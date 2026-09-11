"""
Modelos de base de datos (SQLAlchemy).

Reemplaza el diccionario DB en memoria de app.py. Tres tablas:

- Tarea: cada pendiente. "dias_pendiente" se calcula al vuelo desde
  fecha_creada, así que nunca queda desactualizado (arregla el bug del
  "dias": "0d" fijo que tenías).
- Habito: catálogo de hábitos a seguir (Gimnasio, Tenis, etc).
- HabitoRegistro: una fila por (hábito, semana, día). Al empezar una
  semana nueva simplemente no existen registros todavía -> se ve
  desmarcado automáticamente, sin necesidad de resetear nada a mano
  (arregla el bug de que los checks nunca se borraban).
"""

import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from database import Base

DIAS_SEMANA = ["L", "Ma", "Mi", "J", "V", "S", "D"]


def inicio_semana_actual() -> datetime.date:
    """Devuelve la fecha del lunes de la semana actual (ISO: lunes=0)."""
    hoy = datetime.date.today()
    return hoy - datetime.timedelta(days=hoy.weekday())


class Tarea(Base):
    __tablename__ = "tareas"

    id = Column(Integer, primary_key=True, index=True)
    asignado_a = Column(String, nullable=False, index=True)  # GERARDO, CRIS, etc.
    categoria = Column(String, nullable=False, default="TRABAJO")  # TRABAJO / PERSONALES
    descripcion = Column(String, nullable=False)
    prioritaria = Column(Boolean, default=False)      # equivale a tu "★"
    revisar = Column(Boolean, default=False)          # equivale a tu "⚠"
    completada = Column(Boolean, default=False)
    fecha_creada = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    fecha_completada = Column(DateTime, nullable=True)

    @property
    def dias_pendiente(self) -> int:
        """Días desde que la tarea apareció en el tracker (0 = hoy)."""
        referencia = self.fecha_completada or datetime.datetime.utcnow()
        return (referencia - self.fecha_creada).days

    def marcar_completada(self):
        self.completada = True
        self.fecha_completada = datetime.datetime.utcnow()


class Habito(Base):
    __tablename__ = "habitos"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, unique=True, nullable=False)
    activo = Column(Boolean, default=True)  # para poder "archivar" sin borrar el historial

    registros = relationship("HabitoRegistro", back_populates="habito")


class HabitoRegistro(Base):
    __tablename__ = "habito_registros"
    __table_args__ = (
        UniqueConstraint("habito_id", "semana_inicio", "dia", name="uq_habito_semana_dia"),
    )

    id = Column(Integer, primary_key=True, index=True)
    habito_id = Column(Integer, ForeignKey("habitos.id"), nullable=False)
    semana_inicio = Column(DateTime, nullable=False)  # lunes de esa semana, a medianoche
    dia = Column(String, nullable=False)  # 'L', 'Ma', 'Mi', 'J', 'V', 'S', 'D'
    marcado = Column(Boolean, default=True)

    habito = relationship("Habito", back_populates="registros")
