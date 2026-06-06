import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class CitaCreate(BaseModel):
    tipo: str = "POST_AUXILIO"
    id_incidente_origen: Optional[uuid.UUID] = None
    id_cliente: Optional[uuid.UUID] = None
    id_vehiculo: uuid.UUID
    id_sucursal: Optional[uuid.UUID] = None
    id_tecnico: Optional[uuid.UUID] = None
    fecha_hora: datetime
    motivo: str = Field(..., min_length=1)
    observaciones: Optional[str] = None
    prioridad: str = "MEDIA"

class CitaRescheduleRequest(BaseModel):
    fecha_hora: datetime
    observaciones: Optional[str] = None

class CitaResponse(BaseModel):
    id_cita: uuid.UUID
    id_incidente_origen: Optional[uuid.UUID]
    id_cliente: uuid.UUID
    id_vehiculo: uuid.UUID
    id_taller: uuid.UUID
    id_sucursal: uuid.UUID
    id_tecnico: Optional[uuid.UUID]
    fecha_hora: datetime
    duracion_minutos: int
    estado: str
    tipo: str
    motivo: str
    observaciones: Optional[str]
    prioridad: str
    creado_por: uuid.UUID
    rol_creador: str
    fecha_creacion: datetime
    fecha_modificacion: datetime
    
    # Campos adicionales enriquecidos
    cliente_nombre: Optional[str] = None
    cliente_telefono: Optional[str] = None
    vehiculo_matricula: Optional[str] = None
    vehiculo_marca: Optional[str] = None
    vehiculo_modelo: Optional[str] = None
    tecnico_nombre: Optional[str] = None
    sucursal_nombre: Optional[str] = None

    class Config:
        from_attributes = True

class SlotAvailabilityResponse(BaseModel):
    fecha_hora: datetime
    disponible: bool
    motivo: Optional[str] = None
