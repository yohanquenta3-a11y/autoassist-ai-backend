import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.packages.identity.domain.models import Usuario
from app.packages.transfers.application.services import TransferService
from app.packages.transfers.domain.models import SolicitudTraslado
from app.packages.transfers.domain.schemas import (
    ImmediateTransferCreate,
    ScheduledTransferCreate,
    TransferAssignRequest,
    TransferRejectRequest,
    TransferRescheduleRequest,
    TransferBranchOption,
    TransferResponse,
    TransferStatusUpdate,
    TransferWorkshopOption,
)
from app.packages.workshops.dependencies import get_selected_branch_id
from app.packages.workshops.domain.models import SucursalTaller, Taller

router = APIRouter()


def _build_transfer_response(transfer: SolicitudTraslado) -> TransferResponse:
    return TransferResponse(
        id_traslado=transfer.id_traslado,
        tipo_traslado=transfer.tipo_traslado,
        estado=transfer.estado,
        id_cliente=transfer.id_cliente,
        id_vehiculo=transfer.id_vehiculo,
        id_taller=transfer.id_taller,
        id_sucursal=transfer.id_sucursal,
        id_tecnico=transfer.id_tecnico,
        origen_direccion=transfer.origen_direccion,
        origen_latitud=transfer.origen_latitud,
        origen_longitud=transfer.origen_longitud,
        destino_direccion=transfer.destino_direccion,
        destino_latitud=transfer.destino_latitud,
        destino_longitud=transfer.destino_longitud,
        fecha_programada=transfer.fecha_programada,
        motivo=transfer.motivo,
        observaciones=transfer.observaciones,
        telefono_contacto=transfer.telefono_contacto,
        creado_por=transfer.creado_por,
        rol_creador=transfer.rol_creador,
        fecha_creacion=transfer.fecha_creacion,
        fecha_modificacion=transfer.fecha_modificacion,
        cliente_nombre=transfer.cliente.nombre if transfer.cliente else None,
        cliente_telefono=transfer.cliente.telefono if transfer.cliente else None,
        vehiculo_matricula=transfer.vehiculo.matricula if transfer.vehiculo else None,
        vehiculo_marca=transfer.vehiculo.marca if transfer.vehiculo else None,
        vehiculo_modelo=transfer.vehiculo.modelo if transfer.vehiculo else None,
        vehiculo_color=transfer.vehiculo.color if transfer.vehiculo else None,
        vehiculo_ano=transfer.vehiculo.ano if transfer.vehiculo else None,
        taller_nombre=transfer.taller.nombre if transfer.taller else None,
        sucursal_nombre=transfer.branch_name,
        tecnico_nombre=transfer.tecnico.nombre if transfer.tecnico else None,
        tecnico_telefono=transfer.tecnico.telefono if transfer.tecnico else None,
        historial=transfer.historial or [],
    )


def get_transfer_service(db: AsyncSession = Depends(get_db)) -> TransferService:
    return TransferService(db)


@router.post("/immediate", response_model=TransferResponse, status_code=status.HTTP_201_CREATED)
async def create_immediate_transfer(
    payload: ImmediateTransferCreate,
    current_user: Usuario = Depends(get_current_active_user),
    service: TransferService = Depends(get_transfer_service),
):
    transfer = await service.create_immediate_transfer(current_user, payload)
    return _build_transfer_response(transfer)


@router.post("/scheduled", response_model=TransferResponse, status_code=status.HTTP_201_CREATED)
async def create_scheduled_transfer(
    payload: ScheduledTransferCreate,
    current_user: Usuario = Depends(get_current_active_user),
    service: TransferService = Depends(get_transfer_service),
):
    transfer = await service.create_scheduled_transfer(current_user, payload)
    return _build_transfer_response(transfer)


@router.get("/me", response_model=list[TransferResponse])
async def list_my_transfers(
    current_user: Usuario = Depends(get_current_active_user),
    service: TransferService = Depends(get_transfer_service),
):
    transfers = await service.list_my_transfers(current_user)
    return [_build_transfer_response(t) for t in transfers]


@router.get("/workshop", response_model=list[TransferResponse])
async def list_workshop_transfers(
    current_user: Usuario = Depends(get_current_active_user),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    estado: Optional[str] = Query(None),
    tipo_traslado: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    id_tecnico: Optional[uuid.UUID] = Query(None),
    service: TransferService = Depends(get_transfer_service),
):
    transfers = await service.list_workshop_transfers(
        user=current_user,
        selected_branch_id=selected_branch_id,
        estado=estado,
        tipo_traslado=tipo_traslado,
        search=search,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        id_tecnico=id_tecnico,
    )
    return [_build_transfer_response(t) for t in transfers]


@router.get("/options/destinations", response_model=list[TransferWorkshopOption])
@router.get("/destinations", response_model=list[TransferWorkshopOption])
async def list_transfer_destinations(
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Lista talleres y sucursales activas para que el cliente programe traslados sin ingresar UUIDs."""
    result = await db.execute(
        select(Taller)
        .options(selectinload(Taller.sucursales))
        .where(Taller.is_active == True)
        .order_by(Taller.nombre)
    )
    workshops = result.scalars().unique().all()

    return [
        TransferWorkshopOption(
            id_taller=workshop.id_taller,
            nombre=workshop.nombre,
            direccion=workshop.direccion,
            sucursales=[
                TransferBranchOption(
                    id_sucursal=branch.id_sucursal,
                    nombre=branch.nombre,
                    direccion=branch.direccion,
                )
                for branch in sorted(
                    [branch for branch in workshop.sucursales if branch.is_active],
                    key=lambda item: item.nombre,
                )
            ],
        )
        for workshop in workshops
        if any(branch.is_active for branch in workshop.sucursales)
    ]


@router.get("/{transfer_id}", response_model=TransferResponse)
async def get_transfer(
    transfer_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    service: TransferService = Depends(get_transfer_service),
):
    transfer = await service.get_transfer(transfer_id, current_user, selected_branch_id)
    return _build_transfer_response(transfer)


@router.put("/{transfer_id}/confirm", response_model=TransferResponse)
async def confirm_transfer(
    transfer_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    service: TransferService = Depends(get_transfer_service),
):
    transfer = await service.confirm(transfer_id, current_user, selected_branch_id)
    return _build_transfer_response(transfer)


@router.put("/{transfer_id}/reject", response_model=TransferResponse)
async def reject_transfer(
    transfer_id: uuid.UUID,
    payload: TransferRejectRequest,
    current_user: Usuario = Depends(get_current_active_user),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    service: TransferService = Depends(get_transfer_service),
):
    transfer = await service.reject(transfer_id, current_user, selected_branch_id, payload.comentario)
    return _build_transfer_response(transfer)


@router.put("/{transfer_id}/cancel", response_model=TransferResponse)
async def cancel_transfer(
    transfer_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    service: TransferService = Depends(get_transfer_service),
):
    transfer = await service.cancel(transfer_id, current_user, selected_branch_id)
    return _build_transfer_response(transfer)


@router.put("/{transfer_id}/reschedule", response_model=TransferResponse)
async def reschedule_transfer(
    transfer_id: uuid.UUID,
    payload: TransferRescheduleRequest,
    current_user: Usuario = Depends(get_current_active_user),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    service: TransferService = Depends(get_transfer_service),
):
    transfer = await service.reschedule(
        transfer_id,
        payload.fecha_programada,
        current_user,
        selected_branch_id,
        payload.comentario,
    )
    return _build_transfer_response(transfer)


@router.put("/{transfer_id}/assign", response_model=TransferResponse)
async def assign_transfer(
    transfer_id: uuid.UUID,
    payload: TransferAssignRequest,
    current_user: Usuario = Depends(get_current_active_user),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    service: TransferService = Depends(get_transfer_service),
):
    transfer = await service.assign(transfer_id, payload.id_tecnico, current_user, selected_branch_id)
    return _build_transfer_response(transfer)


@router.patch("/{transfer_id}/status", response_model=TransferResponse)
async def update_transfer_status(
    transfer_id: uuid.UUID,
    payload: TransferStatusUpdate,
    current_user: Usuario = Depends(get_current_active_user),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    service: TransferService = Depends(get_transfer_service),
):
    transfer = await service.update_status(
        transfer_id,
        payload.estado,
        current_user,
        selected_branch_id,
        payload.comentario,
    )
    return _build_transfer_response(transfer)
