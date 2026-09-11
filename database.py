"""
Conexión a la base de datos.

Usa Postgres gestionado (Supabase o Neon, capa gratuita) en vez del
diccionario en memoria. Render borra el filesystem y la memoria del
contenedor en cada redeploy o reinicio, así que la base de datos tiene
que vivir fuera de Render.

Variable de entorno requerida:
    DATABASE_URL  -> cadena de conexión que te da Supabase/Neon, ej:
                     postgresql://usuario:password@host:5432/basededatos

En Render: Settings -> Environment -> agrega DATABASE_URL con ese valor.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "Falta la variable de entorno DATABASE_URL. "
        "Configúrala en Render con la cadena de conexión de Supabase o Neon."
    )

# Supabase/Neon normalmente ya incluyen sslmode=require en la URL;
# esto es un respaldo por si tu URL no lo trae. Solo aplica a Postgres:
# SQLite (usado en pruebas locales) no acepta este argumento y rompería.
connect_args = {}
if DATABASE_URL.startswith("postgresql") and "sslmode" not in DATABASE_URL:
    connect_args = {"sslmode": "require"}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,  # evita errores por conexiones que el servidor cerró por inactividad
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency de FastAPI: entrega una sesión y la cierra siempre al terminar."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
