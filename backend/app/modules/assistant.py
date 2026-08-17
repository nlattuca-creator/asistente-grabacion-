"""Ventana de chat: asistente de preguntas sobre producción musical / Logic Pro.

No analiza el audio del usuario (para eso está compose.py, fase 3) — es un
chat de conocimiento general tipo "¿cómo hago X en Logic Pro?", con el
historial de la conversación viajando desde el cliente en cada request
(sin estado en el server, así el MVP no necesita sesiones/DB).
"""

import os

from anthropic import Anthropic, APIError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

MODEL = os.environ.get("ASSISTANT_MODEL", "claude-sonnet-5")
MAX_HISTORY_MESSAGES = 40

SYSTEM_PROMPT = (
    "Sos un asistente experto en producción musical, mezcla, mastering y, en "
    "particular, Logic Pro. Respondés en español (Argentina, forma 'vos'), "
    "de manera directa y técnica. Cuando expliques una función de Logic Pro, "
    "mencioná el nombre exacto del menú/panel/atajo cuando lo sepas. Si una "
    "pregunta depende de la versión de Logic Pro y no te la dieron, aclaralo "
    "en vez de asumir. Si no estás seguro de algo específico de la UI, decilo "
    "en vez de inventar rutas de menú."
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)


def _client() -> Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            503,
            "Chat no configurado: falta ANTHROPIC_API_KEY en el backend (ver README).",
        )
    return Anthropic(api_key=api_key)


@router.post("/chat")
async def chat(request: ChatRequest):
    for msg in request.messages:
        if msg.role not in ("user", "assistant"):
            raise HTTPException(400, f"role inválido: {msg.role}")

    history = request.messages[-MAX_HISTORY_MESSAGES:]

    client = _client()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": m.role, "content": m.content} for m in history],
        )
    except APIError as exc:
        raise HTTPException(502, f"Error llamando a Claude: {exc}") from exc

    text = "".join(block.text for block in response.content if block.type == "text")
    return {"role": "assistant", "content": text}
