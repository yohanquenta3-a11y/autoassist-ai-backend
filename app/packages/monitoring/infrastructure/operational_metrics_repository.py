from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.packages.emergencies.domain.models import HistorialIncidente, Incidente
from app.packages.identity.domain.models import Vehiculo
from app.packages.workshops.domain.models import SucursalTaller, Taller, Tecnico


class OperationalMetricsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_incidents(
        self,
        *,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        id_taller: Optional[uuid.UUID] = None,
        id_sucursal: Optional[uuid.UUID] = None,
        estado: Optional[str] = None,
        prioridad: Optional[str] = None,
        origen: Optional[str] = None,
    ) -> list[Incidente]:
        stmt = (
            select(Incidente)
            .options(
                joinedload(Incidente.vehiculo).joinedload(Vehiculo.propietario),
                joinedload(Incidente.taller),
                joinedload(Incidente.tecnico),
                selectinload(Incidente.historial),
                selectinload(Incidente.evidencias),
                selectinload(Incidente.verificaciones),
                selectinload(Incidente.pago),
                selectinload(Incidente.sucursal),
            )
            .order_by(Incidente.fecha_reporte.desc())
        )

        if date_from is not None:
            stmt = stmt.where(Incidente.fecha_reporte >= date_from)
        if date_to is not None:
            stmt = stmt.where(Incidente.fecha_reporte <= date_to)
        if id_taller is not None:
            stmt = stmt.where(Incidente.id_taller == id_taller)
        if id_sucursal is not None:
            stmt = stmt.where(Incidente.id_sucursal == id_sucursal)
        if estado:
            stmt = stmt.where(Incidente.estado_incidente == estado)
        if prioridad:
            stmt = stmt.where(Incidente.prioridad_incidente == prioridad)
        if origen:
            stmt = stmt.where(Incidente.origen == origen)

        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def get_user_operational_context(self, user_id: uuid.UUID) -> tuple[Optional[uuid.UUID], Optional[uuid.UUID], Optional[str]]:
        from app.packages.workshops.domain.models import AdministradorTaller, UsuarioTaller

        admin_link = await self.session.execute(
            select(AdministradorTaller).where(AdministradorTaller.id_usuario == user_id)
        )
        admin_link_obj = admin_link.scalars().first()
        if admin_link_obj:
            return admin_link_obj.id_taller, None, "owner"

        user_taller = await self.session.execute(
            select(UsuarioTaller).where(
                UsuarioTaller.id_usuario == user_id,
                UsuarioTaller.estado == True,
            )
        )
        user_taller_obj = user_taller.scalars().first()
        if user_taller_obj:
            return user_taller_obj.id_taller, user_taller_obj.id_sucursal, user_taller_obj.rol_contexto

        tecnico = await self.session.execute(
            select(Tecnico).where(Tecnico.id_usuario == user_id, Tecnico.estado == True)
        )
        tecnico_obj = tecnico.scalars().first()
        if tecnico_obj:
            return tecnico_obj.id_taller, tecnico_obj.id_sucursal, "tecnico"

        return None, None, None

    async def get_workshops(self) -> list[Taller]:
        result = await self.session.execute(select(Taller).order_by(Taller.nombre.asc()))
        return list(result.scalars().all())

    async def get_branches(self, id_taller: uuid.UUID) -> list[SucursalTaller]:
        result = await self.session.execute(
            select(SucursalTaller)
            .where(SucursalTaller.id_taller == id_taller)
            .order_by(SucursalTaller.nombre.asc())
        )
        return list(result.scalars().all())
