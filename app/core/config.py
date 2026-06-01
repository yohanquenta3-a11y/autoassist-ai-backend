from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    PROJECT_NAME: str = "API Taller Backend"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Seguridad - JWT
    SECRET_KEY: str = "change-this-secret-key-in-production-environments"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7 # 7 días por defecto
    
    # Base de Datos (PostgreSQL usando asyncpg)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/taller_db"
    
    # AWS S3
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION_NAME: str = "us-east-1"
    AWS_BUCKET_NAME: str = "taller-evidencias-bucket"
    
    # IA - Roboflow
    ROBOFLOW_API_URL: str = ""
    ROBOFLOW_API_KEY: str = ""
    ROBOFLOW_WORKSPACE: str = ""
    ROBOFLOW_WORKFLOW_ID: str = ""
    
    # IA - Google Gemini
    GEMINI_API_KEY: str = ""
    
    # Firebase Cloud Messaging
    FIREBASE_SERVICE_ACCOUNT_PATH: str = ""
    
    # Google Maps API Key para el backend
    GOOGLE_MAPS_BACKEND_KEY: str = ""
    
    # Redis URL para Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Stripe Keys
    STRIPE_SECRET_KEY: str = "sk_test_placeholder"
    STRIPE_WEBHOOK_SECRET: str = "whsec_placeholder"
    # CORS
    BACKEND_CORS_ORIGINS: list[str] = ["*"]
    
    # Pydantic Configuration para leer el .env
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore")

# Instancia global de las configuraciones para importar en todo el proyecto
settings = Settings()
