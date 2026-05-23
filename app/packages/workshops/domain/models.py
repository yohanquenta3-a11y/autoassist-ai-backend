import uuid
from sqlalchemy import Column, String, Boolean, ForeignKey, Time
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geography

from app.core.database import Base


class CategoriaServicio(Base):
    """Tipos de servicio que un taller puede ofrecer."""
    __tablename__ = "categoria_servicio"

    id_categoria = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(150), nullable=False)

    talleres = relationship("TallerCategoriaServicio", back_populates="categoria")


class Taller(Base):
    """Talleres mecánicos afiliados a la plataforma."""
    __tablename__ = "taller"

    id_taller = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(150), nullable=False)
    nit = Column(String(50), unique=True, index=True, nullable=False)
    telefono = Column(String(20), nullable=True)
    email = Column(String(150), nullable=True)
    direccion = Column(String(255), nullable=True)

    # Campo geográfico PostGIS para búsquedas de cercanía (CU de asignación inteligente)
    ubicacion = Column(Geography('POINT', srid=4326), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    administradores = relationship("AdministradorTaller", back_populates="taller", cascade="all, delete-orphan")
    tecnicos = relationship("Tecnico", back_populates="taller")
    categorias = relationship("TallerCategoriaServicio", back_populates="taller", cascade="all, delete-orphan")


class TallerCategoriaServicio(Base):
    """Tabla pivote: relación N-N entre Taller y CategoriaServicio."""
    __tablename__ = "tallercategoria_servicio"

    id_taller_cat = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_taller = Column(UUID(as_uuid=True), ForeignKey("taller.id_taller"), nullable=False)
    id_categoria = Column(UUID(as_uuid=True), ForeignKey("categoria_servicio.id_categoria"), nullable=False)

    taller = relationship("Taller", back_populates="categorias")
    categoria = relationship("CategoriaServicio", back_populates="talleres")


class AdministradorTaller(Base):
    """Vincula un usuario con rol admin_taller a su taller correspondiente."""
    __tablename__ = "administradortaller"

    id_admin_taller = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_usuario = Column(UUID(as_uuid=True), ForeignKey("usuarios.id_usuario"), nullable=False)
    id_taller = Column(UUID(as_uuid=True), ForeignKey("taller.id_taller"), nullable=False)

    taller = relationship("Taller", back_populates="administradores")
    usuario = relationship("app.packages.identity.domain.models.Usuario")


class Tecnico(Base):
    """Técnicos que trabajan en un taller específico."""
    __tablename__ = "tecnico"

    id_tecnico = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_usuario = Column(UUID(as_uuid=True), ForeignKey("usuarios.id_usuario"), nullable=False)
    id_taller = Column(UUID(as_uuid=True), ForeignKey("taller.id_taller"), nullable=False)
    nombre = Column(String(150), nullable=False)
    telefono = Column(String(20), nullable=True)
    estado = Column(Boolean, default=True, nullable=False)

    taller = relationship("Taller", back_populates="tecnicos")
    disponibilidades = relationship("DisponibilidadTecnico", back_populates="tecnico", cascade="all, delete-orphan")


class DisponibilidadTecnico(Base):
    """Horarios de disponibilidad semanal de cada técnico."""
    __tablename__ = "disponibilidad_tecnico"

    id_disponibilidad = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_tecnico = Column(UUID(as_uuid=True), ForeignKey("tecnico.id_tecnico"), nullable=False)
    dia = Column(String(20), nullable=False)
    hora_fin = Column(Time, nullable=False)
    hora_ini = Column(Time, nullable=False)
    disponibilidad = Column(Boolean, default=True, nullable=False)

    tecnico = relationship("Tecnico", back_populates="disponibilidades")


# Constantes de Categorías
CATEGORIA_MECANICA_GENERAL = "Mecánica General"