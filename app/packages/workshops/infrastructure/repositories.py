from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from typing import Optional
import uuid

from app.packages.workshops.domain.models import Taller, AdministradorTaller


from sqlalchemy.orm import selectinload

class WorkshopRepository:
    """Operaciones de BD para la entidad Taller y sus relaciones."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_workshop(self, taller: Taller) -> Taller:
        try:
            self.session.add(taller)
            await self.session.commit()
            await self.session.refresh(taller)
            return taller
        except IntegrityError:
            await self.session.rollback()
            raise ValueError("El NIT ya está registrado por otro taller.")

    async def get_by_id(self, taller_id: uuid.UUID) -> Optional[Taller]:
        result = await self.session.execute(
            select(Taller)
            .options(
                selectinload(Taller.administradores)
                .selectinload(AdministradorTaller.usuario)
            )
            .where(Taller.id_taller == taller_id)
        )
        return result.scalars().first()

    async def get_by_nit(self, nit: str) -> Optional[Taller]:
        result = await self.session.execute(
            select(Taller).where(Taller.nit == nit)
        )
        return result.scalars().first()

    async def get_by_admin(self, user_id: uuid.UUID) -> Optional[Taller]:
        """Devuelve el taller vinculado a un administrador (relación 1:1 según el diseño)."""
        result = await self.session.execute(
            select(AdministradorTaller).where(AdministradorTaller.id_usuario == user_id)
        )
        admin_link = result.scalars().first()
        if admin_link:
            return await self.get_by_id(admin_link.id_taller)

        # Fallback para administradores de sucursal u otros roles asociados al taller
        from app.packages.workshops.domain.models import UsuarioTaller
        result_ut = await self.session.execute(
            select(UsuarioTaller).where(
                UsuarioTaller.id_usuario == user_id,
                UsuarioTaller.estado == True
            )
        )
        ut_link = result_ut.scalars().first()
        if ut_link:
            return await self.get_by_id(ut_link.id_taller)

        return None

    async def link_admin(self, admin_link: AdministradorTaller) -> AdministradorTaller:
        self.session.add(admin_link)
        await self.session.commit()
        await self.session.refresh(admin_link)
        return admin_link

    async def get_all(self) -> list[Taller]:
        """Devuelve la lista completa de talleres registrados."""
        result = await self.session.execute(select(Taller))
        return list(result.scalars().all())

    async def update_workshop(self, taller: Taller) -> Taller:
        """Actualiza un taller existente en la base de datos."""
        self.session.add(taller)
        await self.session.commit()
        await self.session.refresh(taller)
        return taller

    # --- Gestión de Técnicos ---

    async def create_technician(self, tecnico):
        self.session.add(tecnico)
        await self.session.commit()
        await self.session.refresh(tecnico)
        return tecnico

    async def get_technicians_by_workshop(self, taller_id: uuid.UUID, id_sucursal: Optional[uuid.UUID] = None):
        from app.packages.workshops.domain.models import Tecnico
        stmt = select(Tecnico).where(Tecnico.id_taller == taller_id)
        if id_sucursal is not None:
            stmt = stmt.where(Tecnico.id_sucursal == id_sucursal)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_technician_by_id(self, tecnico_id: uuid.UUID):
        from app.packages.workshops.domain.models import Tecnico
        result = await self.session.execute(
            select(Tecnico).where(Tecnico.id_tecnico == tecnico_id)
        )
        return result.scalars().first()

    # --- Gestión de Sucursales ---

    async def create_branch(self, sucursal):
        self.session.add(sucursal)
        await self.session.commit()
        await self.session.refresh(sucursal)
        return sucursal

    async def get_branches_by_workshop(self, taller_id: uuid.UUID):
        from app.packages.workshops.domain.models import SucursalTaller
        result = await self.session.execute(
            select(SucursalTaller).where(SucursalTaller.id_taller == taller_id)
        )
        return list(result.scalars().all())

    async def get_branch_by_id(self, sucursal_id: uuid.UUID, taller_id: uuid.UUID):
        from app.packages.workshops.domain.models import SucursalTaller
        result = await self.session.execute(
            select(SucursalTaller).where(
                SucursalTaller.id_sucursal == sucursal_id,
                SucursalTaller.id_taller == taller_id
            )
        )
        return result.scalars().first()

    async def update_branch(self, sucursal):
        self.session.add(sucursal)
        await self.session.commit()
        await self.session.refresh(sucursal)
        return sucursal

    async def get_user_taller_by_user(self, user_id: uuid.UUID):
        from app.packages.workshops.domain.models import UsuarioTaller
        result = await self.session.execute(
            select(UsuarioTaller).where(UsuarioTaller.id_usuario == user_id)
        )
        return result.scalars().first()

    async def link_user_taller(self, user_taller):
        self.session.add(user_taller)
        await self.session.commit()
        await self.session.refresh(user_taller)
        return user_taller