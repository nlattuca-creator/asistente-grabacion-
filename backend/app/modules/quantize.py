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

import io
import json
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
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


def _detect_bpm(audio: np.ndarray) -> float:
    tempo, _ = librosa.beat.beat_track(y=audio, sr=SR)
    return float(tempo[0]) if hasattr(tempo, "__len__") else float(tempo)


def _nearest_grid_point(t: float, grid: np.ndarray) -> float:
    idx = np.searchsorted(grid, t)
    candidates = grid[max(0, idx - 1):idx + 1]
    return float(candidates[np.argmin(np.abs(candidates - t))])


def _detect_onsets(target_audio: np.ndarray, prefix: str) -> list[float]:
    onset_frames = librosa.onset.onset_detect(
        y=target_audio, sr=SR, units="frames", backtrack=True
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=SR)
    duration = len(target_audio) / SR
    onsets = sorted(float(t) for t in onset_times if 0 < t < duration)

    if len(onsets) + 1 > MAX_SEGMENTS:
        raise HTTPException(
            413,
            f"'{prefix}': demasiados eventos detectados ({len(onsets) + 1}), "
            f"máximo {MAX_SEGMENTS}. Probá con un audio más corto o más limpio.",
        )
    return onsets


def _compute_boundaries(
    onsets: list[float], duration: float, grid: np.ndarray, strength: float,
) -> tuple[list[float], list[float]]:
    """A partir de los onsets detectados, sugiere a dónde debería moverse cada
    uno (grid-snap con la fuerza pedida). Devuelve (boundaries_orig, boundaries_target),
    ambos incluyendo 0.0 y duration en las puntas."""
    boundaries_orig = [0.0, *onsets, duration]

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

    return boundaries_orig, boundaries_target


def _parse_events_json(events_json: str) -> list:
    try:
        events_list = json.loads(events_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"'events' no es JSON válido: {exc}") from exc
    if not isinstance(events_list, list):
        raise HTTPException(400, "'events' debe ser una lista")
    if len(events_list) > MAX_SEGMENTS:
        raise HTTPException(413, f"Demasiados eventos ({len(events_list)}), máximo {MAX_SEGMENTS}")
    return events_list


def _events_to_pairs(events_list: list) -> list[tuple[float, float]]:
    try:
        return sorted(
            ((float(e["orig_time"]), float(e["target_time"])) for e in events_list),
            key=lambda e: e[0],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            400, "cada evento necesita 'orig_time' y 'target_time' numéricos"
        ) from exc


def _boundaries_from_pairs(
    parsed_events: list[tuple[float, float]], duration: float,
) -> tuple[list[float], list[float]]:
    boundaries_orig = [0.0] + [t for t, _ in parsed_events if 0 < t < duration] + [duration]
    boundaries_target = [0.0]
    for _, target_time in parsed_events:
        snapped = max(target_time, boundaries_target[-1] + MIN_SEGMENT_SECONDS)
        boundaries_target.append(snapped)
    last_orig_segment = boundaries_orig[-1] - boundaries_orig[-2]
    boundaries_target.append(boundaries_target[-1] + last_orig_segment)
    return boundaries_orig, boundaries_target


def _render_boundaries(
    target_audio: np.ndarray,
    boundaries_orig: list[float],
    boundaries_target: list[float],
    work_dir: Path,
    prefix: str,
) -> tuple[np.ndarray, int, int]:
    """Estira/comprime cada segmento entre boundaries_orig[i]..[i+1] para que
    dure boundaries_target[i+1]-boundaries_target[i]. Devuelve (audio final,
    segmentos, cuántos se limitaron por estiramiento extremo)."""
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

        seg_in_path = work_dir / f"{prefix}_seg_in_{i}.wav"
        seg_out_path = work_dir / f"{prefix}_seg_out_{i}.wav"
        sf.write(str(seg_in_path), seg, SR)
        _run([
            "rubberband", "--tempo", str(ratio_clamped), "-c", "6",
            str(seg_in_path), str(seg_out_path),
        ])
        seg_out, _ = sf.read(str(seg_out_path), dtype="float32", always_2d=False)
        segments_out.append(seg_out)

    final_audio = np.concatenate(segments_out) if segments_out else target_audio
    return final_audio, len(segments_out), clamped_count


def _quantize_to_grid(
    target_audio: np.ndarray, grid: np.ndarray, strength: float, work_dir: Path, prefix: str,
) -> tuple[np.ndarray, int, int]:
    """Alinea target_audio a la grilla de punta a punta (detecta + sugiere +
    renderiza). Usado por /align y /align_session, que no necesitan el paso
    intermedio editable de /analyze + /render."""
    onsets = _detect_onsets(target_audio, prefix)
    duration = len(target_audio) / SR
    boundaries_orig, boundaries_target = _compute_boundaries(onsets, duration, grid, strength)
    return _render_boundaries(target_audio, boundaries_orig, boundaries_target, work_dir, prefix)


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

        final_audio, n_segments, clamped_count = _quantize_to_grid(
            target_audio, grid, strength, work_dir, "t"
        )
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
        response.headers["X-Quantize-Segments"] = str(n_segments)
        response.headers["X-Quantize-Clamped"] = str(clamped_count)
        return response
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


@router.post("/align_session")
async def align_session(
    reference: UploadFile,
    targets: list[UploadFile] = File(...),
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
    if not targets:
        raise HTTPException(400, "Mandá al menos una pista para alinear")
    if len(targets) > 8:
        raise HTTPException(400, "Máximo 8 pistas por sesión")

    work_dir = Path(tempfile.mkdtemp(prefix="session_"))
    try:
        ref_audio = await _load_normalized(reference, work_dir, "reference")
        grid = _build_grid(ref_audio, subdivision)

        report = []
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_STORED) as zf:
            for idx, target in enumerate(targets):
                stem = Path(target.filename or f"pista_{idx + 1}").stem
                target_audio = await _load_normalized(target, work_dir, f"target_{idx}")

                final_audio, n_segments, clamped_count = _quantize_to_grid(
                    target_audio, grid, strength, work_dir, f"t{idx}"
                )

                final_wav = work_dir / f"out_{idx}.wav"
                sf.write(str(final_wav), final_audio, SR)

                if output_format == "mp3":
                    out_path = work_dir / f"out_{idx}.mp3"
                    _run([
                        "ffmpeg", "-y", "-i", str(final_wav),
                        "-codec:a", "libmp3lame", "-q:a", "2",
                        str(out_path),
                    ])
                else:
                    out_path = final_wav

                entry_name = f"{idx + 1:02d}_{stem}_quantized.{output_format}"
                zf.write(str(out_path), entry_name)
                report.append({
                    "file": entry_name, "segments": n_segments, "clamped": clamped_count,
                })

            zf.writestr("report.json", json.dumps(report, indent=2, ensure_ascii=False))

        zip_buf.seek(0)
        shutil.rmtree(work_dir, ignore_errors=True)

        return StreamingResponse(
            zip_buf,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="sesion_alineada.zip"',
                "X-Session-Tracks": str(len(targets)),
            },
        )
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


@router.post("/analyze")
async def analyze(
    reference: UploadFile,
    target: UploadFile,
    subdivision: int = Form(1),
    strength: float = Form(100.0),
):
    """Detecta la grilla del reference y los onsets del target, y devuelve
    dónde sugiere mover cada uno — sin tocar el audio todavía. El frontend
    muestra esto en waveforms editables; lo que el usuario confirme (tal
    cual o corregido a mano) se manda después a /render."""
    if not (1 <= subdivision <= 8):
        raise HTTPException(400, "subdivision debe estar entre 1 y 8")
    if not (0 <= strength <= 100):
        raise HTTPException(400, "strength debe estar entre 0 y 100")

    work_dir = Path(tempfile.mkdtemp(prefix="analyze_"))
    try:
        ref_audio = await _load_normalized(reference, work_dir, "reference")
        target_audio = await _load_normalized(target, work_dir, "target")

        grid = _build_grid(ref_audio, subdivision)
        onsets = _detect_onsets(target_audio, "target")
        duration = len(target_audio) / SR
        boundaries_orig, boundaries_target = _compute_boundaries(onsets, duration, grid, strength)

        events = [
            {"orig_time": boundaries_orig[i], "suggested_time": boundaries_target[i]}
            for i in range(1, len(boundaries_orig) - 1)
        ]
        grid_in_range = [float(g) for g in grid if -0.5 <= g <= duration + 0.5]

        return {"duration": duration, "events": events, "grid": grid_in_range}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@router.post("/render")
async def render(
    target: UploadFile,
    events: str = Form(...),
    output_format: str = Form("wav"),
):
    """Renderiza el target con los puntos de /analyze, tal cual o corregidos
    a mano por el usuario en el frontend. No necesita el reference de nuevo
    — los tiempos finales ya vienen decididos en `events`."""
    if output_format not in ("wav", "mp3"):
        raise HTTPException(400, "output_format debe ser 'wav' o 'mp3'")

    parsed_events = _events_to_pairs(_parse_events_json(events))

    work_dir = Path(tempfile.mkdtemp(prefix="render_"))
    try:
        target_audio = await _load_normalized(target, work_dir, "target")
        duration = len(target_audio) / SR
        boundaries_orig, boundaries_target = _boundaries_from_pairs(parsed_events, duration)

        final_audio, n_segments, clamped_count = _render_boundaries(
            target_audio, boundaries_orig, boundaries_target, work_dir, "r"
        )
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
        response.headers["X-Quantize-Segments"] = str(n_segments)
        response.headers["X-Quantize-Clamped"] = str(clamped_count)
        return response
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


@router.post("/analyze_session")
async def analyze_session(
    reference: UploadFile,
    targets: list[UploadFile] = File(...),
    subdivision: int = Form(1),
    strength: float = Form(100.0),
):
    """Version multi-pista de /analyze: una referencia, N pistas, un evento
    por onset detectado en cada una."""
    if not (1 <= subdivision <= 8):
        raise HTTPException(400, "subdivision debe estar entre 1 y 8")
    if not (0 <= strength <= 100):
        raise HTTPException(400, "strength debe estar entre 0 y 100")
    if not targets:
        raise HTTPException(400, "Mandá al menos una pista para alinear")
    if len(targets) > 8:
        raise HTTPException(400, "Máximo 8 pistas por sesión")

    work_dir = Path(tempfile.mkdtemp(prefix="analyzesession_"))
    try:
        ref_audio = await _load_normalized(reference, work_dir, "reference")
        grid = _build_grid(ref_audio, subdivision)
        reference_bpm = _detect_bpm(ref_audio)

        tracks = []
        max_duration = 0.0
        for idx, target in enumerate(targets):
            stem = Path(target.filename or f"pista_{idx + 1}").stem
            target_audio = await _load_normalized(target, work_dir, f"target_{idx}")
            duration = len(target_audio) / SR
            max_duration = max(max_duration, duration)

            onsets = _detect_onsets(target_audio, stem)
            boundaries_orig, boundaries_target = _compute_boundaries(onsets, duration, grid, strength)
            events = [
                {"orig_time": boundaries_orig[i], "suggested_time": boundaries_target[i]}
                for i in range(1, len(boundaries_orig) - 1)
            ]
            # Tempo global propio de la pista, aparte de los eventos puntuales.
            # Si un track viene tocado/cantado a otro tempo de punta a punta
            # (no solo desvíos sueltos), esto lo muestra aunque el cuantizado
            # por onsets igual lo termine corrigiendo evento por evento.
            detected_bpm = _detect_bpm(target_audio)

            tracks.append({
                "filename": target.filename or f"{stem}.wav",
                "duration": duration,
                "events": events,
                "detected_bpm": round(detected_bpm, 1),
            })

        grid_in_range = [float(g) for g in grid if -0.5 <= g <= max_duration + 0.5]
        return {
            "grid": grid_in_range,
            "reference_bpm": round(reference_bpm, 1),
            "tracks": tracks,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@router.post("/render_session")
async def render_session(
    targets: list[UploadFile] = File(...),
    events: str = Form(...),
    output_format: str = Form("wav"),
):
    """Version multi-pista de /render: `events` es un array JSON con un
    array de eventos por cada pista de `targets`, en el mismo orden."""
    if output_format not in ("wav", "mp3"):
        raise HTTPException(400, "output_format debe ser 'wav' o 'mp3'")
    if not targets:
        raise HTTPException(400, "Mandá al menos una pista para alinear")
    if len(targets) > 8:
        raise HTTPException(400, "Máximo 8 pistas por sesión")

    try:
        all_events = json.loads(events)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"'events' no es JSON válido: {exc}") from exc
    if not isinstance(all_events, list) or len(all_events) != len(targets):
        raise HTTPException(400, "'events' debe tener un array por cada pista, en el mismo orden que 'targets'")

    work_dir = Path(tempfile.mkdtemp(prefix="rendersession_"))
    try:
        report = []
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_STORED) as zf:
            for idx, target in enumerate(targets):
                stem = Path(target.filename or f"pista_{idx + 1}").stem
                parsed_events = _events_to_pairs(_parse_events_json(json.dumps(all_events[idx])))

                target_audio = await _load_normalized(target, work_dir, f"target_{idx}")
                duration = len(target_audio) / SR
                boundaries_orig, boundaries_target = _boundaries_from_pairs(parsed_events, duration)

                final_audio, n_segments, clamped_count = _render_boundaries(
                    target_audio, boundaries_orig, boundaries_target, work_dir, f"r{idx}"
                )

                final_wav = work_dir / f"out_{idx}.wav"
                sf.write(str(final_wav), final_audio, SR)

                if output_format == "mp3":
                    out_path = work_dir / f"out_{idx}.mp3"
                    _run([
                        "ffmpeg", "-y", "-i", str(final_wav),
                        "-codec:a", "libmp3lame", "-q:a", "2",
                        str(out_path),
                    ])
                else:
                    out_path = final_wav

                entry_name = f"{idx + 1:02d}_{stem}_quantized.{output_format}"
                zf.write(str(out_path), entry_name)
                report.append({
                    "file": entry_name, "segments": n_segments, "clamped": clamped_count,
                })

            zf.writestr("report.json", json.dumps(report, indent=2, ensure_ascii=False))

        zip_buf.seek(0)
        shutil.rmtree(work_dir, ignore_errors=True)

        return StreamingResponse(
            zip_buf,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="sesion_alineada.zip"',
                "X-Session-Tracks": str(len(targets)),
            },
        )
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
