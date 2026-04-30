import uuid
from sqlalchemy import Column, String, ForeignKey, Numeric, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime

from app.core.database import Base


class AsignacionIncidente(Base):
    """Asignación de un técnico a un incidente por el motor de asignación inteligente."""
    __tablename__ = "asignacion_incidente"

    id_asignacion = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_incidente = Column(UUID(as_uuid=True), ForeignKey("incidente.id_incidente"), nullable=False)
    id_taller = Column(UUID(as_uuid=True), ForeignKey("taller.id_taller"), nullable=True)
    id_tecnico = Column(UUID(as_uuid=True), ForeignKey("tecnico.id_tecnico"), nullable=True)
    estado_asignacion = Column(String(50), default="ASIGNADO", nullable=False)
    score_asignacion = Column(Numeric(5, 2), nullable=True)  # Puntuación del algoritmo
    distancia_km = Column(Numeric(8, 2), nullable=True)       # Distancia calculada en km
    fecha_asignacion = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relaciones
    incidente = relationship("app.packages.emergencies.domain.models.Incidente")
    taller = relationship("app.packages.workshops.domain.models.Taller")
