"""
Schemas de Pydantic.

Tres usos:
1. Validar la respuesta de Gemini ANTES de tocar la base de datos.
2. Formatear las respuestas de la API hacia el frontend.
3. Definir la forma de respuesta compartida entre /pendientes y
   /procesar-hoja, para que el frontend siempre reciba el estado
   COMPLETO persistido — nunca un fragmento parcial de una sola foto.
"""

from typing import List, Dict
from pydantic import BaseModel, Field, field_validator

DIAS_VALIDOS = {"L", "Ma", "Mi", "J", "V", "S", "D"}


# ---------- Validación de la respuesta de Gemini ----------

class ItemCompletado(BaseModel):
    id: int
    confianza: float = Field(default=1.0, ge=0, le=1)


class NuevaTarea(BaseModel):
    asignado_a: str
    categoria: str = "TRABAJO"
    descripcion: str
    prioritaria: bool = False
    confianza: float = Field(default=1.0, ge=0, le=1)

    @field_validator("asignado_a")
    @classmethod
    def normalizar_nombre(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("categoria")
    @classmethod
    def normalizar_categoria(cls, v: str) -> str:
        v = v.strip().upper()
        return v if v in {"TRABAJO", "PERSONALES"} else "TRABAJO"


class VisionResult(BaseModel):
    """Forma esperada del JSON que devuelve Gemini. Si Gemini se desvía
    de esto, Pydantic lanza un error claro antes de escribir nada en la DB."""
    completados: List[ItemCompletado] = Field(default_factory=list)
    nuevas_tareas: List[NuevaTarea] = Field(default_factory=list)
    habitos_marcados: Dict[str, List[str]] = Field(default_factory=dict)

    @field_validator("habitos_marcados")
    @classmethod
    def filtrar_dias_validos(cls, v: Dict[str, List[str]]) -> Dict[str, List[str]]:
        return {
            habito: [d for d in dias if d in DIAS_VALIDOS]
            for habito, dias in v.items()
        }


# ---------- Respuestas de la API hacia el frontend ----------

class TareaOut(BaseModel):
    id: int
    asignado_a: str
    categoria: str
    descripcion: str
    prioritaria: bool
    revisar: bool
    dias_pendiente: int

    model_config = {"from_attributes": True}


class HabitoOut(BaseModel):
    nombre: str
    registros: Dict[str, bool]  # {"L": True, "Ma": False, ...}
    completados_semana: int

    model_config = {"from_attributes": True}


class EstadoCompleto(BaseModel):
    """Estado completo del tablero: se usa como respuesta tanto de
    GET /pendientes (carga inicial) como de POST /procesar-hoja
    (después de aplicar los cambios de una foto). Así el frontend
    SIEMPRE renderiza desde la misma forma de datos, ya persistidos
    en la base de datos — nunca desde un fragmento parcial."""
    pendientes: List[TareaOut]
    habitos: List[HabitoOut]


class ProcesarHojaResponse(EstadoCompleto):
    status: str = "success"
