import uuid
import logging
from datetime import date, datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.core.exceptions import BadRequestError, NotFoundError, ForbiddenError
from app.packages.identity.domain.models import Usuario
from app.packages.workshops.dependencies import get_selected_branch_id
from app.packages.scheduling.domain.services import SchedulingService
from app.packages.scheduling.domain.models import Cita
from app.packages.scheduling.domain.schemas import (
    CitaCreate,
    CitaResponse,
    CitaRescheduleRequest,
    SlotAvailabilityResponse
)

logger = logging.getLogger(__name__)
router = APIRouter()

def _build_cita_response(cita: Cita) -> CitaResponse:
    """Enriches the Cita SQLAlchemy model into a CitaResponse Pydantic schema."""
    tecnico_nombre = None
    if cita.tecnico:
        tecnico_nombre = cita.tecnico.nombre

    return CitaResponse(
        id_cita=cita.id_cita,
        id_incidente_origen=cita.id_incidente_origen,
        id_cliente=cita.id_cliente,
        id_vehiculo=cita.id_vehiculo,
        id_taller=cita.id_taller,
        id_sucursal=cita.id_sucursal,
        id_tecnico=cita.id_tecnico,
        fecha_hora=cita.fecha_hora,
        duracion_minutos=cita.duracion_minutos,
        estado=cita.estado,
        tipo=cita.tipo,
        motivo=cita.motivo,
        observaciones=cita.observaciones,
        prioridad=cita.prioridad,
        creado_por=cita.creado_por,
        rol_creador=cita.rol_creador,
        fecha_creacion=cita.fecha_creacion,
        fecha_modificacion=cita.fecha_modificacion,
        cliente_nombre=cita.cliente.nombre if cita.cliente else None,
        cliente_telefono=cita.cliente.telefono if cita.cliente else None,
        vehiculo_matricula=cita.vehiculo.matricula if cita.vehiculo else None,
        vehiculo_marca=cita.vehiculo.marca if cita.vehiculo else None,
        vehiculo_modelo=cita.vehiculo.modelo if cita.vehiculo else None,
        tecnico_nombre=tecnico_nombre,
        sucursal_nombre=cita.sucursal.nombre if cita.sucursal else None,
    )

async def _notify_appointment_update(appt: Cita, db: AsyncSession):
    """Sends real-time updates through WebSocket and Push Notifications."""
    # WebSocket broadcast
    try:
        from app.core.notifications import manager as notify_manager
        msg = {
            "type": "APPOINTMENT_UPDATED",
            "id_cita": str(appt.id_cita),
            "estado": appt.estado,
            "id_taller": str(appt.id_taller),
            "id_sucursal": str(appt.id_sucursal),
            "fecha_hora": appt.fecha_hora.isoformat()
        }
        # Notify user (client)
        await notify_manager.notify_user(str(appt.id_cliente), msg)
        # Notify workshop
        await notify_manager.notify_workshop(str(appt.id_taller), msg)
    except Exception as e:
        logger.warning(f"Error notifying via WebSocket: {e}")

    # Incident room WebSocket broadcast if origins from an incident
    if appt.id_incidente_origen:
        try:
            from app.core.websocket import manager as ws_manager
            await ws_manager.broadcast_to_incident(
                str(appt.id_incidente_origen),
                {
                    "type": "APPOINTMENT_UPDATED",
                    "id_cita": str(appt.id_cita),
                    "estado": appt.estado
                }
            )
        except Exception as e:
            logger.warning(f"Error broadcasting to incident WebSocket: {e}")

    # Push Notification to the client
    try:
        from app.core.push_notifications import push_service
        result_user = await db.execute(
            select(Usuario).where(Usuario.id_usuario == appt.id_cliente)
        )
        client_user = result_user.scalars().first()
        if client_user and client_user.fcm_token:
            title = "Actualización de Cita"
            body = f"Tu cita de seguimiento en taller ha sido actualizada a: {appt.estado}."
            if appt.estado == "PENDIENTE_CONFIRMACION":
                body = "Tienes una nueva cita propuesta de seguimiento posterior. Confírmala en la app."
            elif appt.estado == "CONFIRMADA":
                body = "Tu cita ha sido confirmada con éxito. ¡Te esperamos!"
            elif appt.estado == "CANCELADA":
                body = "Tu cita de seguimiento ha sido cancelada."
            elif appt.estado == "REPROGRAMACION_SOLICITADA":
                body = "Se ha solicitado una reprogramación para tu cita."
            elif appt.estado == "COMPLETADA":
                body = "Tu cita de seguimiento ha sido completada. ¡Gracias por confiar en nosotros!"

            await push_service.send_push_notification(
                token=client_user.fcm_token,
                title=title,
                body=body,
                data={
                    "type": "appointment",
                    "id_cita": str(appt.id_cita),
                    "estado": appt.estado
                }
            )
    except Exception as e:
        logger.warning(f"Error sending push notification: {e}")

@router.get("/slots/availability", response_model=List[SlotAvailabilityResponse])
async def get_availability_slots(
    id_sucursal: uuid.UUID = Query(...),
    date_str: str = Query(..., alias="date"),
    id_tecnico: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Retrieves 60-minute time slots and checks their availability for a specific date and branch."""
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        raise BadRequestError("Formato de fecha inválido. Utilice YYYY-MM-DD.")

    service = SchedulingService(db)
    return await service.get_available_slots(id_sucursal, target_date, id_tecnico)

@router.post("/appointments", response_model=CitaResponse, status_code=status.HTTP_201_CREATED)
async def create_appointment(
    payload: CitaCreate,
    current_user: Usuario = Depends(get_current_active_user),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    db: AsyncSession = Depends(get_db)
):
    """Creates a new follow-up appointment (initially PENDIENTE_CONFIRMACION)."""
    service = SchedulingService(db)
    if (payload.tipo or "POST_AUXILIO").upper() == "DIRECTA":
        appt = await service.create_direct_appointment(
            creator=current_user,
            id_cliente=payload.id_cliente,
            id_vehiculo=payload.id_vehiculo,
            id_sucursal=payload.id_sucursal,
            id_tecnico=payload.id_tecnico,
            fecha_hora=payload.fecha_hora,
            motivo=payload.motivo,
            observaciones=payload.observaciones,
            prioridad=payload.prioridad,
            selected_branch_id=selected_branch_id,
        )
    else:
        appt = await service.create_appointment(
            creator=current_user,
            id_incidente_origen=payload.id_incidente_origen,
            id_vehiculo=payload.id_vehiculo,
            id_tecnico=payload.id_tecnico,
            fecha_hora=payload.fecha_hora,
            motivo=payload.motivo,
            observaciones=payload.observaciones,
            prioridad=payload.prioridad,
        )
    # Refresh to load relationships (e.g. client, vehicle, sucursal, etc.)
    full_appt = await service.repo.get_by_id(appt.id_cita)
    await _notify_appointment_update(full_appt, db)
    return _build_cita_response(full_appt)

@router.get("/appointments/me", response_model=List[CitaResponse])
async def get_my_appointments(
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Returns appointments belonging to the authenticated client."""
    if current_user.rol_nombre != "cliente":
        raise ForbiddenError("Solo los clientes pueden consultar sus propias citas.")
    service = SchedulingService(db)
    citas = await service.repo.get_by_client(current_user.id_usuario)
    return [_build_cita_response(c) for c in citas]

@router.get("/appointments/workshop", response_model=List[CitaResponse])
async def get_workshop_appointments(
    current_user: Usuario = Depends(get_current_active_user),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    estado: Optional[str] = Query(None),
    prioridad: Optional[str] = Query(None),
    tipo: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    id_tecnico: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Returns workshop appointments matching tenant (taller) and branch (sucursal) scope constraints."""
    from app.packages.identity.domain.models import ROL_SUPERADMIN, ROL_ADMIN_TALLER
    from app.packages.workshops.domain.models import AdministradorTaller, UsuarioTaller, Tecnico
    
    taller_id = None
    if current_user.rol_nombre == ROL_SUPERADMIN:
        raise ForbiddenError("Endpoint reservado para personal del taller.")
    elif current_user.rol_nombre == ROL_ADMIN_TALLER:
        result = await db.execute(
            select(AdministradorTaller.id_taller).where(AdministradorTaller.id_usuario == current_user.id_usuario)
        )
        taller_id = result.scalar_one_or_none()
        if not taller_id:
            # Check if Admin Sucursal
            result_ut = await db.execute(
                select(UsuarioTaller.id_taller).where(
                    UsuarioTaller.id_usuario == current_user.id_usuario,
                    UsuarioTaller.estado == True
                )
            )
            taller_id = result_ut.scalar_one_or_none()
    elif current_user.rol_nombre == "tecnico":
        result_tec = await db.execute(
            select(Tecnico.id_taller).where(Tecnico.id_usuario == current_user.id_usuario)
        )
        taller_id = result_tec.scalar_one_or_none()
    
    if not taller_id:
        raise ForbiddenError("No tiene un taller o sucursal asociada.")

    service = SchedulingService(db)
    tecnico_id = None
    if current_user.rol_nombre == "tecnico":
        result_tec = await db.execute(
            select(Tecnico.id_tecnico).where(Tecnico.id_usuario == current_user.id_usuario)
        )
        tecnico_id = result_tec.scalar_one_or_none()
        
    citas = await service.repo.get_by_workshop(
        workshop_id=taller_id,
        sucursal_id=selected_branch_id,
        tecnico_id=id_tecnico or tecnico_id,
        estado=estado,
        prioridad=prioridad,
        tipo=tipo,
        search=search,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )
    return [_build_cita_response(c) for c in citas]

@router.put("/appointments/{appointment_id}/confirm", response_model=CitaResponse)
async def confirm_appointment(
    appointment_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    db: AsyncSession = Depends(get_db)
):
    """Confirms a pending appointment, changing its state to CONFIRMADA."""
    service = SchedulingService(db)
    appt = await service.confirm_appointment(appointment_id, current_user, selected_branch_id)
    # Refresh to load relationships
    full_appt = await service.repo.get_by_id(appt.id_cita)
    await _notify_appointment_update(full_appt, db)
    return _build_cita_response(full_appt)

@router.put("/appointments/{appointment_id}/reschedule", response_model=CitaResponse)
async def reschedule_appointment(
    appointment_id: uuid.UUID,
    payload: CitaRescheduleRequest,
    current_user: Usuario = Depends(get_current_active_user),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    db: AsyncSession = Depends(get_db)
):
    """Requests or proposes rescheduling of an existing appointment."""
    service = SchedulingService(db)
    appt = await service.reschedule_appointment(
        appointment_id=appointment_id,
        new_fecha_hora=payload.fecha_hora,
        observaciones=payload.observaciones,
        user=current_user,
        selected_branch_id=selected_branch_id,
    )
    # Refresh to load relationships
    full_appt = await service.repo.get_by_id(appt.id_cita)
    await _notify_appointment_update(full_appt, db)
    return _build_cita_response(full_appt)

@router.put("/appointments/{appointment_id}/cancel", response_model=CitaResponse)
async def cancel_appointment(
    appointment_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    db: AsyncSession = Depends(get_db)
):
    """Cancels an existing appointment, freeing its slot."""
    service = SchedulingService(db)
    appt = await service.cancel_appointment(appointment_id, current_user, selected_branch_id)
    # Refresh to load relationships
    full_appt = await service.repo.get_by_id(appt.id_cita)
    await _notify_appointment_update(full_appt, db)
    return _build_cita_response(full_appt)

@router.put("/appointments/{appointment_id}/complete", response_model=CitaResponse)
async def complete_appointment(
    appointment_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    db: AsyncSession = Depends(get_db)
):
    """Marks an appointment as completed when the client attends their visit."""
    # Complete is only for taller staff (admin or owner)
    if current_user.rol_nombre == "cliente":
        raise ForbiddenError("Solo el personal del taller puede marcar una cita como completada.")
    service = SchedulingService(db)
    appt = await service.complete_appointment(appointment_id, current_user, selected_branch_id)
    # Refresh to load relationships
    full_appt = await service.repo.get_by_id(appt.id_cita)
    await _notify_appointment_update(full_appt, db)
    return _build_cita_response(full_appt)
