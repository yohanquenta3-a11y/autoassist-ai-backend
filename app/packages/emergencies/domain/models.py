import uuid
from typing import Optional
from sqlalchemy import Column, String, Text, DateTime, Numeric, ForeignKey, ForeignKeyConstraint, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geography
from datetime import datetime

from app.core.database import Base

# Importar modelos relacionados para que SQLAlchemy resuelva las relaciones por nombre
import app.packages.finance.domain.models  # noqa: F401
import app.packages.assignment.domain.models  # noqa: F401


class Incidente(Base):
    """Ticket de emergencia reportado por un cliente en campo."""
    __tablename__ = "incidente"

    id_incidente = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_vehiculo = Column(UUID(as_uuid=True), ForeignKey("vehiculo.id_vehiculo"), nullable=False)
    id_taller = Column(UUID(as_uuid=True), ForeignKey("taller.id_taller"), nullable=True)
    id_sucursal = Column(UUID(as_uuid=True), nullable=True)
    id_usuario_cliente = Column(UUID(as_uuid=True), ForeignKey("usuarios.id_usuario"), nullable=False)

    # Coordenadas GPS de la emergencia — PostGIS POINT
    ubicacion_emergencia = Column(Geography('POINT', srid=4326), nullable=True)

    telefono = Column(String(20), nullable=True)
    descripcion = Column(Text, nullable=True)
    estado_incidente = Column(String(50), default="PENDIENTE", nullable=False)
    prioridad_incidente = Column(String(20), default="MEDIA", nullable=False)
    origen = Column(String(50), nullable=True)
    identificador_local = Column(String(120), nullable=True)
    origen_registro = Column(String(50), default="ONLINE", nullable=False)
    fecha_sincronizacion = Column(DateTime, nullable=True)
    id_cotizacion_origen = Column(UUID(as_uuid=True), ForeignKey("cotizacion.id_cotizacion"), nullable=True)

    # Campos enriquecidos por la IA (Fase de procesamiento inteligente)
    transcripcion_audio = Column(Text, nullable=True)
    resumen_ia = Column(Text, nullable=True)
    analisis_consolidado = Column(Text, nullable=True)

    id_tecnico = Column(UUID(as_uuid=True), ForeignKey("tecnico.id_tecnico"), nullable=True)

    fecha_reporte = Column(DateTime, default=datetime.utcnow, nullable=False)

    vehiculo = relationship("Vehiculo")
    taller = relationship("Taller")
    cliente = relationship("app.packages.identity.domain.models.Usuario")
    tecnico = relationship("Tecnico", foreign_keys=[id_tecnico])
    evidencias = relationship("EvidenciaIncidente", back_populates="incidente", cascade="all, delete-orphan")
    historial = relationship("HistorialIncidente", back_populates="incidente", cascade="all, delete-orphan")
    verificaciones = relationship("VerificacionTecnico", back_populates="incidente", cascade="all, delete-orphan", lazy="selectin")
    pago = relationship(
        "app.packages.finance.domain.models.Pago",
        uselist=False,
        primaryjoin="Incidente.id_incidente==Pago.id_incidente",
        lazy="selectin",
        viewonly=True
    )


    @property
    def latest_verification(self) -> Optional["VerificacionTecnico"]:
        if not self.verificaciones:
            return None
        return sorted(self.verificaciones, key=lambda v: v.fecha_creacion)[-1]
    sucursal = relationship(
        "SucursalTaller",
        primaryjoin="and_(Incidente.id_sucursal==SucursalTaller.id_sucursal, Incidente.id_taller==SucursalTaller.id_taller)",
        lazy="selectin",
        viewonly=True
    )

    @property
    def branch_name(self) -> Optional[str]:
        return self.sucursal.nombre if (self.id_sucursal and self.sucursal) else "Sin sucursal asignada"

    # Restricción de integridad compuesta para asegurar que la sucursal asignada pertenece al mismo taller (tenant)
    __table_args__ = (
        ForeignKeyConstraint(
            ['id_sucursal', 'id_taller'],
            ['sucursal_taller.id_sucursal', 'sucursal_taller.id_taller'],
            name='fk_incidente_sucursal'
        ),
    )


class EvidenciaIncidente(Base):
    """Archivos multimedia (fotos, audios) y análisis por IA de un incidente."""
    __tablename__ = "evidencia_incidente"

    id_evidencia = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_incidente = Column(UUID(as_uuid=True), ForeignKey("incidente.id_incidente"), nullable=False)
    evidencia_tipo = Column(String(50), nullable=False)       # "foto", "audio", "video"
    archivo_url = Column(String(500), nullable=False)          # URL en S3
    transcripcion = Column(Text, nullable=True)                # Para audios (Whisper)
    confianza_deteccion = Column(Numeric(5, 4), nullable=True) # Score del modelo de visión
    tipo_de_combustible = Column(String(50), nullable=True)    # Inferido por IA
    analisis_imagen = Column(Text, nullable=True)              # Descripción devuelta por la IA
    fecha_subida = Column(DateTime, default=datetime.utcnow, nullable=False)

    incidente = relationship("Incidente", back_populates="evidencias")


class HistorialIncidente(Base):
    """Registro auditorio de todos los cambios de estado de un incidente."""
    __tablename__ = "historial_incidente"

    id_historial = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_incidente = Column(UUID(as_uuid=True), ForeignKey("incidente.id_incidente"), nullable=False)
    id_taller = Column(UUID(as_uuid=True), ForeignKey("taller.id_taller"), nullable=True)
    id_sucursal = Column(UUID(as_uuid=True), nullable=True)
    incidente_estado_anterior = Column(String(50), nullable=True)
    incidente_estado_nuevo = Column(String(50), nullable=False)
    historial_actor = Column(String(150), nullable=True)  # Nombre o ID del actor que realizó el cambio
    id_usuario_actor = Column(UUID(as_uuid=True), ForeignKey("usuarios.id_usuario"), nullable=True)
    fecha = Column(DateTime, default=datetime.utcnow, nullable=False)

    incidente = relationship("Incidente", back_populates="historial")
    usuario_actor = relationship("app.packages.identity.domain.models.Usuario")

    __table_args__ = (
        ForeignKeyConstraint(
            ['id_sucursal', 'id_taller'],
            ['sucursal_taller.id_sucursal', 'sucursal_taller.id_taller'],
            name='fk_historial_incidente_sucursal'
        ),
    )


class VerificacionTecnico(Base):
    """Registro de la verificación segura de identidad del técnico en sitio (CU30)."""
    __tablename__ = "verificacion_tecnico"

    id_verificacion = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_incidente = Column(UUID(as_uuid=True), ForeignKey("incidente.id_incidente"), nullable=False)
    id_asignacion = Column(UUID(as_uuid=True), ForeignKey("asignacion_incidente.id_asignacion"), nullable=True)
    id_tecnico = Column(UUID(as_uuid=True), ForeignKey("tecnico.id_tecnico"), nullable=False)
    metodo_verificacion = Column(String(50), default="PIN", nullable=False)       # "PIN", "QR", "MANUAL_OVERRIDE"
    codigo_verificacion = Column(String(10), nullable=False)                      # Código PIN de 6 dígitos
    estado_verificacion = Column(String(50), default="PENDIENTE", nullable=False)  # "PENDIENTE", "VERIFICADO", "RECHAZADO_ERROR", "BLOQUEADO"
    fecha_verificacion = Column(DateTime, nullable=True)
    resultado = Column(String(50), default="PENDIENTE", nullable=False)           # "PENDIENTE", "EXITOSO", "FALLIDO", "MISMATCH"
    intentos = Column(Integer, default=0, nullable=False)
    usuario_validador = Column(String(150), nullable=True)                        # Quién validó (cliente o admin)
    motivo_override = Column(Text, nullable=True)                                 # Motivo del override manual si corresponde
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relaciones
    incidente = relationship("Incidente", back_populates="verificaciones")
    tecnico = relationship("app.packages.workshops.domain.models.Tecnico")
    asignacion = relationship("app.packages.assignment.domain.models.AsignacionIncidente")
