import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.packages.identity.domain.models import ROL_ADMIN_TALLER, ROL_CLIENTE, ROL_SUPERADMIN, Usuario, Vehiculo
from app.packages.transfers.domain.models import SolicitudTraslado
from app.packages.transfers.domain.schemas import ImmediateTransferCreate, ScheduledTransferCreate
from app.packages.transfers.infrastructure.repositories import TransferRepository
from app.packages.workshops.domain.models import AdministradorTaller, SucursalTaller, Tecnico, UsuarioTaller

IMMEDIATE_TYPE = "FLETE_INMEDIATO"
SCHEDULED_TYPE = "PREVENTIVO"

IMMEDIATE_INITIAL = "SOLICITADO"
SCHEDULED_INITIAL = "PROGRAMADO"

CONFIRM_TARGETS = {
    IMMEDIATE_TYPE: "ACEPTADO",
    SCHEDULED_TYPE: "CONFIRMADO",
}

CANCELABLE_STATES = {
    "SOLICITADO",
    "PROGRAMADO",
    "ACEPTADO",
    "CONFIRMADO",
    "REPROGRAMACION_SOLICITADA",
}

ALLOWED_TRANSITIONS = {
    IMMEDIATE_TYPE: {
        "SOLICITADO": {"ACEPTADO", "RECHAZADO", "CANCELADO"},
        "ACEPTADO": {"ASIGNADO", "RECHAZADO", "CANCELADO"},
        "ASIGNADO": {"EN_CAMINO", "CANCELADO"},
        "EN_CAMINO": {"VEHICULO_RECOGIDO"},
        "VEHICULO_RECOGIDO": {"ENTREGADO"},
    },
    SCHEDULED_TYPE: {
        "PROGRAMADO": {"CONFIRMADO", "REPROGRAMACION_SOLICITADA", "RECHAZADO", "CANCELADO"},
        "CONFIRMADO": {"ASIGNADO", "REPROGRAMACION_SOLICITADA", "CANCELADO"},
        "REPROGRAMACION_SOLICITADA": {"CONFIRMADO", "RECHAZADO", "CANCELADO"},
        "ASIGNADO": {"EN_CAMINO", "CANCELADO"},
        "EN_CAMINO": {"VEHICULO_RECOGIDO"},
        "VEHICULO_RECOGIDO": {"ENTREGADO_EN_TALLER"},
    },
}


class TransferService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TransferRepository(db)

    async def _get_vehicle_for_client(self, vehicle_id: uuid.UUID, user: Usuario) -> Vehiculo:
        result = await self.db.execute(select(Vehiculo).where(Vehiculo.id_vehiculo == vehicle_id))
        vehicle = result.scalars().first()
        if not vehicle:
            raise NotFoundError("Vehiculo no encontrado.")
        if vehicle.id_usuario != user.id_usuario:
            raise ForbiddenError("No tienes permisos sobre este vehiculo.")
        return vehicle

    async def _get_branch(self, branch_id: uuid.UUID, workshop_id: Optional[uuid.UUID] = None) -> SucursalTaller:
        stmt = select(SucursalTaller).where(SucursalTaller.id_sucursal == branch_id)
        if workshop_id:
            stmt = stmt.where(SucursalTaller.id_taller == workshop_id)
        result = await self.db.execute(stmt)
        branch = result.scalars().first()
        if not branch or not branch.is_active:
            raise NotFoundError("Sucursal no encontrada.")
        return branch

    async def _resolve_workshop_scope(
        self,
        user: Usuario,
        selected_branch_id: Optional[uuid.UUID],
    ) -> tuple[uuid.UUID, Optional[uuid.UUID], Optional[uuid.UUID]]:
        """Returns workshop_id, branch_id, technician_id for workshop users."""
        if user.rol_nombre == ROL_SUPERADMIN:
            raise ForbiddenError("Endpoint reservado para personal del taller.")

        if user.rol_nombre == "tecnico":
            result = await self.db.execute(select(Tecnico).where(Tecnico.id_usuario == user.id_usuario))
            tecnico = result.scalars().first()
            if not tecnico:
                raise ForbiddenError("Tecnico no asociado a un taller.")
            return tecnico.id_taller, tecnico.id_sucursal, tecnico.id_tecnico

        if user.rol_nombre != ROL_ADMIN_TALLER:
            raise ForbiddenError("No tienes permisos de taller.")

        result_owner = await self.db.execute(
            select(AdministradorTaller).where(AdministradorTaller.id_usuario == user.id_usuario)
        )
        owner = result_owner.scalars().first()
        if owner:
            return owner.id_taller, selected_branch_id, None

        result_ut = await self.db.execute(
            select(UsuarioTaller).where(
                UsuarioTaller.id_usuario == user.id_usuario,
                UsuarioTaller.estado == True,
            )
        )
        relation = result_ut.scalars().first()
        if not relation:
            raise ForbiddenError("Usuario sin taller asociado.")
        return relation.id_taller, relation.id_sucursal or selected_branch_id, None

    async def _ensure_transfer_access(
        self,
        transfer: SolicitudTraslado,
        user: Usuario,
        selected_branch_id: Optional[uuid.UUID] = None,
    ) -> None:
        if user.rol_nombre == ROL_CLIENTE:
            if transfer.id_cliente != user.id_usuario:
                raise ForbiddenError("No tienes permisos sobre este traslado.")
            return

        workshop_id, branch_id, tecnico_id = await self._resolve_workshop_scope(user, selected_branch_id)

        if transfer.id_taller != workshop_id:
            raise ForbiddenError("No tienes permisos sobre traslados de otro taller.")
        if branch_id and transfer.id_sucursal != branch_id:
            raise ForbiddenError("No tienes permisos sobre traslados de otra sucursal.")
        if tecnico_id and transfer.id_tecnico != tecnico_id:
            raise ForbiddenError("No tienes permisos sobre traslados no asignados a ti.")

    async def _validate_technician(
        self,
        *,
        technician_id: uuid.UUID,
        workshop_id: uuid.UUID,
        branch_id: Optional[uuid.UUID],
    ) -> Tecnico:
        result = await self.db.execute(select(Tecnico).where(Tecnico.id_tecnico == technician_id))
        tecnico = result.scalars().first()
        if not tecnico:
            raise NotFoundError("Tecnico no encontrado.")
        if tecnico.id_taller != workshop_id:
            raise ForbiddenError("El tecnico pertenece a otro taller.")
        if branch_id and tecnico.id_sucursal and tecnico.id_sucursal != branch_id:
            raise ForbiddenError("El tecnico pertenece a otra sucursal.")
        return tecnico

    async def _set_state(
        self,
        transfer: SolicitudTraslado,
        new_state: str,
        user: Usuario,
        comentario: Optional[str] = None,
        enforce_transition: bool = True,
    ) -> SolicitudTraslado:
        new_state = new_state.upper().strip()
        previous_state = transfer.estado

        if enforce_transition:
            allowed = ALLOWED_TRANSITIONS.get(transfer.tipo_traslado, {}).get(previous_state, set())
            if new_state not in allowed:
                raise BadRequestError(f"No se puede cambiar de {previous_state} a {new_state}.")

        transfer.estado = new_state
        await self.repo.add_history(
            transfer=transfer,
            previous_state=previous_state,
            new_state=new_state,
            actor=f"{user.rol_nombre.upper()}:{user.nombre}",
            actor_id=user.id_usuario,
            comentario=comentario,
        )
        updated = await self.repo.update(transfer)
        await self._notify_transfer_update(updated)
        return updated

    async def _notify_transfer_update(self, transfer: SolicitudTraslado) -> None:
        try:
            from app.core.notifications import manager as notify_manager

            event = {
                "type": "TRANSFER_UPDATED",
                "id_traslado": str(transfer.id_traslado),
                "estado": transfer.estado,
                "tipo_traslado": transfer.tipo_traslado,
                "id_taller": str(transfer.id_taller) if transfer.id_taller else None,
                "id_sucursal": str(transfer.id_sucursal) if transfer.id_sucursal else None,
            }
            await notify_manager.notify_user(str(transfer.id_cliente), event)
            if transfer.id_taller:
                await notify_manager.notify_workshop(str(transfer.id_taller), event)
        except Exception:
            pass

    async def create_immediate_transfer(self, user: Usuario, payload: ImmediateTransferCreate) -> SolicitudTraslado:
        if user.rol_nombre != ROL_CLIENTE:
            raise ForbiddenError("Solo los clientes pueden solicitar fletes.")
        await self._get_vehicle_for_client(payload.id_vehiculo, user)

        if payload.id_sucursal:
            branch = await self._get_branch(payload.id_sucursal, payload.id_taller)
            id_taller = branch.id_taller
            id_sucursal = branch.id_sucursal
        else:
            id_taller = payload.id_taller
            id_sucursal = None

        transfer = SolicitudTraslado(
            tipo_traslado=IMMEDIATE_TYPE,
            estado=IMMEDIATE_INITIAL,
            id_cliente=user.id_usuario,
            id_vehiculo=payload.id_vehiculo,
            id_taller=id_taller,
            id_sucursal=id_sucursal,
            origen_direccion=payload.origen_direccion,
            origen_latitud=payload.origen_latitud,
            origen_longitud=payload.origen_longitud,
            destino_direccion=payload.destino_direccion,
            destino_latitud=payload.destino_latitud,
            destino_longitud=payload.destino_longitud,
            motivo=payload.motivo,
            observaciones=payload.observaciones,
            telefono_contacto=payload.telefono_contacto,
            creado_por=user.id_usuario,
            rol_creador="CLIENTE",
        )
        self.db.add(transfer)
        await self.db.flush()
        await self.repo.add_history(
            transfer=transfer,
            previous_state=None,
            new_state=IMMEDIATE_INITIAL,
            actor=f"CLIENTE:{user.nombre}",
            actor_id=user.id_usuario,
            comentario="Flete inmediato solicitado",
        )
        await self.db.commit()
        created = await self.repo.get_by_id(transfer.id_traslado)
        await self._notify_transfer_update(created or transfer)
        return created or transfer

    async def create_scheduled_transfer(self, user: Usuario, payload: ScheduledTransferCreate) -> SolicitudTraslado:
        if user.rol_nombre != ROL_CLIENTE:
            raise ForbiddenError("Solo los clientes pueden programar traslados.")
        await self._get_vehicle_for_client(payload.id_vehiculo, user)

        fecha = payload.fecha_programada
        fecha_utc = fecha.astimezone(timezone.utc) if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)
        if fecha_utc <= datetime.now(timezone.utc):
            raise BadRequestError("La fecha programada debe ser futura.")

        branch = await self._get_branch(payload.id_sucursal, payload.id_taller)

        transfer = SolicitudTraslado(
            tipo_traslado=SCHEDULED_TYPE,
            estado=SCHEDULED_INITIAL,
            id_cliente=user.id_usuario,
            id_vehiculo=payload.id_vehiculo,
            id_taller=branch.id_taller,
            id_sucursal=branch.id_sucursal,
            origen_direccion=payload.origen_direccion,
            origen_latitud=payload.origen_latitud,
            origen_longitud=payload.origen_longitud,
            destino_direccion=payload.destino_direccion,
            destino_latitud=payload.destino_latitud,
            destino_longitud=payload.destino_longitud,
            fecha_programada=fecha_utc.replace(tzinfo=None),
            motivo=payload.motivo,
            observaciones=payload.observaciones,
            telefono_contacto=payload.telefono_contacto,
            creado_por=user.id_usuario,
            rol_creador="CLIENTE",
        )
        self.db.add(transfer)
        await self.db.flush()
        await self.repo.add_history(
            transfer=transfer,
            previous_state=None,
            new_state=SCHEDULED_INITIAL,
            actor=f"CLIENTE:{user.nombre}",
            actor_id=user.id_usuario,
            comentario="Traslado preventivo programado",
        )
        await self.db.commit()
        created = await self.repo.get_by_id(transfer.id_traslado)
        await self._notify_transfer_update(created or transfer)
        return created or transfer

    async def list_my_transfers(self, user: Usuario) -> list[SolicitudTraslado]:
        if user.rol_nombre != ROL_CLIENTE:
            raise ForbiddenError("Solo los clientes pueden consultar sus traslados.")
        return await self.repo.get_by_client(user.id_usuario)

    async def list_workshop_transfers(
        self,
        user: Usuario,
        selected_branch_id: Optional[uuid.UUID],
        estado: Optional[str],
        tipo_traslado: Optional[str],
        search: Optional[str],
        fecha_desde,
        fecha_hasta,
        id_tecnico: Optional[uuid.UUID],
    ) -> list[SolicitudTraslado]:
        workshop_id, branch_id, tecnico_id = await self._resolve_workshop_scope(user, selected_branch_id)
        return await self.repo.get_by_workshop(
            workshop_id=workshop_id,
            sucursal_id=branch_id,
            tecnico_id=id_tecnico or tecnico_id,
            estado=estado,
            tipo_traslado=tipo_traslado,
            search=search,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )

    async def get_transfer(self, transfer_id: uuid.UUID, user: Usuario, selected_branch_id: Optional[uuid.UUID] = None):
        transfer = await self.repo.get_by_id(transfer_id)
        if not transfer:
            raise NotFoundError("Traslado no encontrado.")
        await self._ensure_transfer_access(transfer, user, selected_branch_id)
        return transfer

    async def confirm(self, transfer_id: uuid.UUID, user: Usuario, selected_branch_id: Optional[uuid.UUID]):
        transfer = await self.get_transfer(transfer_id, user, selected_branch_id)
        target = CONFIRM_TARGETS.get(transfer.tipo_traslado)
        if not target:
            raise BadRequestError("Tipo de traslado no soportado.")
        return await self._set_state(transfer, target, user)

    async def reject(self, transfer_id: uuid.UUID, user: Usuario, selected_branch_id: Optional[uuid.UUID], comentario: Optional[str]):
        transfer = await self.get_transfer(transfer_id, user, selected_branch_id)
        return await self._set_state(transfer, "RECHAZADO", user, comentario=comentario)

    async def cancel(self, transfer_id: uuid.UUID, user: Usuario, selected_branch_id: Optional[uuid.UUID]):
        transfer = await self.get_transfer(transfer_id, user, selected_branch_id)
        if transfer.estado not in CANCELABLE_STATES:
            raise BadRequestError(f"No se puede cancelar un traslado en estado {transfer.estado}.")
        return await self._set_state(transfer, "CANCELADO", user, enforce_transition=False)

    async def reschedule(
        self,
        transfer_id: uuid.UUID,
        new_date: datetime,
        user: Usuario,
        selected_branch_id: Optional[uuid.UUID],
        comentario: Optional[str],
    ):
        transfer = await self.get_transfer(transfer_id, user, selected_branch_id)
        if transfer.tipo_traslado != SCHEDULED_TYPE:
            raise BadRequestError("Solo los traslados preventivos se pueden reprogramar.")
        fecha_utc = new_date.astimezone(timezone.utc) if new_date.tzinfo else new_date.replace(tzinfo=timezone.utc)
        if fecha_utc <= datetime.now(timezone.utc):
            raise BadRequestError("La nueva fecha debe ser futura.")
        transfer.fecha_programada = fecha_utc.replace(tzinfo=None)
        return await self._set_state(transfer, "REPROGRAMACION_SOLICITADA", user, comentario=comentario)

    async def assign(
        self,
        transfer_id: uuid.UUID,
        technician_id: uuid.UUID,
        user: Usuario,
        selected_branch_id: Optional[uuid.UUID],
    ):
        transfer = await self.get_transfer(transfer_id, user, selected_branch_id)
        if not transfer.id_taller:
            raise BadRequestError("El traslado no tiene taller asignado.")
        await self._validate_technician(
            technician_id=technician_id,
            workshop_id=transfer.id_taller,
            branch_id=transfer.id_sucursal,
        )
        transfer.id_tecnico = technician_id
        return await self._set_state(transfer, "ASIGNADO", user, enforce_transition=False)

    async def update_status(
        self,
        transfer_id: uuid.UUID,
        new_state: str,
        user: Usuario,
        selected_branch_id: Optional[uuid.UUID],
        comentario: Optional[str],
    ):
        transfer = await self.get_transfer(transfer_id, user, selected_branch_id)
        return await self._set_state(transfer, new_state, user, comentario=comentario)
