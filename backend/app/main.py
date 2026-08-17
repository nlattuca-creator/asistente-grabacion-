from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.modules import assistant, compose, stems, tempo  # noqa: E402

app = FastAPI(title="audio-companion", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tempo.router)
app.include_router(stems.router)
app.include_router(compose.router)
app.include_router(assistant.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
