import uuid
from sqlalchemy import Column, String, ForeignKey, Numeric, DateTime
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime

from app.core.database import Base


class Pago(Base):
    """Registro de pagos entre clientes y talleres por servicio de emergencia."""
    __tablename__ = "pago"

    id_pago = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_incidente = Column(UUID(as_uuid=True), ForeignKey("incidente.id_incidente"), nullable=False)
    id_taller = Column(UUID(as_uuid=True), ForeignKey("taller.id_taller"), nullable=False)
    monto = Column(Numeric(10, 2), nullable=False)
    monto_comision = Column(Numeric(10, 2), nullable=True)  # Comisión de la plataforma
    estado_pago = Column(String(50), default="PENDIENTE", nullable=False)
    fecha_pago = Column(DateTime, nullable=True)
    mano_de_obra = Column(Numeric(10, 2), nullable=True)
    repuestos = Column(Numeric(10, 2), nullable=True)
    observaciones = Column(String, nullable=True)

