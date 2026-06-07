import uuid
from typing import Optional
from pydantic import BaseModel, Field


class TallerCreate(BaseModel):
    nombre: str = Field(..., description="Nombre del taller")
    nit: str = Field(..., description="NIT único del taller")
    telefono: Optional[str] = Field(None, description="Teléfono de contacto del taller")
    email: Optional[str] = Field(None, description="Correo del taller")
    direccion: Optional[str] = Field(None, description="Dirección física del taller")
    is_active: Optional[bool] = Field(True, description="Estado activo del taller")


class TallerUpdate(BaseModel):
    nombre: Optional[str] = Field(None, description="Nombre del taller")
    nit: Optional[str] = Field(None, description="NIT del taller")
    telefono: Optional[str] = Field(None, description="Teléfono de contacto")
    email: Optional[str] = Field(None, description="Correo del taller")
    direccion: Optional[str] = Field(None, description="Dirección física")
    is_active: Optional[bool] = Field(None, description="Estado activo del taller")


class TallerResponse(BaseModel):
    id_taller: uuid.UUID
    nombre: str
    nit: str
    telefono: Optional[str]
    email: Optional[str]
    direccion: Optional[str]
    is_active: bool

    class Config:
        orm_mode = True


class UserAssignmentRequest(BaseModel):
    rol_contexto: Optional[str] = Field("miembro", description="Rol del usuario dentro del taller")
    id_sucursal: Optional[uuid.UUID] = Field(None, description="Sucursal asignada al usuario dentro del taller")


class TechnicianAssignmentRequest(BaseModel):
    id_sucursal: Optional[uuid.UUID] = Field(None, description="Sucursal asignada al técnico dentro del taller")


class IncidentResponse(BaseModel):
    id_incidente: uuid.UUID
    id_taller: Optional[uuid.UUID]
    id_sucursal: Optional[uuid.UUID]
    id_usuario_cliente: uuid.UUID
    id_tecnico: Optional[uuid.UUID]
    estado_incidente: str
    prioridad_incidente: str
    fecha_reporte: Optional[str]
    descripcion: Optional[str]

    class Config:
        orm_mode = True


class MetricasResponse(BaseModel):
    total_incidentes: int
    incidentes_abiertos: int
    total_tecnicos: int
    sucursales_activas: int


class BitacoraResponse(BaseModel):
    id_bitacora: uuid.UUID
    id_usuario_actor: uuid.UUID
    rol_usuario: Optional[str]
    id_taller: Optional[uuid.UUID]
    id_sucursal_contexto: Optional[uuid.UUID]
    accion: str
    descripcion: Optional[str]
    fecha_hora: Optional[str]

    class Config:
        orm_mode = True


class IsolationResponse(BaseModel):
    rol: str
    id_taller: Optional[uuid.UUID]
    id_sucursal: Optional[uuid.UUID]
    puede_acceder: bool
    mensaje: str
