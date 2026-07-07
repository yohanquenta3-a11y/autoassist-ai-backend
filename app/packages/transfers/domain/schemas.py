import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class TransferBaseCreate(BaseModel):
    id_vehiculo: uuid.UUID
    id_taller: Optional[uuid.UUID] = None
    id_sucursal: Optional[uuid.UUID] = None
    origen_direccion: str = Field(..., min_length=1)
    origen_latitud: Optional[Decimal] = None
    origen_longitud: Optional[Decimal] = None
    destino_direccion: str = Field(..., min_length=1)
    destino_latitud: Optional[Decimal] = None
    destino_longitud: Optional[Decimal] = None
    motivo: str = Field(..., min_length=1)
    observaciones: Optional[str] = None
    telefono_contacto: Optional[str] = None

    @field_validator("origen_direccion", "destino_direccion", "motivo")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Campo obligatorio")
        return value


class ImmediateTransferCreate(TransferBaseCreate):
    pass


class ScheduledTransferCreate(TransferBaseCreate):
    id_taller: uuid.UUID
    id_sucursal: uuid.UUID
    fecha_programada: datetime


class TransferBranchOption(BaseModel):
    id_sucursal: uuid.UUID
    nombre: str
    direccion: Optional[str] = None


class TransferWorkshopOption(BaseModel):
    id_taller: uuid.UUID
    nombre: str
    direccion: Optional[str] = None
    sucursales: list[TransferBranchOption] = []


class TransferAssignRequest(BaseModel):
    id_tecnico: uuid.UUID


class TransferStatusUpdate(BaseModel):
    estado: str = Field(..., min_length=1)
    comentario: Optional[str] = None


class TransferRescheduleRequest(BaseModel):
    fecha_programada: datetime
    comentario: Optional[str] = None


class TransferRejectRequest(BaseModel):
    comentario: Optional[str] = None


class TransferHistoryResponse(BaseModel):
    id_historial: uuid.UUID
    id_traslado: uuid.UUID
    estado_anterior: Optional[str]
    estado_nuevo: str
    historial_actor: Optional[str]
    id_usuario_actor: Optional[uuid.UUID]
    comentario: Optional[str]
    fecha: datetime

    class Config:
        from_attributes = True


class TransferResponse(BaseModel):
    id_traslado: uuid.UUID
    tipo_traslado: str
    estado: str
    id_cliente: uuid.UUID
    id_vehiculo: uuid.UUID
    id_taller: Optional[uuid.UUID]
    id_sucursal: Optional[uuid.UUID]
    id_tecnico: Optional[uuid.UUID]
    origen_direccion: str
    origen_latitud: Optional[Decimal]
    origen_longitud: Optional[Decimal]
    destino_direccion: str
    destino_latitud: Optional[Decimal]
    destino_longitud: Optional[Decimal]
    fecha_programada: Optional[datetime]
    motivo: str
    observaciones: Optional[str]
    telefono_contacto: Optional[str]
    creado_por: uuid.UUID
    rol_creador: str
    fecha_creacion: datetime
    fecha_modificacion: datetime
    cliente_nombre: Optional[str] = None
    cliente_telefono: Optional[str] = None
    vehiculo_matricula: Optional[str] = None
    vehiculo_marca: Optional[str] = None
    vehiculo_modelo: Optional[str] = None
    vehiculo_color: Optional[str] = None
    vehiculo_ano: Optional[int] = None
    taller_nombre: Optional[str] = None
    sucursal_nombre: Optional[str] = None
    tecnico_nombre: Optional[str] = None
    tecnico_telefono: Optional[str] = None
    historial: list[TransferHistoryResponse] = []

    class Config:
        from_attributes = True
