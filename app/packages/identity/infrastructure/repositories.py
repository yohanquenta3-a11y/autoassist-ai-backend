from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from typing import Optional, List
import uuid

from app.packages.identity.domain.models import Usuario, Vehiculo, Rol


class UserRepository:
    """Operaciones de BD asíncronas para Usuario, Vehiculo y Rol."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # --- Rol ---

    async def get_rol_by_nombre(self, nombre: str) -> Optional[Rol]:
        """Busca un Rol por su nombre (ej: 'cliente', 'admin_taller')."""
        result = await self.session.execute(select(Rol).where(Rol.nombre == nombre))
        return result.scalars().first()

    # --- Usuario ---

    async def get_by_email(self, email: str) -> Optional[Usuario]:
        result = await self.session.execute(select(Usuario).where(Usuario.correo == email))
        user = result.scalars().first()
        if user:
            user.rol_contexto = await self._get_rol_contexto(user)
        return user

    async def get_by_id(self, user_id: uuid.UUID) -> Optional[Usuario]:
        result = await self.session.execute(select(Usuario).where(Usuario.id_usuario == user_id))
        user = result.scalars().first()
        if user:
            user.rol_contexto = await self._get_rol_contexto(user)
        return user

    async def _get_rol_contexto(self, user: Usuario) -> Optional[str]:
        # Reset dynamic context fields
        user.id_taller = None
        user.id_sucursal = None

        from app.packages.workshops.domain.models import AdministradorTaller, UsuarioTaller, Tecnico
        
        # 1. Owner
        owner_result = await self.session.execute(
            select(AdministradorTaller).where(AdministradorTaller.id_usuario == user.id_usuario)
        )
        owner_link = owner_result.scalars().first()
        if owner_link:
            user.id_taller = owner_link.id_taller
            return "owner"
            
        # 2. Branch Admin
        branch_result = await self.session.execute(
            select(UsuarioTaller).where(UsuarioTaller.id_usuario == user.id_usuario)
        )
        branch_link = branch_result.scalars().first()
        if branch_link:
            user.id_taller = branch_link.id_taller
            user.id_sucursal = branch_link.id_sucursal
            return branch_link.rol_contexto

        # 3. Tecnico
        if user.rol_nombre == "tecnico":
            tec_result = await self.session.execute(
                select(Tecnico).where(Tecnico.id_usuario == user.id_usuario)
            )
            tec = tec_result.scalars().first()
            if tec:
                user.id_taller = tec.id_taller
                user.id_sucursal = tec.id_sucursal
            
        return None

    async def create_user(self, user: Usuario) -> Usuario:
        try:
            self.session.add(user)
            await self.session.commit()
            await self.session.refresh(user)
            return user
        except IntegrityError:
            await self.session.rollback()
            raise ValueError("El correo electrónico ya está registrado.")

    async def update_user(self, user: Usuario) -> Usuario:
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def update_fcm_token(self, user_id: uuid.UUID, token: str) -> bool:
        """Actualiza el token de notificaciones push del usuario."""
        user = await self.get_by_id(user_id)
        if not user:
            return False
        # Si el token es cadena vacía, guardamos None (Logout)
        user.fcm_token = token if token else None
        await self.session.commit()
        return True

    # --- Vehiculo ---

    async def create_vehicle(self, vehicle: Vehiculo) -> Vehiculo:
        try:
            self.session.add(vehicle)
            await self.session.commit()
            await self.session.refresh(vehicle)
            return vehicle
        except IntegrityError:
            await self.session.rollback()
            raise ValueError("La matrícula ya se encuentra registrada en otro vehículo.")

    async def get_vehicles_by_user(self, user_id: uuid.UUID) -> List[Vehiculo]:
        result = await self.session.execute(
            select(Vehiculo).where(Vehiculo.id_usuario == user_id)
        )
        return result.scalars().all()

    async def get_vehicle_by_id(self, vehicle_id: uuid.UUID) -> Optional[Vehiculo]:
        result = await self.session.execute(
            select(Vehiculo).where(Vehiculo.id_vehiculo == vehicle_id)
        )
        return result.scalars().first()

    async def update_vehicle(self, vehicle: Vehiculo) -> Vehiculo:
        self.session.add(vehicle)
        await self.session.commit()
        await self.session.refresh(vehicle)
        return vehicle

    async def delete_vehicle(self, vehicle: Vehiculo) -> None:
        await self.session.delete(vehicle)
        await self.session.commit()

    # --- Filtrado Multi-tenant ---

    async def get_all_with_filters(
        self,
        role: Optional[str] = None,
        workshop_id: Optional[uuid.UUID] = None,
        branch_id: Optional[uuid.UUID] = None
    ) -> List[Usuario]:
        """
        Obtiene usuarios filtrados por rol, taller y/o sucursal.
        Si hay workshop_id, filtra administradores, técnicos y clientes atendidos por dicho taller.
        """
        from app.packages.workshops.domain.models import AdministradorTaller, UsuarioTaller, Tecnico
        from app.packages.emergencies.domain.models import Incidente
        from sqlalchemy import or_

        query = select(Usuario).join(Rol, Usuario.id_rol == Rol.id_rol)

        if role:
            query = query.where(Rol.nombre == role)

        if workshop_id:
            from sqlalchemy import exists

            is_admin = exists().where(AdministradorTaller.id_usuario == Usuario.id_usuario).where(AdministradorTaller.id_taller == workshop_id)
            
            if branch_id is not None:
                is_member = exists().where(UsuarioTaller.id_usuario == Usuario.id_usuario).where(UsuarioTaller.id_taller == workshop_id).where(UsuarioTaller.id_sucursal == branch_id)
                is_tecnico = exists().where(Tecnico.id_usuario == Usuario.id_usuario).where(Tecnico.id_taller == workshop_id).where(Tecnico.id_sucursal == branch_id)
            else:
                is_member = exists().where(UsuarioTaller.id_usuario == Usuario.id_usuario).where(UsuarioTaller.id_taller == workshop_id)
                is_tecnico = exists().where(Tecnico.id_usuario == Usuario.id_usuario).where(Tecnico.id_taller == workshop_id)
                
            is_cliente = exists().where(Vehiculo.id_usuario == Usuario.id_usuario).where(Incidente.id_vehiculo == Vehiculo.id_vehiculo).where(Incidente.id_taller == workshop_id)
            query = query.where(or_(is_admin, is_member, is_tecnico, is_cliente))

        result = await self.session.execute(query)
        users = list(result.scalars().all())
        
        # Cargar dinámicamente el rol de contexto para cada usuario en el listado
        for user in users:
            user.rol_contexto = await self._get_rol_contexto(user)
            
        return users