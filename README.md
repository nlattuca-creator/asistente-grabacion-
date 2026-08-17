# audio-companion

Compañero de edición, mezcla y mastering asistido por IA. Le subís audio,
le pedís cambios (tempo, separación de pistas, sugerencias de composición) y
vas iterando el trabajo con él.

## Estado

**Fase 1 (implementada):** edición de tempo/pitch. Subís un audio (por ahora
pensado para voz sola), le decís el tempo objetivo, y te devuelve el archivo
re-temporizado **preservando el tono** (no es un simple "pitch up/down" al
acelerar — es time-stretching real vía [Rubber Band](https://breakfastquay.com/rubberband/)).

**Fase 2 (planeada):** separación de stems (voz/instrumentos) sobre una mezcla,
para poder ajustar niveles de cada pista por separado. Necesita un modelo tipo
Demucs corriendo server-side — no anda bien en el browser.

**Fase 3 (planeada):** sugerencias de composición/arreglo/mezcla con Claude,
usando como contexto el audio ya analizado (tempo, tonalidad, estructura).

**Asistente de chat (implementado, sin probar contra Claude real):** ventana
de diálogo flotante para preguntas de conocimiento general sobre producción
musical y Logic Pro (atajos, dónde está tal función, cómo se hace tal cosa).
No analiza tu audio — para eso es la fase 3. Requiere una API key de
Anthropic propia de este proyecto (ver abajo).

La arquitectura (backend Python separado del frontend) está pensada desde el
día 1 para soportar las tres fases sin reescribir nada: cada módulo nuevo es
un router más en `backend/app/modules/`.

## Arquitectura

```
audio-companion/
  backend/            FastAPI (Python) — todo el procesamiento pesado de audio
    app/
      main.py          entrypoint, monta los routers de cada módulo
      modules/
        tempo.py        Fase 1: tempo/pitch (rubberband + ffmpeg)
        stems.py         Fase 2: separación de stems (placeholder)
        compose.py       Fase 3: sugerencias con Claude (placeholder)
        assistant.py     Chat de Q&A general (Claude, sin analizar audio)
    requirements.txt
    .env.example
  frontend/            Página web simple (HTML/JS vanilla, sin build step)
    index.html
    app.js              lógica del formulario de tempo
    chat.js              lógica del panel de chat flotante
    style.css
```

Por qué backend separado en vez de todo en el browser: la separación de
stems (fase 2) necesita modelos pesados (tipo Demucs) que no corren bien en
JS/WASM. Arrancar con esa arquitectura desde la fase 1, aunque el módulo de
tempo sea liviano, evita tener que reescribir todo cuando lleguemos a fase 2.

## Cómo correrlo local

Requiere `ffmpeg` y `rubberband-cli` instalados en el sistema (Debian/Ubuntu:
`sudo apt-get install ffmpeg rubberband-cli`).

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend: abrir `frontend/index.html` directamente en el browser (apunta a
`http://localhost:8000` por default), o servirlo con cualquier server
estático.

## Módulo 1: tempo/pitch

`POST /api/tempo/process` — multipart form:
- `file`: archivo de audio (wav, mp3, m4a, etc.)
- `tempo_ratio` **o** (`bpm_from` + `bpm_to`): a cuánto cambiar el tempo.
  Ej: `tempo_ratio=1.15` = 15% más rápido. `bpm_from=90&bpm_to=100` calcula
  el ratio solo.
- `output_format` (opcional, default `wav`): `wav` o `mp3`.

Devuelve el archivo procesado. El pitch se preserva automáticamente (eso es
lo que diferencia esto de simplemente acelerar el archivo).

## Asistente de chat

1. `cp backend/.env.example backend/.env`
2. Completar `ANTHROPIC_API_KEY` en ese `.env` (nunca se commitea — está en
   `.gitignore`). Opcionalmente `ASSISTANT_MODEL` (default `claude-sonnet-5`).
3. Reiniciar el backend. El botón 💬 abre el panel de chat en el frontend.

`POST /api/assistant/chat` — JSON `{"messages": [{"role": "user"|"assistant", "content": "..."}]}`.
El historial completo viaja desde el cliente en cada request (no hay estado
en el server). Devuelve `{"role": "assistant", "content": "..."}`.
