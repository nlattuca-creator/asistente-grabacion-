"""Cuantizado: alinea el timing de una pista (ej. voz) a la grilla rítmica
de otra (ej. piano).

No es un cambio de tempo global (eso es tempo.py): cada "evento" (onset)
del audio a alinear se estira/comprime individualmente para caer en el
punto de grilla más cercano — como el quantize de audio de un DAW
(Flex Time + Quantize en Logic, Warp + Quantize en Ableton), pero
enganchado a la grilla de un archivo de referencia real en vez del
metrónomo interno.

Limitaciones del MVP:
- Procesa en mono (simplifica detección y reensamblado).
- No soporta swing/triplets, solo subdivisiones rectas de la grilla.
- Si no se detectan onsets en la pista a alinear, la devuelve sin cambios.
"""

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

router = APIRouter(prefix="/api/quantize", tags=["quantize"])

SR = 44100
MIN_RATIO = 0.25
MAX_RATIO = 4.0
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100MB
MAX_DURATION_SECONDS = 10 * 60
MAX_SEGMENTS = 400
MIN_SEGMENT_SECONDS = 0.02


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise HTTPException(
            status_code=422,
            detail=f"Fallo procesando audio ({cmd[0]}): {result.stderr.strip()[-2000:]}",
        )


async def _load_normalized(file: UploadFile, work_dir: Path, name: str) -> np.ndarray:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, f"Archivo '{name}' vacío")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Archivo '{name}' demasiado grande (máx 100MB)")

    src_ext = Path(file.filename or name).suffix or ".bin"
    src_path = work_dir / f"{name}{src_ext}"
    src_path.write_bytes(raw)

    norm_path = work_dir / f"{name}_norm.wav"
    _run(["ffmpeg", "-y", "-i", str(src_path), "-ar", str(SR), "-ac", "1", str(norm_path)])

    audio, _ = sf.read(str(norm_path), dtype="float32", always_2d=False)
    if len(audio) / SR > MAX_DURATION_SECONDS:
        raise HTTPException(
            413, f"Archivo '{name}' demasiado largo (máx {MAX_DURATION_SECONDS // 60} min)"
        )
    return audio


def _build_grid(reference: np.ndarray, subdivision: int) -> np.ndarray:
    _, beat_frames = librosa.beat.beat_track(y=reference, sr=SR, units="frames")
    beat_times = librosa.frames_to_time(beat_frames, sr=SR)
    if len(beat_times) < 2:
        raise HTTPException(
            422, "No se pudo detectar una grilla rítmica clara en el archivo de referencia"
        )

    grid = []
    for i in range(len(beat_times) - 1):
        start, end = beat_times[i], beat_times[i + 1]
        grid.extend(start + (end - start) * s / subdivision for s in range(subdivision))
    grid.append(beat_times[-1])

    avg_step = float(np.mean(np.diff(beat_times))) / subdivision
    first = beat_times[0]
    while first - avg_step > 0:
        first -= avg_step
        grid.append(first)
    last = beat_times[-1]
    limit = beat_times[-1] + avg_step * subdivision * 8  # margen extra por si la voz sigue despues
    while last + avg_step < limit:
        last += avg_step
        grid.append(last)

    return np.array(sorted(grid))


def _nearest_grid_point(t: float, grid: np.ndarray) -> float:
    idx = np.searchsorted(grid, t)
    candidates = grid[max(0, idx - 1):idx + 1]
    return float(candidates[np.argmin(np.abs(candidates - t))])


@router.post("/align")
async def align(
    reference: UploadFile,
    target: UploadFile,
    subdivision: int = Form(1),
    strength: float = Form(100.0),
    output_format: str = Form("wav"),
):
    if output_format not in ("wav", "mp3"):
        raise HTTPException(400, "output_format debe ser 'wav' o 'mp3'")
    if not (1 <= subdivision <= 8):
        raise HTTPException(400, "subdivision debe estar entre 1 y 8")
    if not (0 <= strength <= 100):
        raise HTTPException(400, "strength debe estar entre 0 y 100")

    work_dir = Path(tempfile.mkdtemp(prefix="quantize_"))
    try:
        ref_audio = await _load_normalized(reference, work_dir, "reference")
        target_audio = await _load_normalized(target, work_dir, "target")

        grid = _build_grid(ref_audio, subdivision)

        onset_frames = librosa.onset.onset_detect(
            y=target_audio, sr=SR, units="frames", backtrack=True
        )
        onset_times = librosa.frames_to_time(onset_frames, sr=SR)
        duration = len(target_audio) / SR

        boundaries_orig = sorted(
            {0.0, duration, *(float(t) for t in onset_times if 0 < t < duration)}
        )

        if len(boundaries_orig) - 1 > MAX_SEGMENTS:
            raise HTTPException(
                413,
                f"Demasiados eventos detectados ({len(boundaries_orig) - 1}), "
                f"máximo {MAX_SEGMENTS}. Probá con un audio más corto o más limpio.",
            )

        boundaries_target = [0.0]
        for t in boundaries_orig[1:-1]:
            nearest = _nearest_grid_point(t, grid)
            snapped = t + (strength / 100.0) * (nearest - t)
            snapped = max(snapped, boundaries_target[-1] + MIN_SEGMENT_SECONDS)
            boundaries_target.append(snapped)
        # el tramo final (despues del ultimo onset, tipicamente cola/silencio)
        # no se cuantiza, mantiene su duracion original
        last_orig_segment = boundaries_orig[-1] - boundaries_orig[-2]
        boundaries_target.append(boundaries_target[-1] + last_orig_segment)

        segments_out = []
        clamped_count = 0
        for i in range(len(boundaries_orig) - 1):
            start_sample = int(boundaries_orig[i] * SR)
            end_sample = int(boundaries_orig[i + 1] * SR)
            seg = target_audio[start_sample:end_sample]
            orig_dur = len(seg) / SR
            target_dur = boundaries_target[i + 1] - boundaries_target[i]
            if orig_dur <= 0 or target_dur <= 0 or len(seg) == 0:
                continue

            ratio = orig_dur / target_dur
            ratio_clamped = min(max(ratio, MIN_RATIO), MAX_RATIO)
            if ratio_clamped != ratio:
                clamped_count += 1

            if abs(ratio_clamped - 1.0) < 0.01:
                segments_out.append(seg)
                continue

            seg_in_path = work_dir / f"seg_in_{i}.wav"
            seg_out_path = work_dir / f"seg_out_{i}.wav"
            sf.write(str(seg_in_path), seg, SR)
            _run([
                "rubberband", "--tempo", str(ratio_clamped), "-c", "6",
                str(seg_in_path), str(seg_out_path),
            ])
            seg_out, _ = sf.read(str(seg_out_path), dtype="float32", always_2d=False)
            segments_out.append(seg_out)

        final_audio = np.concatenate(segments_out) if segments_out else target_audio
        final_wav = work_dir / "final.wav"
        sf.write(str(final_wav), final_audio, SR)

        if output_format == "mp3":
            final_path = work_dir / f"{uuid.uuid4().hex}.mp3"
            _run([
                "ffmpeg", "-y", "-i", str(final_wav),
                "-codec:a", "libmp3lame", "-q:a", "2",
                str(final_path),
            ])
            media_type = "audio/mpeg"
        else:
            final_path = final_wav
            media_type = "audio/wav"

        download_name = f"{Path(target.filename or 'audio').stem}_quantized.{output_format}"
        response = FileResponse(
            final_path,
            media_type=media_type,
            filename=download_name,
            background=BackgroundTask(shutil.rmtree, work_dir, ignore_errors=True),
        )
        response.headers["X-Quantize-Segments"] = str(len(segments_out))
        response.headers["X-Quantize-Clamped"] = str(clamped_count)
        return response
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
