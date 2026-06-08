import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from app.core.exceptions import ConflictError, BadRequestError
from app.packages.workshops.domain.models import Taller, SucursalTaller, UsuarioTaller, Tecnico
from app.packages.emergencies.domain.models import Incidente
from app.packages.identity.domain.models import Usuario, Bitacora


class TenantRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all_workshops(self) -> list[Taller]:
        result = await self.session.execute(select(Taller))
        return list(result.scalars().all())

    async def get_workshop(self, taller_id: uuid.UUID) -> Optional[Taller]:
        result = await self.session.execute(select(Taller).where(Taller.id_taller == taller_id))
        return result.scalars().first()

    async def create_workshop(self, taller: Taller) -> Taller:
        try:
            self.session.add(taller)
            await self.session.commit()
            await self.session.refresh(taller)
            return taller
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError("El NIT ya está registrado por otro taller.")

    async def update_workshop(self, taller: Taller) -> Taller:
        try:
            self.session.add(taller)
            await self.session.commit()
            await self.session.refresh(taller)
            return taller
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError("El NIT ya está registrado por otro taller.")

    async def get_user(self, user_id: uuid.UUID) -> Optional[Usuario]:
        result = await self.session.execute(select(Usuario).where(Usuario.id_usuario == user_id))
        return result.scalars().first()

    async def get_technician(self, tecnico_id: uuid.UUID) -> Optional[Tecnico]:
        result = await self.session.execute(select(Tecnico).where(Tecnico.id_tecnico == tecnico_id))
        return result.scalars().first()

    async def get_branch(self, id_sucursal: uuid.UUID, id_taller: uuid.UUID) -> Optional[SucursalTaller]:
        result = await self.session.execute(
            select(SucursalTaller).where(
                SucursalTaller.id_sucursal == id_sucursal,
                SucursalTaller.id_taller == id_taller
            )
        )
        return result.scalars().first()

    async def get_user_workshop_links(self, user_id: uuid.UUID) -> list[UsuarioTaller]:
        result = await self.session.execute(select(UsuarioTaller).where(UsuarioTaller.id_usuario == user_id))
        return list(result.scalars().all())

    async def add_user_to_workshop(self, user_taller: UsuarioTaller) -> UsuarioTaller:
        try:
            self.session.add(user_taller)
            await self.session.commit()
            await self.session.refresh(user_taller)
            return user_taller
        except IntegrityError:
            await self.session.rollback()
            raise BadRequestError("No se pudo asociar el usuario al taller. Revise el rol o la sucursal.")

    async def update_technician(self, tecnico: Tecnico) -> Tecnico:
        self.session.add(tecnico)
        await self.session.commit()
        await self.session.refresh(tecnico)
        return tecnico

    async def get_incidents_by_workshop(
        self,
        taller_id: uuid.UUID,
        id_sucursal: Optional[uuid.UUID] = None,
        offset: int = 0,
        limit: int = 50
    ) -> list[Incidente]:
        query = select(Incidente).where(Incidente.id_taller == taller_id)
        if id_sucursal is not None:
            query = query.where(Incidente.id_sucursal == id_sucursal)
        query = query.order_by(Incidente.fecha_reporte.desc()).offset(offset).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_bitacora_by_workshop(
        self,
        taller_id: uuid.UUID,
        offset: int = 0,
        limit: int = 50
    ) -> list[Bitacora]:
        query = select(Bitacora).where(Bitacora.id_taller == taller_id).order_by(Bitacora.fecha_hora.desc()).offset(offset).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_operational_metrics(self, taller_id: uuid.UUID) -> dict:
        total_incidents = await self.session.scalar(
            select(func.count(Incidente.id_incidente)).where(Incidente.id_taller == taller_id)
        )
        open_incidents = await self.session.scalar(
            select(func.count(Incidente.id_incidente)).where(
                Incidente.id_taller == taller_id,
                Incidente.estado_incidente != "FINALIZADO"
            )
        )
        total_technicians = await self.session.scalar(
            select(func.count(Tecnico.id_tecnico)).where(
                Tecnico.id_taller == taller_id,
                Tecnico.estado == True
            )
        )
        active_branches = await self.session.scalar(
            select(func.count(SucursalTaller.id_sucursal)).where(
                SucursalTaller.id_taller == taller_id,
                SucursalTaller.is_active == True
            )
        )
        return {
            "total_incidentes": total_incidents or 0,
            "incidentes_abiertos": open_incidents or 0,
            "total_tecnicos": total_technicians or 0,
            "sucursales_activas": active_branches or 0,
        }

    async def create_bitacora_entry(
        self,
        bitacora: Bitacora
    ) -> Bitacora:
        self.session.add(bitacora)
        await self.session.commit()
        await self.session.refresh(bitacora)
        return bitacora
