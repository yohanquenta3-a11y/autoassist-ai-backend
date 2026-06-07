from fastapi import FastAPI
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

# Configuración de CORS

app.add_middleware(AuditMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS or ["*"],
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
