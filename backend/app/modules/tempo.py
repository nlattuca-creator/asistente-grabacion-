"""Fase 1: edición de tempo/pitch.

Time-stretching con Rubber Band (preserva el tono al cambiar el tempo).
ffmpeg se usa solo para normalizar el input a WAV y, si se pide, exportar
el output a mp3 — Rubber Band CLI trabaja con WAV.
"""

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import librosa
from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

router = APIRouter(prefix="/api/tempo", tags=["tempo"])

MIN_RATIO = 0.25
MAX_RATIO = 4.0
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100MB


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise HTTPException(
            status_code=422,
            detail=f"Fallo procesando audio ({cmd[0]}): {result.stderr.strip()[-2000:]}",
        )


def _cleanup(work_dir: Path) -> None:
    shutil.rmtree(work_dir, ignore_errors=True)


async def _save_and_normalize(file: UploadFile) -> tuple[Path, Path]:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Archivo vacío")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Archivo demasiado grande (máx 100MB)")

    work_dir = Path(tempfile.mkdtemp(prefix="tempo_"))
    src_ext = Path(file.filename or "input").suffix or ".bin"
    src_path = work_dir / f"input{src_ext}"
    src_path.write_bytes(raw)

    normalized_wav = work_dir / "normalized.wav"
    _run([
        "ffmpeg", "-y", "-i", str(src_path),
        "-ar", "44100", "-ac", "2",
        str(normalized_wav),
    ])
    return work_dir, normalized_wav


@router.post("/detect")
async def detect_tempo(file: UploadFile):
    work_dir, normalized_wav = await _save_and_normalize(file)
    try:
        y, sr = librosa.load(str(normalized_wav), sr=None, mono=True)
        tempo = librosa.beat.beat_track(y=y, sr=sr)[0]
        bpm = float(tempo[0]) if hasattr(tempo, "__len__") else float(tempo)
    except Exception as exc:
        raise HTTPException(422, f"No se pudo detectar el BPM: {exc}") from exc
    finally:
        _cleanup(work_dir)

    return {"bpm": round(bpm, 1)}


@router.post("/process")
async def process_tempo(
    file: UploadFile,
    tempo_ratio: float | None = Form(None),
    bpm_from: float | None = Form(None),
    bpm_to: float | None = Form(None),
    output_format: str = Form("wav"),
):
    if output_format not in ("wav", "mp3"):
        raise HTTPException(400, "output_format debe ser 'wav' o 'mp3'")

    if tempo_ratio is None:
        if bpm_from is None or bpm_to is None:
            raise HTTPException(
                400, "Mandá tempo_ratio, o bpm_from + bpm_to"
            )
        if bpm_from <= 0 or bpm_to <= 0:
            raise HTTPException(400, "bpm_from/bpm_to deben ser positivos")
        tempo_ratio = bpm_to / bpm_from

    if not (MIN_RATIO <= tempo_ratio <= MAX_RATIO):
        raise HTTPException(
            400,
            f"tempo_ratio fuera de rango razonable ({MIN_RATIO}-{MAX_RATIO}): {tempo_ratio}",
        )

    work_dir, normalized_wav = await _save_and_normalize(file)

    stretched_wav = work_dir / "stretched.wav"
    _run([
        "rubberband", "--tempo", str(tempo_ratio), "-c", "6",
        str(normalized_wav), str(stretched_wav),
    ])

    if output_format == "mp3":
        final_path = work_dir / f"{uuid.uuid4().hex}.mp3"
        _run([
            "ffmpeg", "-y", "-i", str(stretched_wav),
            "-codec:a", "libmp3lame", "-q:a", "2",
            str(final_path),
        ])
        media_type = "audio/mpeg"
    else:
        final_path = stretched_wav
        media_type = "audio/wav"

    download_name = f"{Path(file.filename or 'audio').stem}_tempo{tempo_ratio:.3f}.{output_format}"
    return FileResponse(
        final_path,
        media_type=media_type,
        filename=download_name,
        background=BackgroundTask(_cleanup, work_dir),
    )
