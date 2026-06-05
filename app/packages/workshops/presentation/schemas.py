from pydantic import BaseModel, EmailStr, Field
from typing import Optional
import uuid
from datetime import datetime


# --- Requests ---

class TallerCreate(BaseModel):
    nombre: str = Field(..., max_length=150)
    nit: str = Field(..., max_length=50)
    telefono: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    direccion: Optional[str] = Field(None, max_length=255)
    latitud: float = Field(..., ge=-90, le=90, description="Latitud GPS del taller")
    longitud: float = Field(..., ge=-180, le=180, description="Longitud GPS del taller")


# --- Responses ---

class TallerResponse(BaseModel):
    id_taller: uuid.UUID
    nombre: str
    nit: str
    telefono: Optional[str]
    email: Optional[str]
    direccion: Optional[str]
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    is_active: bool

    model_config = {"from_attributes": True}

class StatusUpdate(BaseModel):
    nuevo_estado: str = Field(..., max_length=50, description="Ej: EN_CAMINO, EN_PROGRESO, COMPLETADO")

class IncidentAccept(BaseModel):
    id_tecnico: uuid.UUID

# --- Técnicos ---

class TecnicoCreate(BaseModel):
    nombre: str = Field(..., max_length=150)
    telefono: str = Field(..., max_length=20)
    correo: EmailStr = Field(..., alias="email") # Acepta 'email' en el JSON

    model_config = {
        "populate_by_name": True  # Permite usar 'correo' internamente en Python
    }

class TecnicoResponse(BaseModel):
    id_tecnico: uuid.UUID
    id_usuario: uuid.UUID
    nombre: str
    telefono: Optional[str]
    estado: bool
    temp_password: Optional[str] = None
    id_sucursal: Optional[uuid.UUID] = None
    branch_name: Optional[str] = None

    model_config = {"from_attributes": True}

class TecnicoUpdate(BaseModel):
    nombre: Optional[str] = Field(None, max_length=150)
    telefono: Optional[str] = Field(None, max_length=20)

# --- Sucursales ---

class SucursalCreate(BaseModel):
    nombre: str = Field(..., max_length=150)
    telefono: Optional[str] = Field(None, max_length=20)
    direccion: str = Field(..., max_length=255)
    latitud: float = Field(..., ge=-90, le=90)
    longitud: float = Field(..., ge=-180, le=180)

class SucursalResponse(BaseModel):
    id_sucursal: uuid.UUID
    id_taller: uuid.UUID
    nombre: str
    telefono: Optional[str]
    direccion: str
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    estado: bool
    fecha_creacion: datetime

    model_config = {"from_attributes": True}

class AsignarAdminSucursal(BaseModel):
    id_usuario: uuid.UUID
    id_sucursal: uuid.UUID
