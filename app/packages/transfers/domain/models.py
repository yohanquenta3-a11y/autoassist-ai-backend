import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, ForeignKeyConstraint, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class SolicitudTraslado(Base):
    """Solicitud de flete o traslado preventivo de un vehiculo."""

    __tablename__ = "solicitud_traslado"

    id_traslado = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tipo_traslado = Column(String(50), nullable=False)
    estado = Column(String(50), nullable=False)

    id_cliente = Column(UUID(as_uuid=True), ForeignKey("usuarios.id_usuario"), nullable=False)
    id_vehiculo = Column(UUID(as_uuid=True), ForeignKey("vehiculo.id_vehiculo"), nullable=False)
    id_taller = Column(UUID(as_uuid=True), ForeignKey("taller.id_taller"), nullable=True)
    id_sucursal = Column(UUID(as_uuid=True), nullable=True)
    id_tecnico = Column(UUID(as_uuid=True), ForeignKey("tecnico.id_tecnico"), nullable=True)

    origen_direccion = Column(Text, nullable=False)
    origen_latitud = Column(Numeric(10, 7), nullable=True)
    origen_longitud = Column(Numeric(10, 7), nullable=True)
    destino_direccion = Column(Text, nullable=False)
    destino_latitud = Column(Numeric(10, 7), nullable=True)
    destino_longitud = Column(Numeric(10, 7), nullable=True)

    fecha_programada = Column(DateTime, nullable=True)
    motivo = Column(Text, nullable=False)
    observaciones = Column(Text, nullable=True)
    telefono_contacto = Column(String(20), nullable=True)

    creado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id_usuario"), nullable=False)
    rol_creador = Column(String(50), nullable=False)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)
    fecha_modificacion = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    cliente = relationship("app.packages.identity.domain.models.Usuario", foreign_keys=[id_cliente])
    vehiculo = relationship("app.packages.identity.domain.models.Vehiculo")
    taller = relationship("app.packages.workshops.domain.models.Taller")
    tecnico = relationship("app.packages.workshops.domain.models.Tecnico")
    creador = relationship("app.packages.identity.domain.models.Usuario", foreign_keys=[creado_por])
    historial = relationship(
        "HistorialTraslado",
        back_populates="traslado",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    sucursal = relationship(
        "app.packages.workshops.domain.models.SucursalTaller",
        primaryjoin=(
            "and_(SolicitudTraslado.id_sucursal==SucursalTaller.id_sucursal, "
            "SolicitudTraslado.id_taller==SucursalTaller.id_taller)"
        ),
        lazy="selectin",
        viewonly=True,
    )

    @property
    def branch_name(self) -> Optional[str]:
        return self.sucursal.nombre if (self.id_sucursal and self.sucursal) else None

    __table_args__ = (
        ForeignKeyConstraint(
            ["id_sucursal", "id_taller"],
            ["sucursal_taller.id_sucursal", "sucursal_taller.id_taller"],
            name="fk_solicitud_traslado_sucursal",
        ),
    )


class HistorialTraslado(Base):
    """Trazabilidad de cambios de estado de una solicitud de traslado."""

    __tablename__ = "historial_traslado"

    id_historial = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_traslado = Column(UUID(as_uuid=True), ForeignKey("solicitud_traslado.id_traslado"), nullable=False)
    estado_anterior = Column(String(50), nullable=True)
    estado_nuevo = Column(String(50), nullable=False)
    historial_actor = Column(String(150), nullable=True)
    id_usuario_actor = Column(UUID(as_uuid=True), ForeignKey("usuarios.id_usuario"), nullable=True)
    comentario = Column(Text, nullable=True)
    fecha = Column(DateTime, default=datetime.utcnow, nullable=False)

    traslado = relationship("SolicitudTraslado", back_populates="historial")
    usuario_actor = relationship("app.packages.identity.domain.models.Usuario")
