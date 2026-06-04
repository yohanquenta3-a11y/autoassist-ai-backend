import uuid
from sqlalchemy import Column, String, Boolean, ForeignKey, Text, DateTime, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime

from app.core.database import Base

# --- Constantes de nombre de Rol para comparaciones en la lógica de negocio ---
ROL_CLIENTE = "cliente"
ROL_ADMIN_TALLER = "admin_taller"
ROL_SUPERADMIN = "superadmin"
ROL_TECNICO = "tecnico"


class Rol(Base):
    """Tabla de Roles del sistema (admins, clientes, técnicos, etc.)"""
    __tablename__ = "roles"

    id_rol = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(100), nullable=False, unique=True)
    descripcion = Column(Text, nullable=True)
    estado = Column(Boolean, default=True, nullable=False)

    usuarios = relationship("Usuario", back_populates="rol_obj", lazy="selectin")


class Usuario(Base):
    """Tabla central de usuarios del sistema."""
    __tablename__ = "usuarios"

    id_usuario = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_rol = Column(UUID(as_uuid=True), ForeignKey("roles.id_rol"), nullable=False)
    nombre = Column(String(150), nullable=False)
    telefono = Column(String(20), nullable=True)
    correo = Column(String(150), unique=True, index=True, nullable=False)
    contrasena = Column(String(255), nullable=False)
    estado = Column(Boolean, default=True, nullable=False)
    fcm_token = Column(String(255), nullable=True)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)

    rol_obj = relationship("Rol", back_populates="usuarios", lazy="selectin")
    vehiculos = relationship("Vehiculo", back_populates="propietario", cascade="all, delete-orphan", lazy="selectin")
    bitacoras = relationship("Bitacora", back_populates="usuario", foreign_keys="[Bitacora.id_usuario_actor]")
    notificaciones = relationship("Notificacion", back_populates="usuario")

    # Dynamic fields for tenant and role context (not database columns)
    id_taller = None
    id_sucursal = None
    rol_contexto = None

    @property
    def rol_nombre(self) -> str:
        """Devuelve el nombre del rol para comparaciones en la lógica de negocio."""
        return self.rol_obj.nombre if self.rol_obj else ""

    @property
    def placas(self) -> list[str]:
        """Devuelve las patentes de los vehículos asociados."""
        return [v.matricula for v in self.vehiculos] if self.vehiculos else []


class Vehiculo(Base):
    """Vehículos del cliente (placa única por cada propietario)."""
    __tablename__ = "vehiculo"

    id_vehiculo = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_usuario = Column(UUID(as_uuid=True), ForeignKey("usuarios.id_usuario"), nullable=False)
    matricula = Column(String(20), unique=True, index=True, nullable=False)
    modelo = Column(String(100), nullable=False)
    ano = Column(Integer, nullable=False)
    color = Column(String(50), nullable=True)
    marca = Column(String(100), nullable=False)
    foto = Column(String(500), nullable=True)

    propietario = relationship("Usuario", back_populates="vehiculos")


class Bitacora(Base):
    """Registro de auditoría de acciones en el sistema."""
    __tablename__ = "bitacora"

    id_bitacora = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_usuario_actor = Column(UUID(as_uuid=True), ForeignKey("usuarios.id_usuario"), nullable=False)
    rol_usuario = Column(String(50), nullable=True)
    id_taller = Column(UUID(as_uuid=True), ForeignKey("taller.id_taller"), nullable=True)
    id_sucursal_contexto = Column(UUID(as_uuid=True), nullable=True)
    id_sucursal_afectada = Column(UUID(as_uuid=True), nullable=True)
    tipo_entidad = Column(String(100), nullable=True)
    id_entidad = Column(UUID(as_uuid=True), nullable=True)
    ip = Column(String(45), nullable=False)
    accion = Column(String(255), nullable=False)
    descripcion = Column(Text, nullable=True)
    datos_antes = Column(JSONB, nullable=True)
    datos_despues = Column(JSONB, nullable=True)
    fecha_hora = Column(DateTime, default=datetime.utcnow)

    usuario = relationship("Usuario", back_populates="bitacoras", foreign_keys=[id_usuario_actor])


class Notificacion(Base):
    """Notificaciones push y en-app para los usuarios."""
    __tablename__ = "notificacion"

    id_notificacion = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_usuario = Column(UUID(as_uuid=True), ForeignKey("usuarios.id_usuario"), nullable=False)
    tipo_notificacion = Column(String(100), nullable=False)
    mensaje = Column(Text, nullable=False)
    leida = Column(Boolean, default=False, nullable=False)
    fecha_envio = Column(DateTime, default=datetime.utcnow)

    usuario = relationship("Usuario", back_populates="notificaciones")