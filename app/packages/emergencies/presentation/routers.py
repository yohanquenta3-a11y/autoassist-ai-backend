import uuid
from fastapi import APIRouter, Depends, status, UploadFile, File, Form, BackgroundTasks, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from geoalchemy2.shape import to_shape

from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.packages.identity.domain.models import Usuario
from app.packages.identity.infrastructure.repositories import UserRepository
from app.packages.emergencies.infrastructure.repositories import IncidentRepository
from app.packages.emergencies.presentation.schemas import IncidentCreate, IncidentResponse, EvidenceResponse, TrackingRequest, IncidentStatusUpdate
from app.packages.emergencies.application.create_incident import CreateIncidentUseCase
from app.packages.emergencies.application.upload_evidence import UploadEvidenceUseCase
from app.packages.emergencies.application.analyze_incident_ai import AnalyzeIncidentAIUseCase
from app.packages.emergencies.application.tasks import run_full_incident_pipeline, run_full_incident_pipeline_task

router = APIRouter()


def get_incident_repository(session: AsyncSession = Depends(get_db)) -> IncidentRepository:
    return IncidentRepository(session)


def get_user_repository(session: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(session)


def _build_incident_response(incident) -> IncidentResponse:
    """
    Transforma un objeto Incidente (modelo) a IncidentResponse (esquema),
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
        id_tecnico=incident.id_tecnico,
        workshop_name=incident.taller.nombre if incident.taller else None,
        technician_name=incident.tecnico.nombre if incident.tecnico else None,
        technician_phone=incident.tecnico.telefono if incident.tecnico else None,
        descripcion=incident.descripcion,
        telefono=incident.telefono,
        estado_incidente=incident.estado_incidente,
        prioridad_incidente=incident.prioridad_incidente,
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
        vehicle_year=incident.vehiculo.ano if incident.vehiculo else None
    )


@router.get("/me/active", response_model=Optional[IncidentResponse])
async def get_my_active_incident(
    current_user: Usuario = Depends(get_current_active_user),
    incident_repo: IncidentRepository = Depends(get_incident_repository)
):
    """
    (CU Móvil) Consulta si el usuario (cliente o técnico) tiene una emergencia activa.
    Retorna el incidente con detalles de taller y técnico si existen.
    """
    if current_user.rol_nombre == "tecnico":
        incident = await incident_repo.get_active_by_technician(current_user.id_usuario)
    else:
        incident = await incident_repo.get_active_by_user(current_user.id_usuario)
        
    if not incident:
        return None
    return _build_incident_response(incident)


@router.get("/me/history", response_model=list[IncidentResponse])
async def get_my_incident_history(
    current_user: Usuario = Depends(get_current_active_user),
    incident_repo: IncidentRepository = Depends(get_incident_repository)
):
    """
    (CU Móvil) Obtiene el historial completo de incidentes del usuario autenticado.
    """
    incidentes = await incident_repo.get_history_by_user(current_user.id_usuario)
    return [_build_incident_response(i) for i in incidentes]


@router.get("/", response_model=list[IncidentResponse])
async def list_all_incidents(
    current_user: Usuario = Depends(get_current_active_user),
    incident_repo: IncidentRepository = Depends(get_incident_repository),
    db: AsyncSession = Depends(get_db),
    page: Optional[int] = Query(None, ge=0, description="Página (0-indexed)"),
    size: Optional[int] = Query(None, ge=1, le=100, description="Tamaño de página"),
):
    """Listado de incidentes. SuperAdmin ve todo, AdminTaller ve lo de su taller."""
    from app.packages.identity.domain.models import ROL_SUPERADMIN, ROL_ADMIN_TALLER
    from app.packages.workshops.domain.models import AdministradorTaller
    from sqlalchemy.future import select
    
    skip = page * size if (page is not None and size is not None) else None
    
    if current_user.rol_nombre == ROL_SUPERADMIN:
        incidentes = await incident_repo.get_all(skip=skip, limit=size)
    elif current_user.rol_nombre == ROL_ADMIN_TALLER:
        # Buscar a qué taller pertenece este administrador
        result = await db.execute(
            select(AdministradorTaller.id_taller).where(AdministradorTaller.id_usuario == current_user.id_usuario)
        )
        taller_id = result.scalar_one_or_none()
        
        if not taller_id:
            return []
            
        incidentes = await incident_repo.get_by_workshop(taller_id, skip=skip, limit=size)
    else:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("No tienes permisos para ver el historial de incidentes.")
        
    return [_build_incident_response(i) for i in incidentes]


@router.post("/", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
async def report_incident(
    incident_in: IncidentCreate,
    current_user: Usuario = Depends(get_current_active_user),
    incident_repo: IncidentRepository = Depends(get_incident_repository),
    user_repo: UserRepository = Depends(get_user_repository)
):
    """(CU5) Reportar una nueva emergencia. El vehículo debe pertenecer al cliente autenticado."""
    use_case = CreateIncidentUseCase(incident_repo, user_repo)
    incident = await use_case.execute(current_user, incident_in)
    
    # Notificación Real-time para Admins
    from app.core.notifications import manager
    await manager.notify_admins({"type": "NEW_INCIDENT", "id": str(incident.id_incidente)})
    
    return _build_incident_response(incident)


@router.post("/{incident_id}/evidence", response_model=EvidenceResponse, status_code=status.HTTP_201_CREATED)
async def upload_evidence(
    incident_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    evidencia_tipo: str = Form(...),
    current_user: Usuario = Depends(get_current_active_user),
    incident_repo: IncidentRepository = Depends(get_incident_repository),
    user_repo: UserRepository = Depends(get_user_repository)
):
    """(CU6) Cargar evidencia y gatillar análisis de IA en segundo plano."""
    use_case = UploadEvidenceUseCase(incident_repo, user_repo)
    evidence = await use_case.execute(current_user, incident_id, file, evidencia_tipo)
    
    return evidence

@router.post("/{incident_id}/analyze", response_model=IncidentResponse)
async def manual_ai_analysis(
    incident_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    incident_repo: IncidentRepository = Depends(get_incident_repository)
):
    """Disparar manualmente el análisis de IA (útil para pruebas)."""
    ai_use_case = AnalyzeIncidentAIUseCase(incident_repo)
    result = await ai_use_case.execute(incident_id)
    if not result:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Incidente no encontrado.")
    return _build_incident_response(result)


@router.post("/{incident_id}/process", status_code=status.HTTP_202_ACCEPTED)
async def process_incident_pipeline(
    incident_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user)
):
    """
    (CU Móvil) Gatillar el pipeline completo (IA + Asignación) una vez 
    que todas las evidencias han sido cargadas.
    """
    run_full_incident_pipeline_task.delay(str(incident_id))
    return {"message": "Pipeline iniciado en segundo plano"}


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    incident_repo: IncidentRepository = Depends(get_incident_repository)
):
    """Consultar el detalle completo de un incidente (con sus evidencias)."""
    from app.core.exceptions import NotFoundError
    incidente = await incident_repo.get_by_id(incident_id)
    if not incidente:
        raise NotFoundError("Incidente no encontrado.")
    return _build_incident_response(incidente)
@router.post("/{incident_id}/cancel", response_model=IncidentResponse)
async def cancel_incident(
    incident_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    incident_repo: IncidentRepository = Depends(get_incident_repository)
):
    """(CU Móvil) Cancelar una emergencia activa."""
    from app.core.exceptions import NotFoundError
    from fastapi import HTTPException
    
    # Verificación de seguridad: ¿Este incidente le pertenece al usuario actual?
    incident = await incident_repo.get_by_id(incident_id)
    if not incident:
        raise NotFoundError("Incidente no encontrado.")
        
    if incident.vehiculo.id_usuario != current_user.id_usuario:
        raise HTTPException(
            status_code=403, 
            detail="No tienes permiso para cancelar este incidente."
        )

    result = await incident_repo.cancel_incident(incident_id, actor=f"CLIENTE:{current_user.nombre}")
    if not result:
        raise NotFoundError("Error al cancelar el incidente.")
    
    # Notificar a la web que se canceló
    from app.core.notifications import manager
    await manager.notify_admins({"type": "INCIDENT_CANCELLED", "id": str(incident_id)})
    
    return _build_incident_response(result)


@router.patch("/{incident_id}/status", response_model=IncidentResponse)
async def update_incident_status_mobile(
    incident_id: uuid.UUID,
    payload: IncidentStatusUpdate,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    (CU Técnico Móvil) Permite al técnico asignado o al administrador del taller
    actualizar el estado de la emergencia (TALLER_ASIGNADO -> EN_CAMINO -> EN_ATENCION -> FINALIZADO).
    """
    from app.core.exceptions import NotFoundError, ForbiddenError
    from app.packages.workshops.domain.models import Tecnico, AdministradorTaller, UsuarioTaller
    from sqlalchemy.future import select
    from app.packages.emergencies.domain.models import HistorialIncidente

    # 1. Obtener incidente
    incident_repo = IncidentRepository(db)
    incidente = await incident_repo.get_by_id(incident_id)
    if not incidente:
        raise NotFoundError("Incidente no encontrado.")

    # 2. Validar autorización según rol del usuario
    authorized = False
    
    if current_user.rol_nombre == "tecnico":
        # Comprobar que sea el técnico asignado a este incidente
        tecnico_res = await db.execute(
            select(Tecnico).where(Tecnico.id_usuario == current_user.id_usuario)
        )
        tecnico = tecnico_res.scalars().first()
        if tecnico and incidente.id_tecnico == tecnico.id_tecnico:
            authorized = True
    elif current_user.rol_nombre == "admin_taller":
        # Comprobar si es administrador del taller asignado a la emergencia
        # O si es admin de la sucursal asignada a la emergencia
        relation = await db.execute(
            select(UsuarioTaller).where(UsuarioTaller.id_usuario == current_user.id_usuario)
        )
        user_taller = relation.scalars().first()
        if user_taller:
            # Si es admin de sucursal, debe coincidir la sucursal
            if user_taller.rol_contexto == "admin_sucursal" and incidente.id_sucursal == user_taller.id_sucursal:
                authorized = True
            # Si es owner del taller
            elif user_taller.rol_contexto == "owner" and incidente.id_taller == user_taller.id_taller:
                authorized = True
        else:
            # Buscar en AdministradorTaller (Owners globales)
            admin_res = await db.execute(
                select(AdministradorTaller).where(AdministradorTaller.id_usuario == current_user.id_usuario)
            )
            admin_link = admin_res.scalars().first()
            if admin_link and incidente.id_taller == admin_link.id_taller:
                authorized = True
    elif current_user.rol_nombre == "superadmin":
        authorized = True

    if not authorized:
        raise ForbiddenError("No tienes permisos para modificar el estado de esta emergencia.")

    # 3. Registrar cambio en historial y actualizar estado
    estado_anterior = incidente.estado_incidente
    incidente.estado_incidente = payload.nuevo_estado
    
    # Si pasa a finalizado o cancelado, liberar al técnico (hacerlo disponible)
    if payload.nuevo_estado in ["FINALIZADO", "CANCELADO", "COMPLETADO"] and incidente.tecnico:
        incidente.tecnico.estado = True # Disponible para nuevas asignaciones
        
    historial = HistorialIncidente(
        id_incidente=incidente.id_incidente,
        incidente_estado_anterior=estado_anterior,
        incidente_estado_nuevo=payload.nuevo_estado,
        historial_actor=f"{current_user.rol_nombre.upper()}:{current_user.nombre}",
        fecha=None
    )
    incidente.historial.append(historial)
    
    await db.commit()
    await db.refresh(incidente)

    # 4. Notificaciones en Tiempo Real (WebSocket y push si corresponde)
    from app.core.notifications import manager as notify_manager
    from app.core.websocket import manager as ws_manager
    
    # Estructura del evento de actualización de estado
    status_event = {
        "type": "STATUS_UPDATED",
        "data": {
            "id_incidente": str(incident_id),
            "estado_anterior": estado_anterior,
            "estado_nuevo": payload.nuevo_estado,
            "id_taller": str(incidente.id_taller) if incidente.id_taller else None,
            "id_tecnico": str(incidente.id_tecnico) if incidente.id_tecnico else None,
        }
    }
    
    # Emitir por canal WebSocket del incidente (al cliente)
    await ws_manager.broadcast_to_incident(str(incident_id), status_event)
    
    # Notificar a canales generales (Admins web, taller, etc.)
    if incidente.id_taller:
        await notify_manager.notify_workshop(str(incidente.id_taller), status_event)
    await notify_manager.notify_admins(status_event)

    return _build_incident_response(incidente)


@router.post("/incidents/{incident_id}/tracking", status_code=status.HTTP_201_CREATED)
async def post_incident_tracking(
    incident_id: uuid.UUID,
    payload: TrackingRequest,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    (CU Técnico Móvil) Recibe las coordenadas GPS en tiempo real del técnico asignado,
    calcula la polilínea y duración con tráfico (ETA) llamando a Google Directions API,
    almacena el registro en tracking_tecnico y difunde la actualización por WebSocket.
    """
    from app.core.exceptions import NotFoundError
    from app.packages.assignment.domain.models import AsignacionIncidente
    from app.packages.workshops.domain.models import TrackingTecnico
    from sqlalchemy.future import select
    from decimal import Decimal
    import logging
    import httpx
    from app.core.config import settings

    logger = logging.getLogger(__name__)

    # 1. Validar incidente
    incident_repo = IncidentRepository(db)
    incident = await incident_repo.get_by_id(incident_id)
    if not incident:
        raise NotFoundError("Incidente no encontrado.")

    # 2. Validar que el incidente esté activo
    if incident.estado_incidente not in ["TALLER_ASIGNADO", "EN_CAMINO", "EN_ATENCION"]:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"No se puede rastrear un incidente en estado {incident.estado_incidente}."
        )

    # 3. Buscar la asignación activa
    result = await db.execute(
        select(AsignacionIncidente)
        .where(AsignacionIncidente.id_incidente == incident_id)
        .where(AsignacionIncidente.estado_asignacion.in_(["ACEPTADO", "ASIGNADO"]))
        .order_by(AsignacionIncidente.fecha_asignacion.desc())
    )
    asignacion = result.scalar_one_or_none()
    if not asignacion:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="No se encontró una asignación de taller activa para este incidente."
        )

    # 4. Guardar coordenadas
    tracking = TrackingTecnico(
        id_asignacion=asignacion.id_asignacion,
        id_taller=incident.id_taller,
        id_sucursal=incident.id_sucursal,
        latitud=Decimal(str(payload.latitud)),
        longitud=Decimal(str(payload.longitud)),
        velocidad=Decimal(str(payload.velocidad)) if payload.velocidad is not None else None,
        estado_tracking="TRANSMITIENDO"
    )
    db.add(tracking)
    await db.commit()

    # 5. Consultar Google Directions API para ruta óptima y ETA real
    eta_minutos = None
    polyline_ruta = None

    if incident.ubicacion_emergencia is not None:
        try:
            dest_lat = to_shape(incident.ubicacion_emergencia).y
            dest_lng = to_shape(incident.ubicacion_emergencia).x

            if settings.GOOGLE_MAPS_BACKEND_KEY:
                async with httpx.AsyncClient() as client:
                    url = "https://maps.googleapis.com/maps/api/directions/json"
                    params = {
                        "origin": f"{payload.latitud},{payload.longitud}",
                        "destination": f"{dest_lat},{dest_lng}",
                        "key": settings.GOOGLE_MAPS_BACKEND_KEY,
                        "departure_time": "now",
                        "traffic_model": "best_guess"
                    }
                    response = await client.get(url, params=params, timeout=4.0)
                    if response.status_code == 200:
                        res_json = response.json()
                        if res_json.get("status") == "OK" and res_json.get("routes"):
                            route = res_json["routes"][0]
                            polyline_ruta = route["overview_polyline"]["points"]
                            legs = route["legs"][0]
                            duration = legs.get("duration_in_traffic", legs.get("duration", {}))
                            seconds = duration.get("value", 0)
                            eta_minutos = max(1, round(seconds / 60.0))
        except Exception as e:
            logger.error(f"Error consultando Google Directions API: {e}")

    # 6. Difundir ubicación en tiempo real
    from app.core.websocket import manager as ws_manager
    await ws_manager.broadcast_to_incident(
        str(incident_id),
        {
            "type": "TRACKING_UPDATE",
            "data": {
                "latitud": payload.latitud,
                "longitud": payload.longitud,
                "velocidad": payload.velocidad,
                "eta_minutos": eta_minutos,
                "polyline_ruta": polyline_ruta,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )

    return {"status": "success", "eta_minutos": eta_minutos}


@router.websocket("/ws/incidents/{incident_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    incident_id: str,
    token: Optional[str] = Query(None),
    id_sucursal: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Endpoint WebSocket para suscribirse a eventos de tracking y estados en vivo de un incidente.
    Valida el token JWT por parámetros de consulta y aplica scoping por rol y sucursal.
    """
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        from jose import jwt
        from app.core.config import settings
        from app.packages.identity.infrastructure.repositories import UserRepository
        from app.packages.emergencies.infrastructure.repositories import IncidentRepository
        from app.packages.workshops.domain.models import UsuarioTaller, AdministradorTaller, Tecnico
        from sqlalchemy import select
        import uuid
        
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_uuid = payload.get("sub")
        if not user_uuid:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        repo = UserRepository(db)
        user = await repo.get_by_id(uuid.UUID(user_uuid))
        if not user or not user.estado:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Load incident
        incident_repo = IncidentRepository(db)
        incident = await incident_repo.get_by_id(uuid.UUID(incident_id))
        if not incident:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        role = user.rol_nombre

        # Role-based Scoping
        if role != "superadmin":
            if role == "cliente":
                # Check that client owns the incident's vehicle
                if not incident.vehiculo or incident.vehiculo.id_usuario != user.id_usuario:
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    return
            
            elif role == "tecnico":
                # Check that technician is assigned to this incident
                result_tec = await db.execute(
                    select(Tecnico).where(
                        Tecnico.id_usuario == user.id_usuario,
                        Tecnico.estado == True
                    )
                )
                tec = result_tec.scalars().first()
                if not tec or incident.id_tecnico != tec.id_tecnico:
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    return

            else:
                # Check if Admin Sucursal
                result_ut = await db.execute(
                    select(UsuarioTaller).where(
                        UsuarioTaller.id_usuario == user.id_usuario,
                        UsuarioTaller.rol_contexto == "admin_sucursal",
                        UsuarioTaller.estado == True
                    )
                )
                ut_link = result_ut.scalars().first()

                # Check if Owner
                result_owner = await db.execute(
                    select(AdministradorTaller).where(AdministradorTaller.id_usuario == user.id_usuario)
                )
                is_owner = result_owner.scalars().first() is not None

                # Clean query param id_sucursal
                clean_sucursal_param = None
                if id_sucursal:
                    cleaned = id_sucursal.strip().lower()
                    if cleaned not in ("", "null", "undefined", "none"):
                        try:
                            clean_sucursal_param = uuid.UUID(cleaned)
                        except ValueError:
                            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                            return

                if is_owner and not ut_link:
                    # Owner must select a branch and the incident must belong to that branch
                    if not clean_sucursal_param:
                        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                        return
                    
                    # Check Owner workshop
                    from app.packages.workshops.infrastructure.repositories import WorkshopRepository
                    workshop_repo = WorkshopRepository(db)
                    taller = await workshop_repo.get_by_admin(user.id_usuario)
                    if not taller or incident.id_taller != taller.id_taller:
                        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                        return

                    # Validate selected branch belongs to workshop
                    branch = await workshop_repo.get_branch_by_id(clean_sucursal_param, taller.id_taller)
                    if not branch or not branch.is_active or incident.id_sucursal != clean_sucursal_param:
                        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                        return

                elif ut_link:
                    # Admin Sucursal: incident must belong to their branch
                    if not ut_link.id_sucursal or incident.id_sucursal != ut_link.id_sucursal:
                        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                        return

                else:
                    # Any other role without access
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    return

    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    from app.core.websocket import manager as ws_manager
    await ws_manager.connect(incident_id, websocket)
    try:
        while True:
            # Escucha para mantener el socket activo y responder a pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(incident_id, websocket)
