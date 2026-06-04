from pydantic import BaseModel, Field
from typing import Optional, List
from decimal import Decimal
import uuid


# --- Requests ---

class IncidentCreate(BaseModel):
    id_vehiculo: uuid.UUID
    descripcion: Optional[str] = None
    telefono: Optional[str] = Field(None, max_length=20)
    latitud: Optional[float] = Field(None, ge=-90, le=90)
    longitud: Optional[float] = Field(None, ge=-180, le=180)
    prioridad: Optional[str] = Field("MEDIA", pattern="^(BAJA|MEDIA|ALTA|CRITICA)$")


# --- Responses ---

class EvidenceResponse(BaseModel):
    id_evidencia: uuid.UUID
    id_incidente: uuid.UUID
    evidencia_tipo: str
    archivo_url: str
    transcripcion: Optional[str]
    confianza_deteccion: Optional[Decimal]
    tipo_de_combustible: Optional[str]
    analisis_imagen: Optional[str]

    model_config = {"from_attributes": True}


class IncidentResponse(BaseModel):
    id_incidente: uuid.UUID
    id_vehiculo: uuid.UUID
    id_taller: Optional[uuid.UUID]
    id_tecnico: Optional[uuid.UUID] = None
    workshop_name: Optional[str] = None
    technician_name: Optional[str] = None
    technician_phone: Optional[str] = None
    descripcion: Optional[str]
    telefono: Optional[str]
    estado_incidente: str
    prioridad_incidente: str
    transcripcion_audio: Optional[str]
    resumen_ia: Optional[str]
    analisis_consolidado: Optional[str]
    fecha_reporte: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    evidencias: List[EvidenceResponse] = []
    
    # Detalle adicional del cliente y vehículo
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    vehicle_brand: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_plate: Optional[str] = None
    vehicle_color: Optional[str] = None
    vehicle_year: Optional[int] = None

    model_config = {"from_attributes": True}


class TrackingRequest(BaseModel):
    latitud: float = Field(..., ge=-90, le=90)
    longitud: float = Field(..., ge=-180, le=180)
    velocidad: Optional[float] = None


class IncidentStatusUpdate(BaseModel):
    nuevo_estado: str = Field(..., pattern="^(TALLER_ASIGNADO|EN_CAMINO|EN_ATENCION|FINALIZADO|CANCELADO|COMPLETADO)$")
