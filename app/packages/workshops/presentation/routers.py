import uuid
from fastapi import APIRouter, Depends, status, Query
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.shape import to_shape

from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.core.exceptions import NotFoundError, ForbiddenError
from app.packages.identity.domain.models import Usuario
from app.packages.workshops.dependencies import get_selected_branch_id, verify_write_permission, validate_resource_branch
from app.packages.workshops.infrastructure.repositories import WorkshopRepository
from app.packages.emergencies.infrastructure.repositories import IncidentRepository
from app.packages.workshops.domain.models import Taller, SucursalTaller, UsuarioTaller
from app.packages.workshops.presentation.schemas import TallerCreate, TallerResponse, StatusUpdate, IncidentAccept, TecnicoResponse, TecnicoCreate, TecnicoUpdate, SucursalCreate, SucursalResponse, AsignarAdminSucursal
from app.packages.emergencies.presentation.schemas import IncidentResponse, EvidenceResponse
from app.packages.workshops.application.register_workshop import RegisterWorkshopUseCase
from app.packages.workshops.application.update_status import UpdateIncidentStatusUseCase

router = APIRouter()


# ─── Helpers ────────────────────────────────────────────────────────────────

def get_workshop_repository(session: AsyncSession = Depends(get_db)) -> WorkshopRepository:
    return WorkshopRepository(session)


@router.patch("/{workshop_id}/status", response_model=TallerResponse)
async def toggle_workshop_status(
    workshop_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    repo: WorkshopRepository = Depends(get_workshop_repository),
):
    """Cambia el estado de activación de un taller. Reservado para SuperAdmin."""
    from app.packages.identity.domain.models import ROL_SUPERADMIN
    if current_user.rol_nombre != ROL_SUPERADMIN:
        raise ForbiddenError("Solo el SuperAdmin puede cambiar el estado de los talleres.")
    
    taller = await repo.get_by_id(workshop_id)
    if not taller:
        raise NotFoundError("Taller no encontrado.")
    
    # Toggle del estado
    taller.is_active = not taller.is_active
    updated_taller = await repo.update_workshop(taller)
    return _build_taller_response(updated_taller)


def _build_taller_response(taller: Taller) -> TallerResponse:
    """
    Construye el TallerResponse extrayendo latitud y longitud del campo
    Geography (PostGIS) del modelo. Si el campo es None, retorna None en ambos.
    """
    latitud = None
    longitud = None

    if taller.ubicacion is not None:
        try:
            point = to_shape(taller.ubicacion)
            # Geography POINT se almacena como POINT(longitud latitud)
            longitud = point.x
            latitud = point.y
        except Exception:
            pass  # Si el campo no puede parsearse, retornamos None

    return TallerResponse(
        id_taller=taller.id_taller,
        nombre=taller.nombre,
        nit=taller.nit,
        telefono=taller.telefono,
        email=taller.email,
        direccion=taller.direccion,
        latitud=latitud,
        longitud=longitud,
        is_active=taller.is_active,
    )


def _build_incident_response(incident) -> IncidentResponse:
    """
    Transforma un objeto Incidente a IncidentResponse,
    extrayendo coordenadas de PostGIS y formateando fechas.
    """
    latitud = None
    longitud = None

    if incident.ubicacion_emergencia is not None:
        try:
            point = to_shape(incident.ubicacion_emergencia)
            longitud = point.x
            latitud = point.y
        except Exception:
            pass

    return IncidentResponse(
        id_incidente=incident.id_incidente,
        id_vehiculo=incident.id_vehiculo,
        id_taller=incident.id_taller,
        id_sucursal=incident.id_sucursal,
        id_tecnico=incident.id_tecnico,
        workshop_name=incident.taller.nombre if incident.taller else None,
        branch_name=incident.branch_name,
        technician_name=incident.tecnico.nombre if incident.tecnico else None,
        technician_phone=incident.tecnico.telefono if incident.tecnico else None,
        descripcion=incident.descripcion,
        telefono=incident.telefono,
        estado_incidente=incident.estado_incidente,
        prioridad_incidente=incident.prioridad_incidente,
        origen=incident.origen,
        id_cotizacion_origen=incident.id_cotizacion_origen,
        transcripcion_audio=incident.transcripcion_audio,
        resumen_ia=incident.resumen_ia,
        analisis_consolidado=incident.analisis_consolidado,
        fecha_reporte=incident.fecha_reporte.isoformat() if incident.fecha_reporte else None,
        latitud=latitud,
        longitud=longitud,
        evidencias=[EvidenceResponse.model_validate(e) for e in incident.evidencias],
        
        # Nuevos campos
        client_name=incident.vehiculo.propietario.nombre if (incident.vehiculo and incident.vehiculo.propietario) else None,
        client_phone=incident.vehiculo.propietario.telefono if (incident.vehiculo and incident.vehiculo.propietario) else None,
        vehicle_brand=incident.vehiculo.marca if incident.vehiculo else None,
        vehicle_model=incident.vehiculo.modelo if incident.vehiculo else None,
        vehicle_plate=incident.vehiculo.matricula if incident.vehiculo else None,
        vehicle_color=incident.vehiculo.color if incident.vehiculo else None,
        vehicle_year=incident.vehiculo.ano if incident.vehiculo else None,

        # Campos de verificación segura CU30
        verification_status=incident.latest_verification.estado_verificacion if incident.latest_verification else None,
        verification_code=incident.latest_verification.codigo_verificacion if incident.latest_verification else None,

        # Campos de cobro y pago
        monto_total=incident.pago.monto if incident.pago else None,
        mano_de_obra=incident.pago.mano_de_obra if incident.pago else None,
        repuestos=incident.pago.repuestos if incident.pago else None,
        observaciones=incident.pago.observaciones if incident.pago else None
    )


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.get("", response_model=list[TallerResponse])
async def list_all_workshops(
    current_user: Usuario = Depends(get_current_active_user),
    repo: WorkshopRepository = Depends(get_workshop_repository),
):
    """Listado global de talleres. Reservado para SuperAdmin."""
    from app.packages.identity.domain.models import ROL_SUPERADMIN
    if current_user.rol_nombre != ROL_SUPERADMIN:
        raise ForbiddenError("Solo el SuperAdmin puede ver la lista global de talleres.")
    
    talleres = await repo.get_all()
    return [_build_taller_response(t) for t in talleres]


@router.post("/", response_model=TallerResponse, status_code=status.HTTP_201_CREATED)
async def register_workshop(
    taller_in: TallerCreate,
    current_user: Usuario = Depends(get_current_active_user),
    repo: WorkshopRepository = Depends(get_workshop_repository)
):
    """(CU13) Registrar un nuevo taller. Requiere rol admin_taller."""
    use_case = RegisterWorkshopUseCase(repo)
    taller = await use_case.execute(current_user, taller_in)
    return _build_taller_response(taller)


@router.get("/me", response_model=TallerResponse)
async def get_my_workshop(
    current_user: Usuario = Depends(get_current_active_user),
    repo: WorkshopRepository = Depends(get_workshop_repository),
):
    """
    Retorna el taller administrado por el usuario autenticado.
    Incluye latitud y longitud extraídas del campo Geography de PostGIS
    para que el frontend pueda renderizarlas en el mapa de Leaflet.
    """
    taller = await repo.get_by_admin(current_user.id_usuario)
    if not taller:
        raise NotFoundError("No tienes ningún taller registrado.")
    return _build_taller_response(taller)

@router.put("/me", response_model=TallerResponse)
async def update_my_workshop(
    taller_in: TallerCreate,
    current_user: Usuario = Depends(get_current_active_user),
    repo: WorkshopRepository = Depends(get_workshop_repository),
):
    """(CU extra) Actualizar los datos del taller del usuario logueado."""
    from app.packages.workshops.application.update_workshop import UpdateWorkshopUseCase
    use_case = UpdateWorkshopUseCase(repo)
    taller = await use_case.execute(current_user, taller_in)
    return _build_taller_response(taller)


@router.get("/{taller_id}", response_model=TallerResponse)
async def get_workshop(
    taller_id: uuid.UUID,
    repo: WorkshopRepository = Depends(get_workshop_repository),
):
    """Consultar un taller por su ID."""
    taller = await repo.get_by_id(taller_id)
    if not taller:
        raise NotFoundError("Taller no encontrado.")
    return _build_taller_response(taller)


@router.get("/me/assignments", response_model=list[IncidentResponse])
async def list_my_assignments(
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    page: Optional[int] = Query(None, ge=0, description="Página (0-indexed)"),
    size: Optional[int] = Query(None, ge=1, le=100, description="Tamaño de página"),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
):
    """Lista las emergencias del taller vinculado al usuario logueado, con soporte opcional de paginación."""
    workshop_repo = WorkshopRepository(db)
    incident_repo = IncidentRepository(db)

    taller = await workshop_repo.get_by_admin(current_user.id_usuario)
    if not taller:
        raise ForbiddenError("No eres administrador de un taller.")

    skip = page * size if (page is not None and size is not None) else None
    incidentes = await incident_repo.get_by_workshop(
        taller_id=taller.id_taller,
        id_sucursal=selected_branch_id,
        skip=skip,
        limit=size
    )
    return [_build_incident_response(i) for i in incidentes]


@router.patch("/me/assignments/{incident_id}/status", response_model=IncidentResponse)
async def update_assignment_status(
    incident_id: uuid.UUID,
    update_in: StatusUpdate,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    selected_branch_id: uuid.UUID = Depends(verify_write_permission),
):
    """Actualiza el estado de un incidente asignado al taller del usuario autenticado."""
    workshop_repo = WorkshopRepository(db)
    incident_repo = IncidentRepository(db)

    taller = await workshop_repo.get_by_admin(current_user.id_usuario)
    if not taller:
        raise ForbiddenError("No eres administrador de un taller.")

    incident = await incident_repo.get_by_id(incident_id)
    if not incident:
        raise NotFoundError("Incidente no encontrado.")

    await validate_resource_branch(incident.id_sucursal, selected_branch_id, current_user, db)

    use_case = UpdateIncidentStatusUseCase(incident_repo)
    incident = await use_case.execute(
        id_taller=taller.id_taller,
        id_incidente=incident_id,
        nuevo_estado=update_in.nuevo_estado,
        actor_nombre=current_user.nombre,
    )

    # Notificar
    from app.core.notifications import manager
    from app.core.websocket import manager as ws_manager

    status_event = {
        "type": "STATUS_UPDATED",
        "data": {
            "id_incidente": str(incident_id),
            "estado_anterior": None,
            "estado_nuevo": update_in.nuevo_estado,
            "id_taller": str(taller.id_taller),
            "id_tecnico": str(incident.id_tecnico) if incident.id_tecnico else None,
        }
    }
    await manager.notify_workshop(str(taller.id_taller), status_event)
    await manager.notify_admins(status_event)
    await manager.notify_user(str(incident.id_usuario_cliente), status_event)
    await ws_manager.broadcast_to_incident(str(incident_id), status_event)

    return _build_incident_response(incident)
    
# --- Técnicos ---

@router.post("/me/technicians", response_model=TecnicoResponse, status_code=status.HTTP_201_CREATED)
async def register_technician(
    tecnico_in: TecnicoCreate,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    selected_branch_id: uuid.UUID = Depends(verify_write_permission),
):
    """(CU14) Registrar un nuevo mecánico para el taller del usuario logueado."""
    from app.packages.workshops.application.manage_technicians import ManageTechniciansUseCase
    from app.packages.identity.infrastructure.repositories import UserRepository
    
    use_case = ManageTechniciansUseCase(WorkshopRepository(db), UserRepository(db))
    return await use_case.add_technician(current_user, tecnico_in, id_sucursal=selected_branch_id)

@router.get("/me/technicians", response_model=list[TecnicoResponse])
async def list_technicians(
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
):
    """(CU14) Listar todos los mecánicos del taller del usuario logueado."""
    from app.packages.workshops.application.manage_technicians import ManageTechniciansUseCase
    from app.packages.identity.infrastructure.repositories import UserRepository
    
    use_case = ManageTechniciansUseCase(WorkshopRepository(db), UserRepository(db))
    return await use_case.list_technicians(current_user, id_sucursal=selected_branch_id)


@router.put("/me/technicians/{tecnico_id}", response_model=TecnicoResponse)
async def update_technician(
    tecnico_id: uuid.UUID,
    tecnico_in: "TecnicoUpdate",
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    selected_branch_id: uuid.UUID = Depends(verify_write_permission),
):
    """(CU14) Actualizar nombre y teléfono de un técnico del taller."""
    from app.packages.workshops.domain.models import Tecnico
    from sqlalchemy.future import select

    workshop_repo = WorkshopRepository(db)
    taller = await workshop_repo.get_by_admin(current_user.id_usuario)
    if not taller:
        raise ForbiddenError("No eres administrador de un taller.")

    result = await db.execute(
        select(Tecnico).where(
            Tecnico.id_tecnico == tecnico_id,
            Tecnico.id_taller == taller.id_taller
        )
    )
    tecnico = result.scalar_one_or_none()
    if not tecnico:
        raise NotFoundError("Técnico no encontrado en este taller.")

    await validate_resource_branch(tecnico.id_sucursal, selected_branch_id, current_user, db)

    if tecnico_in.nombre is not None:
        tecnico.nombre = tecnico_in.nombre
    if tecnico_in.telefono is not None:
        tecnico.telefono = tecnico_in.telefono

    db.add(tecnico)
    await db.commit()
    await db.refresh(tecnico)
    return tecnico


@router.patch("/me/technicians/{tecnico_id}/status", response_model=TecnicoResponse)
async def toggle_technician_status(
    tecnico_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    selected_branch_id: uuid.UUID = Depends(verify_write_permission),
):
    """(CU14) Soft Delete: Activar o desactivar un técnico del taller."""
    from app.packages.workshops.domain.models import Tecnico
    from sqlalchemy.future import select

    workshop_repo = WorkshopRepository(db)
    taller = await workshop_repo.get_by_admin(current_user.id_usuario)
    if not taller:
        raise ForbiddenError("No eres administrador de un taller.")

    result = await db.execute(
        select(Tecnico).where(
            Tecnico.id_tecnico == tecnico_id,
            Tecnico.id_taller == taller.id_taller
        )
    )
    tecnico = result.scalar_one_or_none()
    if not tecnico:
        raise NotFoundError("Técnico no encontrado en este taller.")

    await validate_resource_branch(tecnico.id_sucursal, selected_branch_id, current_user, db)

    tecnico.estado = not tecnico.estado  # Toggle
    db.add(tecnico)
    await db.commit()
    await db.refresh(tecnico)
    return tecnico


@router.post("/me/assignments/{incident_id}/accept", response_model=IncidentResponse)
async def accept_assignment(
    incident_id: uuid.UUID,
    accept_in: IncidentAccept,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    selected_branch_id: uuid.UUID = Depends(verify_write_permission),
):
    """(CU16) Aceptar un incidente y asignar un técnico."""
    from app.packages.workshops.application.accept_reject_incident import AcceptRejectIncidentUseCase
    from app.packages.assignment.infrastructure.repositories import AssignmentRepository
    from app.packages.workshops.domain.models import Tecnico
    from sqlalchemy.future import select
    
    workshop_repo = WorkshopRepository(db)
    taller = await workshop_repo.get_by_admin(current_user.id_usuario)
    if not taller:
        raise ForbiddenError("No eres administrador de un taller.")

    # Load incident to validate branch
    incident = await IncidentRepository(db).get_by_id(incident_id)
    if not incident:
        raise NotFoundError("Incidente no encontrado.")
    await validate_resource_branch(incident.id_sucursal, selected_branch_id, current_user, db)

    # Load technician to validate branch matches
    result_tec = await db.execute(
        select(Tecnico).where(
            Tecnico.id_tecnico == accept_in.id_tecnico,
            Tecnico.id_taller == taller.id_taller
        )
    )
    tecnico = result_tec.scalar_one_or_none()
    if not tecnico:
        raise NotFoundError("Técnico no encontrado.")
    await validate_resource_branch(tecnico.id_sucursal, selected_branch_id, current_user, db)
        
    use_case = AcceptRejectIncidentUseCase(IncidentRepository(db), AssignmentRepository(db))
    estado_anterior = incident.estado_incidente
    incident = await use_case.accept(taller.id_taller, incident_id, accept_in.id_tecnico, current_user.nombre)

    # Notificar
    from app.core.notifications import manager
    from app.core.websocket import manager as ws_manager
    
    status_event = {
        "type": "STATUS_UPDATED",
        "data": {
            "id_incidente": str(incident_id),
            "estado_anterior": estado_anterior,
            "estado_nuevo": "EN_CAMINO",
            "id_taller": str(taller.id_taller),
            "id_tecnico": str(accept_in.id_tecnico),
        }
    }
    
    await manager.notify_workshop(str(taller.id_taller), status_event)
    await manager.notify_admins(status_event)
    await manager.notify_user(str(incident.id_usuario_cliente), status_event)
    await ws_manager.broadcast_to_incident(str(incident_id), status_event)

    return _build_incident_response(incident)

@router.post("/me/assignments/{incident_id}/reject", response_model=Optional[IncidentResponse])
async def reject_assignment(
    incident_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    selected_branch_id: uuid.UUID = Depends(verify_write_permission),
):
    """(CU16) Rechazar un incidente. Dispara la re-asignación inteligente."""
    from app.packages.workshops.application.accept_reject_incident import AcceptRejectIncidentUseCase
    from app.packages.assignment.infrastructure.repositories import AssignmentRepository
    
    workshop_repo = WorkshopRepository(db)
    taller = await workshop_repo.get_by_admin(current_user.id_usuario)
    if not taller:
        raise ForbiddenError("No eres administrador de un taller.")

    # Load incident to validate branch
    incident_to_check = await IncidentRepository(db).get_by_id(incident_id)
    if not incident_to_check:
        raise NotFoundError("Incidente no encontrado.")
    await validate_resource_branch(incident_to_check.id_sucursal, selected_branch_id, current_user, db)
        
    use_case = AcceptRejectIncidentUseCase(IncidentRepository(db), AssignmentRepository(db))
    # Al rechazar, el resultado podría ser una nueva asignación o None si no hay más talleres
    await use_case.reject(taller.id_taller, incident_id, current_user.nombre)
    
    # Retornamos el incidente actualizado (ahora con id_taller=None o nuevo id_taller)
    incident = await IncidentRepository(db).get_by_id(incident_id)
    
    # Notificar
    from app.core.notifications import manager
    await manager.notify_workshop(str(taller.id_taller), {"type": "ASSIGNMENT_REJECTED", "id": str(incident_id)})
    await manager.notify_admins({"type": "ASSIGNMENT_REJECTED", "id": str(incident_id)})
    
    return _build_incident_response(incident) if incident else None

# --- Gestión de Sucursales ---

def _build_sucursal_response(sucursal: SucursalTaller) -> SucursalResponse:
    latitud = None
    longitud = None

    if sucursal.ubicacion is not None:
        try:
            point = to_shape(sucursal.ubicacion)
            longitud = point.x
            latitud = point.y
        except Exception:
            pass

    return SucursalResponse(
        id_sucursal=sucursal.id_sucursal,
        id_taller=sucursal.id_taller,
        nombre=sucursal.nombre,
        telefono=sucursal.telefono,
        direccion=sucursal.direccion,
        latitud=latitud,
        longitud=longitud,
        estado=sucursal.is_active,
        fecha_creacion=sucursal.fecha_creacion
    )

@router.get("/me/branches", response_model=list[SucursalResponse])
async def list_my_branches(
    current_user: Usuario = Depends(get_current_active_user),
    repo: WorkshopRepository = Depends(get_workshop_repository),
):
    """Listar todas las sucursales del taller del administrador Owner logueado."""
    taller = await repo.get_by_admin(current_user.id_usuario)
    if not taller:
        raise ForbiddenError("No tienes un taller registrado.")
    
    from app.packages.identity.domain.models import ROL_ADMIN_TALLER
    if current_user.rol_nombre != ROL_ADMIN_TALLER:
        raise ForbiddenError("No tienes permisos para ver sucursales corporativas.")

    branches = await repo.get_branches_by_workshop(taller.id_taller)
    return [_build_sucursal_response(b) for b in branches]


@router.get("/{id_taller}/branches", response_model=list[SucursalResponse])
async def list_branches_by_workshop(
    id_taller: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    repo: WorkshopRepository = Depends(get_workshop_repository),
):
    """(SuperAdmin) Listar sucursales de un taller especifico."""
    from app.packages.identity.domain.models import ROL_SUPERADMIN

    if current_user.rol_nombre != ROL_SUPERADMIN:
        raise ForbiddenError("Solo el SuperAdmin puede consultar sucursales de cualquier taller.")

    taller = await repo.get_by_id(id_taller)
    if not taller:
        raise NotFoundError("Taller no encontrado.")

    branches = await repo.get_branches_by_workshop(id_taller)
    return [_build_sucursal_response(branch) for branch in branches]

@router.post("/me/branches", response_model=SucursalResponse, status_code=status.HTTP_201_CREATED)
async def create_my_branch(
    sucursal_in: SucursalCreate,
    current_user: Usuario = Depends(get_current_active_user),
    repo: WorkshopRepository = Depends(get_workshop_repository),
):
    """(Owner) Registrar una nueva sucursal física para el taller logueado."""
    taller = await repo.get_by_admin(current_user.id_usuario)
    if not taller:
        raise ForbiddenError("No tienes un taller registrado.")

    from app.packages.identity.domain.models import ROL_ADMIN_TALLER
    if current_user.rol_nombre != ROL_ADMIN_TALLER:
        raise ForbiddenError("Solo el Owner del taller puede registrar sucursales.")

    point_wkt = f"POINT({sucursal_in.longitud} {sucursal_in.latitud})"
    new_sucursal = SucursalTaller(
        id_taller=taller.id_taller,
        nombre=sucursal_in.nombre,
        telefono=sucursal_in.telefono,
        direccion=sucursal_in.direccion,
        ubicacion=point_wkt,
        is_active=True
    )
    sucursal = await repo.create_branch(new_sucursal)
    return _build_sucursal_response(sucursal)

@router.put("/me/branches/{id_sucursal}", response_model=SucursalResponse)
async def update_my_branch(
    id_sucursal: uuid.UUID,
    sucursal_in: SucursalCreate,
    current_user: Usuario = Depends(get_current_active_user),
    repo: WorkshopRepository = Depends(get_workshop_repository),
):
    """(Owner) Modificar datos de una sucursal del taller del Owner logueado."""
    taller = await repo.get_by_admin(current_user.id_usuario)
    if not taller:
        raise ForbiddenError("No tienes un taller registrado.")

    from app.packages.identity.domain.models import ROL_ADMIN_TALLER
    if current_user.rol_nombre != ROL_ADMIN_TALLER:
        raise ForbiddenError("Solo el Owner del taller puede modificar sucursales.")

    sucursal = await repo.get_branch_by_id(id_sucursal, taller.id_taller)
    if not sucursal:
        raise NotFoundError("Sucursal no encontrada en tu taller.")

    point_wkt = f"POINT({sucursal_in.longitud} {sucursal_in.latitud})"
    sucursal.nombre = sucursal_in.nombre
    sucursal.telefono = sucursal_in.telefono
    sucursal.direccion = sucursal_in.direccion
    sucursal.ubicacion = point_wkt

    updated = await repo.update_branch(sucursal)
    return _build_sucursal_response(updated)

@router.delete("/me/branches/{id_sucursal}", response_model=SucursalResponse)
async def deactivate_my_branch(
    id_sucursal: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    repo: WorkshopRepository = Depends(get_workshop_repository),
):
    """(Owner) Desactivar o activar (Soft Delete) una sucursal del taller."""
    taller = await repo.get_by_admin(current_user.id_usuario)
    if not taller:
        raise ForbiddenError("No tienes un taller registrado.")

    from app.packages.identity.domain.models import ROL_ADMIN_TALLER
    if current_user.rol_nombre != ROL_ADMIN_TALLER:
        raise ForbiddenError("Solo el Owner del taller puede cambiar el estado de las sucursales.")

    sucursal = await repo.get_branch_by_id(id_sucursal, taller.id_taller)
    if not sucursal:
        raise NotFoundError("Sucursal no encontrada en tu taller.")

    sucursal.is_active = not sucursal.is_active # Toggle
    updated = await repo.update_branch(sucursal)
    return _build_sucursal_response(updated)

@router.post("/me/branches/assign-admin", status_code=status.HTTP_200_OK)
async def assign_branch_admin(
    assign_in: AsignarAdminSucursal,
    current_user: Usuario = Depends(get_current_active_user),
    repo: WorkshopRepository = Depends(get_workshop_repository),
):
    """(Owner) Asignar un usuario de taller como administrador de una sucursal física."""
    taller = await repo.get_by_admin(current_user.id_usuario)
    if not taller:
        raise ForbiddenError("No tienes un taller registrado.")

    from app.packages.identity.domain.models import ROL_ADMIN_TALLER
    if current_user.rol_nombre != ROL_ADMIN_TALLER:
        raise ForbiddenError("Solo el Owner del taller puede asignar administradores de sucursal.")

    sucursal = await repo.get_branch_by_id(assign_in.id_sucursal, taller.id_taller)
    if not sucursal:
        raise NotFoundError("Sucursal no encontrada en tu taller.")

    existing_relation = await repo.get_user_taller_by_user(assign_in.id_usuario)
    if existing_relation:
        existing_relation.id_sucursal = assign_in.id_sucursal
        existing_relation.rol_contexto = "admin_sucursal"
        await repo.link_user_taller(existing_relation)
    else:
        new_relation = UsuarioTaller(
            id_usuario=assign_in.id_usuario,
            id_taller=taller.id_taller,
            id_sucursal=assign_in.id_sucursal,
            rol_contexto="admin_sucursal",
            estado=True
        )
        await repo.link_user_taller(new_relation)
    
    return {"message": "Administrador asignado a la sucursal con éxito."}

@router.get("/me/my-branch", response_model=SucursalResponse)
async def get_my_branch(
    current_user: Usuario = Depends(get_current_active_user),
    repo: WorkshopRepository = Depends(get_workshop_repository),
):
    """(Admin Sucursal) Obtener los datos de la sucursal asignada al administrador logueado."""
    relation = await repo.get_user_taller_by_user(current_user.id_usuario)
    if not relation or not relation.id_sucursal:
        raise ForbiddenError("No tienes una sucursal física asignada.")

    sucursal = await repo.get_branch_by_id(relation.id_sucursal, relation.id_taller)
    if not sucursal:
        raise NotFoundError("Sucursal no encontrada.")
    
    return _build_sucursal_response(sucursal)

@router.put("/me/my-branch", response_model=SucursalResponse)
async def update_my_branch_local(
    sucursal_in: SucursalCreate,
    current_user: Usuario = Depends(get_current_active_user),
    repo: WorkshopRepository = Depends(get_workshop_repository),
):
    """(Admin Sucursal) Modificar las coordenadas, dirección o teléfono de su propia sucursal física."""
    relation = await repo.get_user_taller_by_user(current_user.id_usuario)
    if not relation or not relation.id_sucursal:
        raise ForbiddenError("No tienes una sucursal física asignada.")

    sucursal = await repo.get_branch_by_id(relation.id_sucursal, relation.id_taller)
    if not sucursal:
        raise NotFoundError("Sucursal no encontrada.")

    point_wkt = f"POINT({sucursal_in.longitud} {sucursal_in.latitud})"
    sucursal.nombre = sucursal_in.nombre
    sucursal.telefono = sucursal_in.telefono
    sucursal.direccion = sucursal_in.direccion
    sucursal.ubicacion = point_wkt

    updated = await repo.update_branch(sucursal)
    return _build_sucursal_response(updated)
