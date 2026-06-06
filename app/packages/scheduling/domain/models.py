import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, ForeignKeyConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base

class Cita(Base):
    """Citas de atención programadas para vehículos en sucursales."""
    __tablename__ = "cita"

    id_cita = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_incidente_origen = Column(UUID(as_uuid=True), ForeignKey("incidente.id_incidente"), nullable=True)
    id_cliente = Column(UUID(as_uuid=True), ForeignKey("usuarios.id_usuario"), nullable=False)
    id_vehiculo = Column(UUID(as_uuid=True), ForeignKey("vehiculo.id_vehiculo"), nullable=False)
    id_taller = Column(UUID(as_uuid=True), ForeignKey("taller.id_taller"), nullable=False)
    id_sucursal = Column(UUID(as_uuid=True), nullable=False)
    id_tecnico = Column(UUID(as_uuid=True), ForeignKey("tecnico.id_tecnico"), nullable=True)

    fecha_hora = Column(DateTime, nullable=False)  # UTC timestamp
    duracion_minutos = Column(Integer, default=60, nullable=False)
    
    estado = Column(String(50), default="PENDIENTE_CONFIRMACION", nullable=False)
    # "PENDIENTE_CONFIRMACION", "CONFIRMADA", "REPROGRAMACION_SOLICITADA", "CANCELADA", "COMPLETADA"

    tipo = Column(String(50), default="POST_AUXILIO", nullable=False)
    # "POST_AUXILIO", "DIRECTA"
    
    motivo = Column(Text, nullable=False)
    observaciones = Column(Text, nullable=True)
    prioridad = Column(String(20), default="MEDIA", nullable=False)  # "BAJA", "MEDIA", "ALTA"

    creado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id_usuario"), nullable=False)
    rol_creador = Column(String(50), nullable=False)  # "CLIENTE", "TECNICO", "ADMIN"
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)
    fecha_modificacion = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relaciones
    incidente = relationship("app.packages.emergencies.domain.models.Incidente")
    cliente = relationship("app.packages.identity.domain.models.Usuario", foreign_keys=[id_cliente])
    vehiculo = relationship("app.packages.identity.domain.models.Vehiculo")
    taller = relationship("app.packages.workshops.domain.models.Taller")
    tecnico = relationship("app.packages.workshops.domain.models.Tecnico")
    creador = relationship("app.packages.identity.domain.models.Usuario", foreign_keys=[creado_por])

    sucursal = relationship(
        "app.packages.workshops.domain.models.SucursalTaller",
        primaryjoin="and_(Cita.id_sucursal==SucursalTaller.id_sucursal, Cita.id_taller==SucursalTaller.id_taller)",
        lazy="selectin",
        viewonly=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ['id_sucursal', 'id_taller'],
            ['sucursal_taller.id_sucursal', 'sucursal_taller.id_taller'],
            name='fk_cita_sucursal'
        ),
    )
