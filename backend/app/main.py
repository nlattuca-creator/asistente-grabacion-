import os
import re
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from app.modules import assistant, beatmaker, compose, quantize, stems, tempo  # noqa: E402

app = FastAPI(title="audio-companion", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(tempo.router)
app.include_router(quantize.router)
app.include_router(stems.router)
app.include_router(compose.router)
app.include_router(assistant.router)
app.include_router(beatmaker.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Sirve el frontend (HTML/JS/CSS) desde el mismo proceso/puerto que la API,
# así en un deploy alcanza con una sola URL. En dev local podés seguir
# abriendo frontend/index.html directo si preferís (el campo "URL del
# backend" del formulario cubre ese caso).
_frontend_dir = Path(os.environ.get("FRONTEND_DIR", Path(__file__).resolve().parents[2] / "frontend"))


def _compute_asset_version() -> str:
    """Hash de commit actual, para invalidar el cache del browser en cada
    deploy sin depender de que alguien haga hard-refresh a mano."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_frontend_dir.parent,
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return str(int(time.time()))


_ASSET_VERSION = _compute_asset_version()
_ASSET_REF_RE = re.compile(r'(href|src)="([^"?]+\.(?:css|js))"')


@app.get("/", include_in_schema=False)
async def index() -> HTMLResponse:
    html = (_frontend_dir / "index.html").read_text(encoding="utf-8")
    html = _ASSET_REF_RE.sub(rf'\1="\2?v={_ASSET_VERSION}"', html)
    return HTMLResponse(html)


if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
