"""Creador de batería: genera un patrón de batería (1 compás, resolución de
semicorchea) a partir de una descripción de estilo en texto libre, usando
Claude. Devuelve un ZIP con:

- pattern.mid — para arrastrar a un track de Drummer o tu kit en Logic Pro
  y usar tus propios sonidos. Este es el entregable "real".
- preview.wav — un render rápido con sonidos sintetizados acá mismo, solo
  para escuchar la idea sin abrir Logic. No es calidad de estudio.
- pattern.json — el patrón crudo, por transparencia / para debug.
"""

import io
import json
import os
import zipfile

import mido
import numpy as np
import soundfile as sf
from anthropic import Anthropic, APIError
from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import StreamingResponse
from scipy.signal import butter, lfilter

router = APIRouter(prefix="/api/beatmaker", tags=["beatmaker"])

MODEL = os.environ.get("ASSISTANT_MODEL", "claude-sonnet-5")
SR = 44100
STEPS_PER_BAR = 16
INSTRUMENTS = ("kick", "snare", "closed_hihat", "open_hihat", "clap")
GM_NOTE = {"kick": 36, "snare": 38, "closed_hihat": 42, "open_hihat": 46, "clap": 39}

MIN_BPM = 40
MAX_BPM = 240
MIN_BARS = 1
MAX_BARS = 8

SYSTEM_PROMPT = """Sos un programador de baterías profesional. Te dan un \
estilo musical (texto libre, puede estar en español) y un tempo (BPM), y \
devolvés UN patrón de batería de 1 compás en 4/4, 16 pasos (resolución de \
semicorchea), como JSON estricto — sin texto adicional, sin explicaciones, \
sin backticks de markdown, solo el JSON.

Formato exacto de salida:
{
  "kick": {"0": 120, "8": 100},
  "snare": {"4": 110, "12": 105},
  "closed_hihat": {"0": 80, "2": 70, "4": 85, ...},
  "open_hihat": {"14": 90},
  "clap": {}
}

Reglas:
- Las claves de cada instrumento son el número de paso (string, "0" a "15").
- Los valores son velocidad MIDI (entero 1-127). Variá la velocidad para \
que suene humano, no todo al mismo nivel.
- Solo incluí los pasos donde efectivamente suena ese instrumento (no \
pongas ceros).
- Los instrumentos válidos son exactamente: kick, snare, closed_hihat, \
open_hihat, clap. Si alguno no suena en el patrón, devolvé un objeto vacío \
para ese instrumento.
- Basate en la convención rítmica real del género pedido (ej. trap = \
hihats con rolls/subdivisiones y variación de velocity, boom bap = pocket \
y swing, reggaetón = patrón dembow, rock = kick en 1 y 3 con snare en 2 y \
4, etc.). Si el estilo no es claro, usá tu mejor criterio musical."""


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def _validate_pattern(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("la respuesta no es un objeto JSON")
    pattern = {}
    for inst in INSTRUMENTS:
        hits = raw.get(inst, {})
        if not isinstance(hits, dict):
            raise ValueError(f"'{inst}' debe ser un objeto {{paso: velocidad}}")
        clean = {}
        for step_str, vel in hits.items():
            step = int(step_str)
            if not (0 <= step < STEPS_PER_BAR):
                continue
            vel = max(1, min(127, int(vel)))
            clean[step] = vel
        pattern[inst] = clean
    return pattern


def _call_claude_for_pattern(style: str, bpm: float) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            503,
            "Beatmaker no configurado: falta ANTHROPIC_API_KEY en el backend (ver README).",
        )
    client = Anthropic(api_key=api_key)

    user_prompt = f"Estilo: {style}\nBPM: {bpm}"
    last_error = None
    for attempt in range(2):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except APIError as exc:
            raise HTTPException(502, f"Error llamando a Claude: {exc}") from exc

        text = "".join(b.text for b in response.content if b.type == "text")
        try:
            raw = json.loads(_extract_json(text))
            return _validate_pattern(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            user_prompt = (
                f"Estilo: {style}\nBPM: {bpm}\n\n"
                f"Tu respuesta anterior no era JSON válido con el formato pedido "
                f"({exc}). Devolvé SOLO el JSON, sin texto adicional."
            )

    raise HTTPException(502, f"Claude no devolvió un patrón válido: {last_error}")


def _build_midi(pattern: dict, bpm: float, bars: int) -> bytes:
    ticks_per_beat = 480
    tick_per_step = ticks_per_beat // (STEPS_PER_BAR // 4)  # 4/4, 16 pasos = 4 por beat
    note_len_ticks = max(10, tick_per_step // 2)

    events = []  # (abs_tick, is_on, note, velocity)
    for bar in range(bars):
        bar_offset = bar * STEPS_PER_BAR * tick_per_step
        for inst, hits in pattern.items():
            note = GM_NOTE[inst]
            for step, vel in hits.items():
                on_tick = bar_offset + step * tick_per_step
                events.append((on_tick, True, note, vel))
                events.append((on_tick + note_len_ticks, False, note, vel))

    events.sort(key=lambda e: (e[0], not e[1]))  # note_off antes que note_on si empatan

    midi = mido.MidiFile(ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))

    prev_tick = 0
    for abs_tick, is_on, note, vel in events:
        delta = abs_tick - prev_tick
        prev_tick = abs_tick
        track.append(mido.Message(
            "note_on" if is_on else "note_off",
            note=note, velocity=vel if is_on else 0,
            time=delta, channel=9,
        ))

    buf = io.BytesIO()
    midi.save(file=buf)
    return buf.getvalue()


def _highpass(signal: np.ndarray, cutoff: float) -> np.ndarray:
    b, a = butter(2, cutoff / (SR / 2), btype="high")
    return lfilter(b, a, signal)


def _bandpass(signal: np.ndarray, low: float, high: float) -> np.ndarray:
    b, a = butter(2, [low / (SR / 2), high / (SR / 2)], btype="band")
    return lfilter(b, a, signal)


def _synth_kick() -> np.ndarray:
    t = np.arange(int(SR * 0.25)) / SR
    freq = 150 * np.exp(-t * 18) + 45
    phase = 2 * np.pi * np.cumsum(freq) / SR
    env = np.exp(-t * 14)
    return (np.sin(phase) * env).astype(np.float32)


def _synth_snare() -> np.ndarray:
    t = np.arange(int(SR * 0.2)) / SR
    noise = _bandpass(np.random.uniform(-1, 1, len(t)), 1000, 8000)
    tone = np.sin(2 * np.pi * 180 * t) * np.exp(-t * 40)
    env = np.exp(-t * 22)
    return ((noise * 0.7 + tone * 0.5) * env).astype(np.float32)


def _synth_hihat(open_: bool) -> np.ndarray:
    dur = 0.35 if open_ else 0.08
    t = np.arange(int(SR * dur)) / SR
    noise = _highpass(np.random.uniform(-1, 1, len(t)), 7000)
    decay = 6 if open_ else 35
    env = np.exp(-t * decay)
    return (noise * env * 0.6).astype(np.float32)


def _synth_clap() -> np.ndarray:
    t = np.arange(int(SR * 0.2)) / SR
    noise = _bandpass(np.random.uniform(-1, 1, len(t)), 800, 6000)
    env = np.zeros_like(t)
    for offset in (0.0, 0.01, 0.02, 0.035):
        idx = int(offset * SR)
        if idx < len(env):
            env[idx:] = np.maximum(env[idx:], np.exp(-(t[idx:] - offset) * 30))
    return (noise * env * 0.6).astype(np.float32)


_SYNTH = {
    "kick": lambda: _synth_kick(),
    "snare": lambda: _synth_snare(),
    "closed_hihat": lambda: _synth_hihat(False),
    "open_hihat": lambda: _synth_hihat(True),
    "clap": lambda: _synth_clap(),
}


def _render_preview(pattern: dict, bpm: float, bars: int) -> np.ndarray:
    step_dur = (60.0 / bpm) / (STEPS_PER_BAR / 4)
    total_samples = int(bars * STEPS_PER_BAR * step_dur * SR) + SR  # +1s de cola
    master = np.zeros(total_samples, dtype=np.float32)

    samples = {inst: _SYNTH[inst]() for inst in INSTRUMENTS}

    for bar in range(bars):
        for inst, hits in pattern.items():
            one_shot = samples[inst]
            for step, vel in hits.items():
                start = int((bar * STEPS_PER_BAR + step) * step_dur * SR)
                end = min(start + len(one_shot), len(master))
                if end > start:
                    master[start:end] += one_shot[: end - start] * (vel / 127.0)

    peak = np.max(np.abs(master)) or 1.0
    master = master / peak * 0.9
    return master


@router.post("/generate")
async def generate(
    style: str = Form(...),
    bpm: float = Form(...),
    bars: int = Form(4),
):
    if not style.strip():
        raise HTTPException(400, "Describí el estilo de batería que querés")
    if not (MIN_BPM <= bpm <= MAX_BPM):
        raise HTTPException(400, f"bpm fuera de rango ({MIN_BPM}-{MAX_BPM})")
    if not (MIN_BARS <= bars <= MAX_BARS):
        raise HTTPException(400, f"bars fuera de rango ({MIN_BARS}-{MAX_BARS})")

    pattern = _call_claude_for_pattern(style.strip(), bpm)

    midi_bytes = _build_midi(pattern, bpm, bars)

    preview_audio = _render_preview(pattern, bpm, bars)
    wav_buf = io.BytesIO()
    sf.write(wav_buf, preview_audio, SR, format="WAV")

    # Sin compresión (ZIP_STORED): los archivos ya son chicos/incompresibles
    # (WAV) y esto le permite al frontend extraer preview.wav para
    # reproducirlo al toque, sin descomprimir el ZIP, con un parser mínimo
    # de headers locales (ver zip-lite.js) en vez de sumar una librería de
    # DEFLATE en el browser.
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("pattern.mid", midi_bytes)
        zf.writestr("preview.wav", wav_buf.getvalue())
        zf.writestr("pattern.json", json.dumps(pattern, indent=2, ensure_ascii=False))
    zip_buf.seek(0)

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="bateria.zip"'},
    )
