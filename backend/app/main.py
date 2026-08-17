import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()

from app.modules import assistant, compose, quantize, stems, tempo  # noqa: E402

app = FastAPI(title="audio-companion", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tempo.router)
app.include_router(quantize.router)
app.include_router(stems.router)
app.include_router(compose.router)
app.include_router(assistant.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Sirve el frontend (HTML/JS/CSS) desde el mismo proceso/puerto que la API,
# así en un deploy alcanza con una sola URL. En dev local podés seguir
# abriendo frontend/index.html directo si preferís (el campo "URL del
# backend" del formulario cubre ese caso).
_frontend_dir = Path(os.environ.get("FRONTEND_DIR", Path(__file__).resolve().parents[2] / "frontend"))
if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
