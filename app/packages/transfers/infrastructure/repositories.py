import uuid
from datetime import date, datetime, time, timezone, timedelta
from typing import Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.packages.identity.domain.models import Usuario, Vehiculo
from app.packages.transfers.domain.models import HistorialTraslado, SolicitudTraslado
from app.packages.workshops.domain.models import SucursalTaller, Tecnico

LOCAL_TZ = timezone(timedelta(hours=-4))


class TransferRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _with_relationships(self):
        return (
            selectinload(SolicitudTraslado.cliente),
            selectinload(SolicitudTraslado.vehiculo),
            selectinload(SolicitudTraslado.taller),
            selectinload(SolicitudTraslado.sucursal),
            selectinload(SolicitudTraslado.tecnico),
            selectinload(SolicitudTraslado.historial),
        )

    async def create(self, transfer: SolicitudTraslado) -> SolicitudTraslado:
        self.session.add(transfer)
        await self.session.commit()
        return await self.get_by_id(transfer.id_traslado) or transfer

    async def get_by_id(self, transfer_id: uuid.UUID) -> Optional[SolicitudTraslado]:
        result = await self.session.execute(
            select(SolicitudTraslado)
            .options(*self._with_relationships())
            .where(SolicitudTraslado.id_traslado == transfer_id)
        )
        return result.scalars().first()

    async def get_by_client(self, client_id: uuid.UUID) -> list[SolicitudTraslado]:
        result = await self.session.execute(
            select(SolicitudTraslado)
            .options(*self._with_relationships())
            .where(SolicitudTraslado.id_cliente == client_id)
            .order_by(SolicitudTraslado.fecha_creacion.desc())
        )
        return list(result.scalars().all())

    async def get_by_workshop(
        self,
        workshop_id: uuid.UUID,
        sucursal_id: Optional[uuid.UUID] = None,
        tecnico_id: Optional[uuid.UUID] = None,
        estado: Optional[str] = None,
        tipo_traslado: Optional[str] = None,
        search: Optional[str] = None,
        fecha_desde: Optional[date] = None,
        fecha_hasta: Optional[date] = None,
    ) -> list[SolicitudTraslado]:
        stmt = (
            select(SolicitudTraslado)
            .options(*self._with_relationships())
            .where(SolicitudTraslado.id_taller == workshop_id)
        )

        if sucursal_id is not None:
            stmt = stmt.where(SolicitudTraslado.id_sucursal == sucursal_id)
        if tecnico_id is not None:
            stmt = stmt.where(SolicitudTraslado.id_tecnico == tecnico_id)
        if estado:
            stmt = stmt.where(SolicitudTraslado.estado == estado.upper())
        if tipo_traslado:
            stmt = stmt.where(SolicitudTraslado.tipo_traslado == tipo_traslado.upper())
        if fecha_desde is not None:
            start_local = datetime.combine(fecha_desde, time.min, tzinfo=LOCAL_TZ)
            stmt = stmt.where(
                SolicitudTraslado.fecha_creacion >= start_local.astimezone(timezone.utc).replace(tzinfo=None)
            )
        if fecha_hasta is not None:
            end_local = datetime.combine(fecha_hasta, time.max, tzinfo=LOCAL_TZ)
            stmt = stmt.where(
                SolicitudTraslado.fecha_creacion <= end_local.astimezone(timezone.utc).replace(tzinfo=None)
            )
        if search:
            search_term = f"%{search.strip().lower()}%"
            stmt = (
                stmt.outerjoin(SolicitudTraslado.cliente)
                .outerjoin(SolicitudTraslado.vehiculo)
                .outerjoin(SolicitudTraslado.tecnico)
                .outerjoin(SolicitudTraslado.sucursal)
                .where(
                    or_(
                        func.lower(Usuario.nombre).like(search_term),
                        func.lower(Vehiculo.matricula).like(search_term),
                        func.lower(Vehiculo.marca).like(search_term),
                        func.lower(Vehiculo.modelo).like(search_term),
                        func.lower(SolicitudTraslado.motivo).like(search_term),
                        func.lower(SolicitudTraslado.origen_direccion).like(search_term),
                        func.lower(SolicitudTraslado.destino_direccion).like(search_term),
                        func.lower(func.coalesce(Tecnico.nombre, "")).like(search_term),
                        func.lower(func.coalesce(SucursalTaller.nombre, "")).like(search_term),
                    )
                )
            )

        result = await self.session.execute(stmt.order_by(SolicitudTraslado.fecha_creacion.desc()))
        return list(result.scalars().all())

    async def update(self, transfer: SolicitudTraslado) -> SolicitudTraslado:
        transfer.fecha_modificacion = datetime.utcnow()
        self.session.add(transfer)
        await self.session.commit()
        return await self.get_by_id(transfer.id_traslado) or transfer

    async def add_history(
        self,
        *,
        transfer: SolicitudTraslado,
        previous_state: Optional[str],
        new_state: str,
        actor: str,
        actor_id: Optional[uuid.UUID],
        comentario: Optional[str] = None,
    ) -> HistorialTraslado:
        history = HistorialTraslado(
            id_traslado=transfer.id_traslado,
            estado_anterior=previous_state,
            estado_nuevo=new_state,
            historial_actor=actor,
            id_usuario_actor=actor_id,
            comentario=comentario,
        )
        self.session.add(history)
        return history
