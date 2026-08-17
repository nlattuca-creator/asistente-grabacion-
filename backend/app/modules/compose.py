"""Fase 3 (no implementada): sugerencias de composición/arreglo/mezcla.

Plan: usar el audio ya analizado (tempo, tonalidad, estructura, stems si
existen) como contexto para pedirle sugerencias a Claude vía API.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/compose", tags=["compose"])


@router.post("/suggest")
async def suggest():
    raise HTTPException(501, "Sugerencias de composición: todavía no implementado (fase 3)")
