from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import selectinload
from typing import Optional, List
import uuid
from datetime import datetime, date, time, timezone, timedelta

from app.packages.scheduling.domain.models import Cita
from app.packages.identity.domain.models import Usuario
from app.packages.workshops.domain.models import Tecnico, SucursalTaller
from app.packages.emergencies.domain.models import Incidente

LOCAL_TZ = timezone(timedelta(hours=-4))

class SchedulingRepository:
    """BD operations for Cita scheduling system."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_appointment(self, appointment: Cita) -> Cita:
        self.session.add(appointment)
        await self.session.commit()
        await self.session.refresh(appointment)
        return appointment

    async def get_by_id(self, appointment_id: uuid.UUID) -> Optional[Cita]:
        result = await self.session.execute(
            select(Cita)
            .options(
                selectinload(Cita.cliente),
                selectinload(Cita.vehiculo),
                selectinload(Cita.tecnico),
                selectinload(Cita.sucursal)
            )
            .where(Cita.id_cita == appointment_id)
        )
        return result.scalars().first()

    async def get_active_by_incident(self, incident_id: uuid.UUID) -> Optional[Cita]:
        """Finds any active appointment linked to an incident."""
        result = await self.session.execute(
            select(Cita)
            .where(
                and_(
                    Cita.id_incidente_origen == incident_id,
                    Cita.estado.in_(["PENDIENTE_CONFIRMACION", "CONFIRMADA", "REPROGRAMACION_SOLICITADA"])
                )
            )
        )
        return result.scalars().first()

    async def get_by_client(self, client_id: uuid.UUID) -> List[Cita]:
        result = await self.session.execute(
            select(Cita)
            .options(
                selectinload(Cita.cliente),
                selectinload(Cita.vehiculo),
                selectinload(Cita.tecnico),
                selectinload(Cita.sucursal)
            )
            .where(Cita.id_cliente == client_id)
            .order_by(Cita.fecha_hora.asc())
        )
        return list(result.scalars().all())

    async def get_by_workshop(
        self,
        workshop_id: uuid.UUID,
        sucursal_id: Optional[uuid.UUID] = None,
        tecnico_id: Optional[uuid.UUID] = None,
        estado: Optional[str] = None,
        prioridad: Optional[str] = None,
        tipo: Optional[str] = None,
        search: Optional[str] = None,
        fecha_desde: Optional[date] = None,
        fecha_hasta: Optional[date] = None,
    ) -> List[Cita]:
        stmt = select(Cita).options(
            selectinload(Cita.cliente),
            selectinload(Cita.vehiculo),
            selectinload(Cita.tecnico),
            selectinload(Cita.sucursal)
        ).where(Cita.id_taller == workshop_id)

        if sucursal_id is not None:
            stmt = stmt.where(Cita.id_sucursal == sucursal_id)
        
        if tecnico_id is not None:
            stmt = stmt.where(Cita.id_tecnico == tecnico_id)

        if estado:
            stmt = stmt.where(Cita.estado == estado)

        if prioridad:
            stmt = stmt.where(Cita.prioridad == prioridad)

        if tipo:
            stmt = stmt.where(Cita.tipo == tipo)

        if fecha_desde is not None:
            start_local = datetime.combine(fecha_desde, time.min, tzinfo=LOCAL_TZ)
            stmt = stmt.where(Cita.fecha_hora >= start_local.astimezone(timezone.utc).replace(tzinfo=None))

        if fecha_hasta is not None:
            end_local = datetime.combine(fecha_hasta, time.max, tzinfo=LOCAL_TZ)
            stmt = stmt.where(Cita.fecha_hora <= end_local.astimezone(timezone.utc).replace(tzinfo=None))

        if search:
            search_term = f"%{search.strip().lower()}%"
            stmt = stmt.outerjoin(Cita.cliente).outerjoin(Cita.vehiculo).outerjoin(Cita.tecnico).outerjoin(Cita.sucursal).where(
                or_(
                    func.lower(Usuario.nombre).like(search_term),
                    func.lower(Cita.motivo).like(search_term),
                    func.lower(Cita.observaciones).like(search_term),
                    func.lower(Tecnico.nombre).like(search_term),
                    func.lower(func.coalesce(SucursalTaller.nombre, "")).like(search_term),
                    func.lower(func.coalesce(Cita.tipo, "")).like(search_term),
                )
            )

        result = await self.session.execute(stmt.order_by(Cita.fecha_hora.asc()))
        return list(result.scalars().all())

    async def get_active_by_sucursal_and_date(self, sucursal_id: uuid.UUID, target_date: date) -> List[Cita]:
        """Returns all active appointments for a specific branch and date."""
        start_of_day = datetime.combine(target_date, time.min)
        end_of_day = datetime.combine(target_date, time.max)

        result = await self.session.execute(
            select(Cita)
            .where(
                and_(
                    Cita.id_sucursal == sucursal_id,
                    Cita.fecha_hora >= start_of_day,
                    Cita.fecha_hora <= end_of_day,
                    Cita.estado.in_(["PENDIENTE_CONFIRMACION", "CONFIRMADA", "REPROGRAMACION_SOLICITADA"])
                )
            )
        )
        return list(result.scalars().all())

    async def update_appointment(self, appointment: Cita) -> Cita:
        self.session.add(appointment)
        await self.session.commit()
        await self.session.refresh(appointment)
        return appointment
