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
from app.packages.workshops.dependencies import get_selected_branch_id
from app.packages.emergencies.presentation.schemas import IncidentCreate, IncidentResponse, EvidenceResponse, TrackingRequest, IncidentStatusUpdate, IncidentHistoryResponse, IncidentProcessRequest, TechnicianVerificationRequest, ManualOverrideRequest
from app.packages.emergencies.application.create_incident import CreateIncidentUseCase
from app.packages.emergencies.application.upload_evidence import UploadEvidenceUseCase
from app.packages.emergencies.application.analyze_incident_ai import AnalyzeIncidentAIUseCase
from app.packages.emergencies.application.tasks import run_full_incident_pipeline, run_full_incident_pipeline_task

router = APIRouter()


def get_incident_repository(session: AsyncSession = Depends(get_db)) -> IncidentRepository:
    return IncidentRepository(session)


def get_user_repository(session: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(session)


def _build_incident_response(incident, current_user: Optional[Usuario] = None) -> IncidentResponse:
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

    # Determinar si mostramos el código PIN de verificación
    verification_status = None
    verification_code = None
    if incident.latest_verification:
        verification_status = incident.latest_verification.estado_verificacion
        # Solo mostrar el PIN si NO es el cliente (para evitar inspección de red del cliente)
        if current_user is None or current_user.rol_nombre != "cliente":
            verification_code = incident.latest_verification.codigo_verificacion

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
        transcripcion_audio=incident.transcripcion_audio,
        resumen_ia=incident.resumen_ia,
        analisis_consolidado=incident.analisis_consolidado,
        fecha_reporte=incident.fecha_reporte.isoformat() if incident.fecha_reporte else None,
        latitud=latitud,
        longitud=longitud,
        evidencias=[EvidenceResponse.model_validate(e) for e in incident.evidencias],
        historial=[IncidentHistoryResponse.model_validate(h) for h in incident.historial] if incident.historial else [],
        
        # Nuevos campos
        client_name=incident.vehiculo.propietario.nombre if (incident.vehiculo and incident.vehiculo.propietario) else None,
        client_phone=incident.vehiculo.propietario.telefono if (incident.vehiculo and incident.vehiculo.propietario) else None,
        vehicle_brand=incident.vehiculo.marca if incident.vehiculo else None,
        vehicle_model=incident.vehiculo.modelo if incident.vehiculo else None,
        vehicle_plate=incident.vehiculo.matricula if incident.vehiculo else None,
        vehicle_color=incident.vehiculo.color if incident.vehiculo else None,
        vehicle_year=incident.vehiculo.ano if incident.vehiculo else None,
        
        # Campos de verificación segura CU30
        verification_status=verification_status,
        verification_code=verification_code,
        
        # Campos de cobro y pago
        monto_total=incident.pago.monto if incident.pago else None,
        mano_de_obra=incident.pago.mano_de_obra if incident.pago else None,
        repuestos=incident.pago.repuestos if incident.pago else None,
        observaciones=incident.pago.observaciones if incident.pago else None
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
    return _build_incident_response(incident, current_user)


@router.get("/me/history", response_model=list[IncidentResponse])
async def get_my_incident_history(
    current_user: Usuario = Depends(get_current_active_user),
    incident_repo: IncidentRepository = Depends(get_incident_repository)
):
    """
    (CU Móvil) Obtiene el historial completo de incidentes del usuario autenticado.
    """
    incidentes = await incident_repo.get_history_by_user(current_user.id_usuario)
    return [_build_incident_response(i, current_user) for i in incidentes]


@router.get("/", response_model=list[IncidentResponse])
async def list_all_incidents(
    current_user: Usuario = Depends(get_current_active_user),
    incident_repo: IncidentRepository = Depends(get_incident_repository),
    db: AsyncSession = Depends(get_db),
    page: Optional[int] = Query(None, ge=0, description="Página (0-indexed)"),
    size: Optional[int] = Query(None, ge=1, le=100, description="Tamaño de página"),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
):
    """Listado de incidentes. SuperAdmin ve todo, AdminTaller (Owner/Admin Sucursal) ve su taller/sucursal."""
    from app.packages.identity.domain.models import ROL_SUPERADMIN, ROL_ADMIN_TALLER
    from app.packages.workshops.domain.models import AdministradorTaller, UsuarioTaller
    from sqlalchemy.future import select
    
    skip = page * size if (page is not None and size is not None) else None
    
    if current_user.rol_nombre == ROL_SUPERADMIN:
        incidentes = await incident_repo.get_all(skip=skip, limit=size)
    elif current_user.rol_nombre == ROL_ADMIN_TALLER:
        # Buscar a qué taller pertenece este administrador (Owner)
        result = await db.execute(
            select(AdministradorTaller.id_taller).where(AdministradorTaller.id_usuario == current_user.id_usuario)
        )
        taller_id = result.scalar_one_or_none()
        
        if not taller_id:
            # Buscar si es Admin de Sucursal vinculado
            result_ut = await db.execute(
                select(UsuarioTaller.id_taller).where(
                    UsuarioTaller.id_usuario == current_user.id_usuario,
                    UsuarioTaller.estado == True
                )
            )
            taller_id = result_ut.scalar_one_or_none()
            
        if not taller_id:
            return []
            
        incidentes = await incident_repo.get_by_workshop(
            taller_id=taller_id,
            id_sucursal=selected_branch_id,
            skip=skip,
            limit=size
        )
    else:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("No tienes permisos para ver el historial de incidentes.")
        
    return [_build_incident_response(i, current_user) for i in incidentes]


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
    
    return _build_incident_response(incident, current_user)


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
    return _build_incident_response(result, current_user)


def is_redis_available(redis_url: str) -> bool:
    try:
        from urllib.parse import urlparse
        import socket
        parsed = urlparse(redis_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except Exception:
        return False


@router.post("/{incident_id}/process", status_code=status.HTTP_202_ACCEPTED)
async def process_incident_pipeline(
    incident_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    payload: Optional[IncidentProcessRequest] = None,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    (CU Móvil) Gatillar el pipeline completo (IA + Asignación) una vez 
    que todas las evidencias han sido cargadas.
    Permite persistir la descripción transcrita del incidente.
    """
    if payload and payload.descripcion:
        incident_repo = IncidentRepository(db)
        incident = await incident_repo.get_by_id(incident_id)
        if incident:
            incident.descripcion = payload.descripcion
            await db.commit()
            
    from app.core.config import settings
    import logging
    logger = logging.getLogger(__name__)

    if is_redis_available(settings.REDIS_URL):
        try:
            run_full_incident_pipeline_task.delay(str(incident_id))
            logger.info(f"Pipeline task queued on Celery for incident {incident_id}")
        except Exception as e:
            logger.warning(f"Failed to queue on Celery ({e}). Falling back to FastAPI BackgroundTasks.")
            background_tasks.add_task(run_full_incident_pipeline, incident_id)
    else:
        logger.info(f"Redis is not available. Falling back to FastAPI BackgroundTasks for incident {incident_id}")
        background_tasks.add_task(run_full_incident_pipeline, incident_id)

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
    return _build_incident_response(incidente, current_user)
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
    
    # Notificar por WebSocket a todas las partes
    try:
        from app.core.notifications import manager as notify_manager
        from app.core.websocket import manager as ws_manager
        
        status_event = {
            "type": "STATUS_UPDATED",
            "data": {
                "id_incidente": str(incident_id),
                "estado_anterior": incident.estado_incidente,
                "estado_nuevo": "CANCELADO",
                "id_taller": str(incident.id_taller) if incident.id_taller else None,
                "id_tecnico": str(incident.id_tecnico) if incident.id_tecnico else None,
            }
        }
        await ws_manager.broadcast_to_incident(str(incident_id), status_event)
        await notify_manager.notify_user(str(incident.id_usuario_cliente), status_event)
        if incident.id_taller:
            await notify_manager.notify_workshop(str(incident.id_taller), status_event)
        await notify_manager.notify_admins(status_event)
        await notify_manager.notify_admins({"type": "INCIDENT_CANCELLED", "id": str(incident_id)})
    except Exception:
        pass
    
    return _build_incident_response(result, current_user)


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

    # Restricciones de flujo del CU30:
    # 1. Bloquear transición directa de EN_CAMINO a EN_ATENCION (debe pasar por TECNICO_EN_SITIO)
    if estado_anterior == "EN_CAMINO" and payload.nuevo_estado in ["EN_ATENCION", "EN_PROGRESO"]:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="No se puede pasar directamente de EN_CAMINO a atención. El técnico debe reportar su llegada (TECNICO_EN_SITIO) primero."
        )
    # 2. Bloquear transiciones del técnico a inicio de atención si ya está en sitio sin verificar
    if estado_anterior == "TECNICO_EN_SITIO" and payload.nuevo_estado in ["EN_ATENCION", "EN_PROGRESO"]:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="La transición a EN_ATENCION requiere la verificación segura del técnico por parte del cliente."
        )
    # 3. Bloquear transición directa a FINALIZADO a través de este endpoint
    if payload.nuevo_estado == "FINALIZADO":
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="El cambio de estado a FINALIZADO debe registrarse a través del formulario de cierre y cobro (endpoint /billing)."
        )

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
    
    # Notificar al cliente en su canal WebSocket general
    await notify_manager.notify_user(str(incidente.id_usuario_cliente), status_event)
    
    # Notificar a canales generales (Admins web, taller, etc.)
    if incidente.id_taller:
        await notify_manager.notify_workshop(str(incidente.id_taller), status_event)
    await notify_manager.notify_admins(status_event)

    return _build_incident_response(incidente, current_user)


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
    if incident.estado_incidente not in ["TALLER_ASIGNADO", "EN_CAMINO", "EN_ATENCION", "EN_PROGRESO"]:
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

    if incident.estado_incidente == "EN_CAMINO" and incident.ubicacion_emergencia is not None:
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
                "is_estimated": False,
                "has_tracking": True,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )

    return {"status": "success", "eta_minutos": eta_minutos}


@router.get("/incidents/{incident_id}/tracking/latest")
async def get_latest_tracking(
    incident_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Obtiene la última ubicación conocida del técnico para el incidente.
    """
    from app.core.exceptions import NotFoundError
    from app.packages.assignment.domain.models import AsignacionIncidente
    from app.packages.workshops.domain.models import TrackingTecnico
    from sqlalchemy.future import select
    from geoalchemy2.shape import to_shape
    from app.core.config import settings
    import httpx
    from datetime import datetime

    # 1. Validar incidente
    incident_repo = IncidentRepository(db)
    incident = await incident_repo.get_by_id(incident_id)
    if not incident:
        raise NotFoundError("Incidente no encontrado.")

    # 2. Buscar la asignación activa
    result = await db.execute(
        select(AsignacionIncidente)
        .where(AsignacionIncidente.id_incidente == incident_id)
        .order_by(AsignacionIncidente.fecha_asignacion.desc())
    )
    asignacion = result.scalars().first()
    if not asignacion:
        return {
            "latitud": None,
            "longitud": None,
            "velocidad": None,
            "eta_minutos": None,
            "polyline_ruta": None,
            "is_estimated": False,
            "has_tracking": False,
            "timestamp": None
        }

    # 3. Buscar el último tracking
    result_track = await db.execute(
        select(TrackingTecnico)
        .where(TrackingTecnico.id_asignacion == asignacion.id_asignacion)
        .order_by(TrackingTecnico.fecha_registro.desc())
    )
    tracking = result_track.scalars().first()

    if not tracking:
        return {
            "latitud": None,
            "longitud": None,
            "velocidad": None,
            "eta_minutos": None,
            "polyline_ruta": None,
            "is_estimated": False,
            "has_tracking": False,
            "timestamp": None
        }

    latitud = float(tracking.latitud)
    longitud = float(tracking.longitud)
    velocidad = float(tracking.velocidad) if tracking.velocidad is not None else None
    timestamp = tracking.fecha_registro.isoformat()
    is_estimated = False

    # 4. Calcular ETA y polyline si es necesario
    eta_minutos = None
    polyline_ruta = None
    if incident.estado_incidente == "EN_CAMINO" and incident.ubicacion_emergencia is not None and latitud is not None and longitud is not None:
        try:
            dest_lat = to_shape(incident.ubicacion_emergencia).y
            dest_lng = to_shape(incident.ubicacion_emergencia).x

            if settings.GOOGLE_MAPS_BACKEND_KEY:
                async with httpx.AsyncClient() as client:
                    url = "https://maps.googleapis.com/maps/api/directions/json"
                    params = {
                        "origin": f"{latitud},{longitud}",
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
        except Exception:
            pass

    return {
        "latitud": latitud,
        "longitud": longitud,
        "velocidad": velocidad,
        "eta_minutos": eta_minutos,
        "polyline_ruta": polyline_ruta,
        "is_estimated": is_estimated,
        "has_tracking": True,
        "timestamp": timestamp
    }


async def _notify_verification_change(incident, event_type: str, estado_anterior: str, estado_nuevo: str, db: AsyncSession):
    from app.core.notifications import manager as notify_manager
    from app.core.websocket import manager as ws_manager
    
    status_event = {
        "type": "STATUS_UPDATED",
        "data": {
            "id_incidente": str(incident.id_incidente),
            "estado_anterior": estado_anterior,
            "estado_nuevo": estado_nuevo,
            "id_taller": str(incident.id_taller) if incident.id_taller else None,
            "id_tecnico": str(incident.id_tecnico) if incident.id_tecnico else None,
            "verification_event": event_type
        }
    }
    
    await ws_manager.broadcast_to_incident(str(incident.id_incidente), status_event)
    await notify_manager.notify_user(str(incident.id_usuario_cliente), status_event)
    
    if incident.id_taller:
        await notify_manager.notify_workshop(str(incident.id_taller), status_event)
        
    await notify_manager.notify_admins(status_event)


@router.post("/{incident_id}/verify-technician", response_model=IncidentResponse)
async def validate_verification_code(
    incident_id: uuid.UUID,
    payload: TechnicianVerificationRequest,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    (CU30 Cliente Móvil) Valida la identidad del técnico mediante el PIN ingresado por el cliente.
    Si el PIN coincide, cambia el estado de la emergencia a EN_ATENCION.
    """
    from fastapi import HTTPException
    from app.core.exceptions import NotFoundError, ForbiddenError
    from app.packages.emergencies.domain.models import HistorialIncidente
    from datetime import datetime

    incident_repo = IncidentRepository(db)
    incident = await incident_repo.get_by_id(incident_id)
    if not incident:
        raise NotFoundError("Incidente no encontrado.")

    # Validar que el cliente autenticado es el dueño del incidente
    if incident.vehiculo.id_usuario != current_user.id_usuario:
        raise ForbiddenError("No tienes permisos para verificar este incidente.")

    if incident.estado_incidente != "TECNICO_EN_SITIO":
        raise HTTPException(
            status_code=400,
            detail=f"El incidente se encuentra en estado {incident.estado_incidente}. No está pendiente de verificación."
        )

    verification = incident.latest_verification
    if not verification:
        raise HTTPException(
            status_code=400,
            detail="No se encontró un registro de verificación activo para este incidente."
        )

    if verification.estado_verificacion == "BLOQUEADO":
        raise HTTPException(
            status_code=400,
            detail="La verificación está bloqueada debido a demasiados intentos fallidos. Contacta a soporte."
        )

    if verification.estado_verificacion == "VERIFICADO":
        raise HTTPException(
            status_code=400,
            detail="El técnico ya ha sido verificado anteriormente."
        )

    # Validar el código
    if verification.codigo_verificacion == payload.verification_code:
        # Éxito!
        verification.estado_verificacion = "VERIFICADO"
        verification.resultado = "EXITOSO"
        verification.fecha_verificacion = datetime.utcnow()
        verification.usuario_validador = f"CLIENTE:{current_user.nombre}"
        
        # Transición de estado a EN_ATENCION
        estado_anterior = incident.estado_incidente
        incident.estado_incidente = "EN_ATENCION"

        # Registrar historial
        historial = HistorialIncidente(
            id_incidente=incident.id_incidente,
            incidente_estado_anterior=estado_anterior,
            incidente_estado_nuevo="EN_ATENCION",
            historial_actor=f"CLIENTE:{current_user.nombre}",
            fecha=None
        )
        incident.historial.append(historial)

        # Si el técnico está enlazado, mover su estado a ocupado
        if incident.tecnico:
            incident.tecnico.estado = False # Ocupado en atención
            incident.tecnico.estado_operativo = "EN_ATENCION"

        await db.commit()
        await db.refresh(incident)

        # Notificar por WebSockets
        await _notify_verification_change(incident, "VERIFICATION_SUCCESS", estado_anterior, "EN_ATENCION", db)

        return _build_incident_response(incident, current_user)
    else:
        # Fallido
        verification.intentos += 1
        verification.resultado = "FALLIDO"
        if verification.intentos >= 3:
            verification.estado_verificacion = "BLOQUEADO"
            
        await db.commit()
        
        # Notificar fallo por WebSocket
        await _notify_verification_change(incident, "VERIFICATION_FAILED", incident.estado_incidente, incident.estado_incidente, db)

        if verification.estado_verificacion == "BLOQUEADO":
            raise HTTPException(
                status_code=400,
                detail="Código incorrecto. La verificación ha sido bloqueada tras 3 intentos fallidos."
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Código de verificación inválido. Intentos fallidos: {verification.intentos}/3."
            )


@router.post("/{incident_id}/reject-technician", response_model=IncidentResponse)
async def reject_technician_verification(
    incident_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    (CU30 Cliente Móvil) Reporta que el técnico en sitio no coincide con el asignado.
    No cancela el incidente, lo marca como MISMATCH y lo reporta al taller para intervención/reasignación.
    """
    from fastapi import HTTPException
    from app.core.exceptions import NotFoundError, ForbiddenError
    from app.packages.emergencies.domain.models import HistorialIncidente
    from datetime import datetime

    incident_repo = IncidentRepository(db)
    incident = await incident_repo.get_by_id(incident_id)
    if not incident:
        raise NotFoundError("Incidente no encontrado.")

    if incident.vehiculo.id_usuario != current_user.id_usuario:
        raise ForbiddenError("No tienes permisos para realizar esta acción.")

    if incident.estado_incidente != "TECNICO_EN_SITIO":
        raise HTTPException(
            status_code=400,
            detail="Solo se puede rechazar al técnico si se encuentra en estado de verificación."
        )

    verification = incident.latest_verification
    if not verification:
        raise HTTPException(
            status_code=400,
            detail="No se encontró un registro de verificación activo para este incidente."
        )

    verification.estado_verificacion = "RECHAZADO_ERROR"
    verification.resultado = "MISMATCH"
    verification.fecha_verificacion = datetime.utcnow()
    verification.usuario_validador = f"CLIENTE:{current_user.nombre}"

    # Registrar en el historial de incidentes
    estado_anterior = incident.estado_incidente
    incident.estado_incidente = "TECNICO_RECHAZADO"

    historial = HistorialIncidente(
        id_incidente=incident.id_incidente,
        incidente_estado_anterior=estado_anterior,
        incidente_estado_nuevo="TECNICO_RECHAZADO",
        historial_actor=f"CLIENTE:{current_user.nombre}",
        fecha=None
    )
    incident.historial.append(historial)

    await db.commit()
    await db.refresh(incident)

    # Notificar por WebSockets
    await _notify_verification_change(incident, "VERIFICATION_MISMATCH", estado_anterior, "TECNICO_RECHAZADO", db)

    return _build_incident_response(incident, current_user)


@router.post("/{incident_id}/override-verification", response_model=IncidentResponse)
async def authorize_service_start(
    incident_id: uuid.UUID,
    payload: ManualOverrideRequest,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    (CU30 Web Admin) Permite al administrador o propietario del taller forzar la verificación 
    en caso de problemas de conectividad o lectura (Manual Override). Requiere auditoría estricta.
    """
    from fastapi import HTTPException
    from app.core.exceptions import NotFoundError, ForbiddenError
    from app.packages.emergencies.domain.models import HistorialIncidente
    from app.packages.workshops.domain.models import UsuarioTaller, AdministradorTaller
    from sqlalchemy import select
    from datetime import datetime

    # 1. Validar incidente
    incident_repo = IncidentRepository(db)
    incident = await incident_repo.get_by_id(incident_id)
    if not incident:
        raise NotFoundError("Incidente no encontrado.")

    if incident.estado_incidente not in ["TECNICO_EN_SITIO", "TECNICO_RECHAZADO"]:
        raise HTTPException(
            status_code=400,
            detail="Solo se puede realizar override manual si el técnico está en sitio o fue rechazado."
        )

    # 2. Validar que el usuario es Owner o Admin Sucursal de este taller/sucursal
    authorized = False
    if current_user.rol_nombre == "superadmin":
        authorized = True
    elif current_user.rol_nombre == "admin_taller":
        relation = await db.execute(
            select(UsuarioTaller).where(UsuarioTaller.id_usuario == current_user.id_usuario)
        )
        user_taller = relation.scalars().first()
        if user_taller:
            if user_taller.rol_contexto == "admin_sucursal" and incident.id_sucursal == user_taller.id_sucursal:
                authorized = True
            elif user_taller.rol_contexto == "owner" and incident.id_taller == user_taller.id_taller:
                authorized = True
        else:
            admin_res = await db.execute(
                select(AdministradorTaller).where(AdministradorTaller.id_usuario == current_user.id_usuario)
            )
            admin_link = admin_res.scalars().first()
            if admin_link and incident.id_taller == admin_link.id_taller:
                authorized = True

    if not authorized:
        raise ForbiddenError("No tienes permisos para autorizar el inicio de atención de este incidente.")

    verification = incident.latest_verification
    if not verification:
        raise HTTPException(
            status_code=400,
            detail="No se encontró un registro de verificación activo para este incidente."
        )

    # Aplicar MANUAL_OVERRIDE
    verification.estado_verificacion = "VERIFICADO"
    verification.resultado = "EXITOSO"
    verification.metodo_verificacion = "MANUAL_OVERRIDE"
    verification.fecha_verificacion = datetime.utcnow()
    verification.usuario_validador = f"ADMIN:{current_user.rol_nombre.upper()}:{current_user.nombre}"
    verification.motivo_override = payload.motivo

    # Cambiar estado incidente a EN_ATENCION
    estado_anterior = incident.estado_incidente
    incident.estado_incidente = "EN_ATENCION"

    # Registrar en el historial de incidentes
    historial = HistorialIncidente(
        id_incidente=incident.id_incidente,
        incidente_estado_anterior=estado_anterior,
        incidente_estado_nuevo="EN_ATENCION",
        historial_actor=f"ADMIN:{current_user.rol_nombre.upper()}:{current_user.nombre}",
        fecha=None
    )
    incident.historial.append(historial)

    if incident.tecnico:
        incident.tecnico.estado = False
        incident.tecnico.estado_operativo = "EN_ATENCION"

    await db.commit()
    await db.refresh(incident)

    # Notificar por WebSockets
    await _notify_verification_change(incident, "VERIFICATION_SUCCESS", estado_anterior, "EN_ATENCION", db)

    return _build_incident_response(incident, current_user)


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
                        Tecnico.id_usuario == user.id_usuario
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
