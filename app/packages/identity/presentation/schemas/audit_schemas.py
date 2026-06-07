from datetime import datetime
from typing import Optional
import uuid

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    id_bitacora: uuid.UUID
    id_usuario: Optional[uuid.UUID] = None
    nombre_usuario: Optional[str] = None
    rol_usuario: Optional[str] = None
    ip: str
    accion: str
    descripcion: Optional[str] = None
    tipo_entidad: Optional[str] = None
    id_entidad: Optional[uuid.UUID] = None
    id_taller: Optional[uuid.UUID] = None
    taller_nombre: Optional[str] = None
    id_sucursal: Optional[uuid.UUID] = None
    sucursal_nombre: Optional[str] = None
    fecha_hora: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedAuditLogResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
