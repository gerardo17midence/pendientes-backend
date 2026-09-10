from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import google.generativeai as genai
import json
import os
import io
import datetime
from PIL import Image

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

# Base de datos en memoria (reflejo de tu PDF)
DB = {
    "equipo": ["GERARDO", "CRIS", "MARIO", "HÉCTOR", "GRACIA", "INGRID", "JULIO"],
    "pendientes": [
        {"id": 1, "asignado_a": "GERARDO", "categoria": "TRABAJO", "descripcion": "Seguimiento Computadoras", "dias": "Hoy"},
        {"id": 2, "asignado_a": "GERARDO", "categoria": "TRABAJO", "descripcion": "Ingresar Ticket ON Premise Demand", "dias": "Hoy"},
        {"id": 16, "asignado_a": "CRIS", "categoria": "TRABAJO", "descripcion": "Reportes Migrar a ReportBuilder", "dias": "9d"},
        {"id": 18, "asignado_a": "MARIO", "categoria": "TRABAJO", "descripcion": "Elga Incentivos", "dias": "Hoy"},
        {"id": 24, "asignado_a": "JULIO", "categoria": "TRABAJO", "descripcion": "Revisión de informes", "dias": "0d"}
    ],
    "habitos": [
        {"nombre": "Gimnasio", "registros": {"L": False, "Ma": False, "Mi": False, "J": False, "V": False, "S": False, "D": False}},
        {"nombre": "Lectura 15 min", "registros": {"L": False, "Ma": False, "Mi": False, "J": False, "V": False, "S": False, "D": False}},
        {"nombre": "Tenis", "registros": {"L": False, "Ma": False, "Mi": False, "J": False, "V": False, "S": False, "D": False}}
    ]
}

PROMPT_ANALISIS = """
Analiza esta foto de una hoja impresa de pendientes y hábitos.
1. COMPLETADOS: Identifica números/tareas marcados con tachón, X o check.
2. NUEVAS TAREAS MANUSCRITAS: Busca notas a mano (ej. '+ GERARDO tarea'). Extrae tarea y asignado. Si no hay asignado, es GERARDO.
3. HABIT TRACKER: Identifica qué días están marcados.

Devuelve ÚNICAMENTE un JSON válido (sin Markdown):
{
  "completados_ids": [],
  "nuevas_tareas": [{"asignado_a": "GERARDO", "categoria": "TRABAJO", "descripcion": "Nueva tarea detectada"}],
  "habitos_marcados": {"Gimnasio": ["L"]}
}
"""

@app.get("/api/data")
def get_data():
    return DB

@app.post("/procesar-hoja")
async def procesar_hoja(file: UploadFile = File(...)):
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes))

        model = genai.GenerativeModel('gemini-1.5-pro')
        response = model.generate_content([PROMPT_ANALISIS, image])
        
        raw_text = response.text.strip().replace("```json", "").replace("```", "")
        resultado = json.loads(raw_text)

        # Eliminar completados
        ids_comp = resultado.get("completados_ids", [])
        DB["pendientes"] = [p for p in DB["pendientes"] if p["id"] not in ids_comp]

        # Agregar nuevas tareas
        for nt in resultado.get("nuevas_tareas", []):
            nuevo_id = max([p["id"] for p in DB["pendientes"]] + [0]) + 1
            DB["pendientes"].append({
                "id": nuevo_id,
                "asignado_a": nt.get("asignado_a", "GERARDO").upper(),
                "categoria": nt.get("categoria", "TRABAJO"),
                "descripcion": nt.get("descripcion", "Nueva actividad"),
                "dias": "0d"
            })

        return {"status": "success", "data": DB}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/descargar-pdf")
def descargar_pdf():
    filename = "pendientes.pdf"
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    story = []
    
    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#1A1A1A'))
    story.append(Paragraph("<b>GERARDO - Pendientes</b>", title_style))
    story.append(Spacer(1, 15))

    p_data = [["ID / Tarea", "Asignado", "Días"]]
    for p in DB["pendientes"]:
        p_data.append([f"{p['id']}. {p['descripcion']}", p['asignado_a'], p['dias']])

    t_pend = Table(p_data, colWidths=[350, 100, 50])
    t_pend.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#E5E7EB')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CCCCCC')),
    ]))
    story.append(t_pend)
    doc.build(story)
    
    return FileResponse(filename, media_type="application/pdf", filename="pendientes_actualizados.pdf")
