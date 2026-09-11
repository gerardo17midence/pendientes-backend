from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
import google.generativeai as genai
import json
import os
import io
import datetime
from pydantic import ValidationError
from PIL import Image

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from database import Base, engine, get_db
from models import Tarea, Habito, HabitoRegistro, DIAS_SEMANA, inicio_semana_actual
from schemas import VisionResult, TareaOut, HabitoOut, EstadoCompleto

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Crea las tablas si no existen (no reemplaza a Alembic para el futuro,
# pero es suficiente mientras el esquema sea simple)
Base.metadata.create_all(bind=engine)

# Configuración de clave API de Gemini
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

EQUIPO = ["GERARDO", "CRIS", "MARIO", "HÉCTOR", "GRACIA", "INGRID", "JULIO"]
HABITOS_BASE = ["Gimnasio", "Lectura 15 min", "Tenis"]

PROMPT_ANALISIS = """
Analiza esta foto de una hoja impresa de pendientes y hábitos.

1. COMPLETADOS: identifica qué tareas están marcadas con tachón, X o check.
   Para cada una, devuelve su "id" (el número que aparece junto a la tarea
   en la hoja) y tu nivel de confianza (0 a 1) en que sí está marcada.

2. NUEVAS TAREAS MANUSCRITAS: busca notas a mano con el formato
   "+ NOMBRE tarea" (ej. "+ Julio revisar reporte"). Para cada una,
   extrae a quién está asignada, la descripción, si parece marcada como
   prioritaria (ej. una estrella dibujada), y tu confianza en la lectura.

3. HABIT TRACKER: identifica qué días (L, Ma, Mi, J, V, S, D) están
   marcados en la matriz de hábitos, por cada hábito.

Si no estás seguro de haber leído bien un texto manuscrito, igual
inclúyelo pero con confianza baja (menor a 0.6) en vez de omitirlo.

Devuelve ÚNICAMENTE un JSON válido con esta forma exacta (sin Markdown,
sin texto adicional):
{
  "completados": [{"id": 3, "confianza": 0.95}],
  "nuevas_tareas": [
    {"asignado_a": "JULIO", "categoria": "TRABAJO", "descripcion": "Revisar reporte", "prioritaria": false, "confianza": 0.9}
  ],
  "habitos_marcados": {"Gimnasio": ["L", "Ma"]}
}
"""


def asegurar_habitos_base(db: Session):
    """Crea los hábitos base la primera vez que se usa la base de datos."""
    existentes = {h.nombre for h in db.query(Habito).all()}
    for nombre in HABITOS_BASE:
        if nombre not in existentes:
            db.add(Habito(nombre=nombre))
    db.commit()


@app.on_event("startup")
def startup():
    db = next(get_db())
    try:
        asegurar_habitos_base(db)
    finally:
        db.close()


@app.get("/")
def home():
    return {"status": "ok", "message": "Backend de Pendientes Operativo"}


@app.get("/pendientes", response_model=EstadoCompleto)
def obtener_estado(db: Session = Depends(get_db)):
    """Estado actual completo: pendientes + hábitos de la semana en curso.
    Útil para que el frontend cargue el tablero sin necesidad de subir foto."""
    tareas = db.query(Tarea).filter(Tarea.completada == False).order_by(Tarea.fecha_creada).all()  # noqa: E712

    lunes = datetime.datetime.combine(inicio_semana_actual(), datetime.time.min)
    habitos_out = []
    for hab in db.query(Habito).filter(Habito.activo == True).all():  # noqa: E712
        registros_semana = {
            r.dia: r.marcado
            for r in db.query(HabitoRegistro).filter(
                HabitoRegistro.habito_id == hab.id,
                HabitoRegistro.semana_inicio == lunes,
            ).all()
        }
        registros_completos = {dia: registros_semana.get(dia, False) for dia in DIAS_SEMANA}
        habitos_out.append(HabitoOut(
            nombre=hab.nombre,
            registros=registros_completos,
            completados_semana=sum(registros_completos.values()),
        ))

    return EstadoCompleto(
        pendientes=[TareaOut.model_validate(t) for t in tareas],
        habitos=habitos_out,
    )


@app.post("/procesar-hoja")
async def procesar_hoja(file: UploadFile = File(...), db: Session = Depends(get_db)):
    # 1. Leer y validar la imagen
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes))
    except Exception:
        raise HTTPException(status_code=400, detail="No se pudo leer la imagen enviada.")

    # 2. Llamar a Gemini
    try:
        model = genai.GenerativeModel(
            "gemini-1.5-pro",
            generation_config={"response_mime_type": "application/json"},
        )
        response = model.generate_content([PROMPT_ANALISIS, image])
        raw_text = response.text.strip().replace("```json", "").replace("```", "")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error al llamar a Gemini: {e}")

    # 3. Parsear y validar la forma del JSON antes de tocar la base de datos
    try:
        crudo = json.loads(raw_text)
        resultado = VisionResult.model_validate(crudo)
    except (json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(
            status_code=502,
            detail=f"Gemini devolvió una respuesta con formato inesperado: {e}",
        )

    # 4. Aplicar cambios a la base de datos
    try:
        # Marcar completadas (solo las que Gemini reportó con confianza razonable)
        ids_confirmados = [c.id for c in resultado.completados if c.confianza >= 0.5]
        if ids_confirmados:
            tareas_a_marcar = db.query(Tarea).filter(Tarea.id.in_(ids_confirmados)).all()
            for t in tareas_a_marcar:
                t.marcar_completada()

        # Agregar nuevas tareas
        for nt in resultado.nuevas_tareas:
            db.add(Tarea(
                asignado_a=nt.asignado_a,
                categoria=nt.categoria,
                descripcion=nt.descripcion,
                prioritaria=nt.prioritaria,
            ))

        # Actualizar hábitos de la semana en curso
        lunes = datetime.datetime.combine(inicio_semana_actual(), datetime.time.min)
        for nombre_habito, dias in resultado.habitos_marcados.items():
            habito = db.query(Habito).filter(Habito.nombre == nombre_habito).first()
            if not habito:
                continue  # ignora hábitos que no existen en el catálogo
            for dia in dias:
                registro = db.query(HabitoRegistro).filter(
                    HabitoRegistro.habito_id == habito.id,
                    HabitoRegistro.semana_inicio == lunes,
                    HabitoRegistro.dia == dia,
                ).first()
                if not registro:
                    db.add(HabitoRegistro(habito_id=habito.id, semana_inicio=lunes, dia=dia, marcado=True))

        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar los cambios: {e}")

    # 5. Regenerar el PDF con el estado ya actualizado
    try:
        generar_pdf_file(db)
    except Exception as e:
        # No hacemos rollback: los datos ya se guardaron bien, solo falló el PDF.
        raise HTTPException(status_code=500, detail=f"Los cambios se guardaron pero el PDF falló: {e}")

    return {"status": "success", "data": crudo}


def generar_pdf_file(db: Session):
    filename = "pendientes_actualizados.pdf"
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#1A1A1A'))
    fecha_str = datetime.date.today().strftime("%d.%m.%Y")

    # Página 1: Pendientes
    story.append(Paragraph(f"<b>GERARDO - Pendientes</b><br/><font size=9 color='#666666'>{fecha_str}</font>", title_style))
    story.append(Spacer(1, 15))

    tareas = db.query(Tarea).filter(Tarea.completada == False).order_by(Tarea.fecha_creada).all()  # noqa: E712

    p_data = [["ID / Tarea", "Asignado", "Días"]]
    for t in tareas:
        prefijo = "★ " if t.prioritaria else ("⚠ " if t.revisar else "")
        p_data.append([f"{t.id}. {prefijo}{t.descripcion}", t.asignado_a, f"{t.dias_pendiente}d"])

    t_pend = Table(p_data, colWidths=[350, 100, 50])
    t_pend.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E5E7EB')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
    ]))
    story.append(t_pend)

    story.append(PageBreak())

    # Página 2: Hábitos (semana en curso)
    story.append(Paragraph("<b>GERARDO - Hábitos</b>", title_style))
    story.append(Spacer(1, 15))

    lunes = datetime.datetime.combine(inicio_semana_actual(), datetime.time.min)
    h_data = [["Hábito", "L", "Ma", "Mi", "J", "V", "S", "D", "Semana"]]
    for hab in db.query(Habito).filter(Habito.activo == True).all():  # noqa: E712
        registros = {
            r.dia: r.marcado
            for r in db.query(HabitoRegistro).filter(
                HabitoRegistro.habito_id == hab.id,
                HabitoRegistro.semana_inicio == lunes,
            ).all()
        }
        fila = [hab.nombre]
        comp = 0
        for dia in DIAS_SEMANA:
            marcado = registros.get(dia, False)
            comp += int(marcado)
            fila.append("✓" if marcado else "")
        fila.append(f"{comp}/7")
        h_data.append(fila)

    t_hab = Table(h_data, colWidths=[150] + [35] * 7 + [50])
    t_hab.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E5E7EB')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
    ]))
    story.append(t_hab)

    doc.build(story)


@app.get("/descargar-pdf")
def descargar_pdf(db: Session = Depends(get_db)):
    generar_pdf_file(db)
    return FileResponse("pendientes_actualizados.pdf", media_type="application/pdf", filename="pendientes.pdf")
