"""Fase 2 (no implementada): separación de stems.

Plan: correr un modelo tipo Demucs server-side sobre el audio subido,
devolver pistas separadas (voz, batería, bajo, resto) para poder mezclarlas
por separado. Requiere GPU/CPU con más recursos que el módulo de tempo —
se arma como módulo aparte para no complicar la fase 1.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/stems", tags=["stems"])


@router.post("/separate")
async def separate_stems():
    raise HTTPException(501, "Separación de stems: todavía no implementado (fase 2)")
