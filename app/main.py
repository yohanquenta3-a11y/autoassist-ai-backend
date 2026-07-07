from html import escape

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings
from app.core.exceptions import setup_exception_handlers
from app.core.middleware import AuditMiddleware
from app.core.push_notifications import PushNotificationService

# Inicializar Firebase Admin SDK
PushNotificationService.initialize()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="API para la gestión del taller mecánico",
    version=settings.VERSION
)

# Middleware de auditoría
app.add_middleware(AuditMiddleware)

# Configuración de CORS
# Permite localhost y cualquier subdominio de Vercel, por ejemplo:
# https://autoassist-ai-frontend-xl4v.vercel.app
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_origin_regex=r"^https://.*\.vercel\.app$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Inicializar manejadores de excepciones globales
setup_exception_handlers(app)

# Incluir el router principal que agrupa los demás
app.include_router(api_router, prefix=settings.API_V1_STR)

from app.packages.identity.presentation.websocket import router as ws_router
app.include_router(ws_router)


@app.get("/")
def read_root():
    return {"message": "Bienvenido a la API del Taller"}


@app.get("/vehicle-card", response_class=HTMLResponse)
def vehicle_card(
    marca: str = "",
    modelo: str = "",
    matricula: str = "",
    ano: str = "",
    color: str = "",
    id_vehiculo: str = "",
):
    vehicle_name = f"{marca} {modelo}".strip() or "Vehiculo"
    safe_vehicle_name = escape(vehicle_name)
    safe_plate = escape(matricula.upper() or "SIN MATRICULA")
    safe_year = escape(ano or "No registrado")
    safe_color = escape(color or "No registrado")
    safe_id = escape(id_vehiculo or "No registrado")

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ficha vehicular AutoAssist AI</title>
  <style>
    body {{
      margin: 0;
      background: linear-gradient(135deg, #f5fbfc, #d8eef1);
      font-family: Arial, sans-serif;
      color: #172033;
    }}
    .wrap {{
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 22px;
      box-sizing: border-box;
    }}
    .card {{
      width: 100%;
      max-width: 430px;
      background: white;
      border-radius: 28px;
      padding: 24px;
      box-shadow: 0 16px 40px rgba(0,0,0,.14);
      border: 1px solid #cbe4ea;
      box-sizing: border-box;
    }}
    .brand {{
      color: #0f766e;
      font-weight: 800;
      letter-spacing: .6px;
      font-size: 13px;
    }}
    h1 {{
      margin: 10px 0 4px;
      font-size: 27px;
      line-height: 1.05;
    }}
    .vehicle {{
      color: #466175;
      margin-bottom: 14px;
      font-weight: 700;
    }}
    .plate {{
      display: inline-block;
      margin: 4px 0 18px;
      padding: 9px 13px;
      border-radius: 12px;
      background: #ecfeff;
      color: #0f766e;
      font-family: monospace;
      font-weight: 900;
      letter-spacing: 1px;
    }}
    .row {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      border-top: 1px solid #e5eef0;
      padding: 12px 0;
      font-size: 15px;
    }}
    .label {{ color: #466175; font-weight: 700; }}
    .value {{ font-weight: 800; text-align: right; word-break: break-word; }}
    .note {{
      margin-top: 18px;
      padding: 12px;
      border-radius: 16px;
      background: #f0fafb;
      color: #466175;
      font-size: 13px;
      line-height: 1.35;
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="card">
      <div class="brand">AUTOASSIST AI</div>
      <h1>Ficha vehicular</h1>
      <div class="vehicle">{safe_vehicle_name}</div>
      <div class="plate">{safe_plate}</div>
      <div class="row"><span class="label">Ano</span><span class="value">{safe_year}</span></div>
      <div class="row"><span class="label">Color</span><span class="value">{safe_color}</span></div>
      <div class="row"><span class="label">ID vehiculo</span><span class="value">{safe_id}</span></div>
      <div class="note">Carnet virtual generado por AutoAssist AI. Esta ficha solo contiene datos basicos del vehiculo.</div>
    </section>
  </main>
</body>
</html>"""
