import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_current_active_user
from app.packages.admin.dependencies import get_admin_service
from app.packages.identity.domain.models import Usuario
from app.packages.admin.application.tenant_management import TenantManagementService
from app.packages.admin.presentation.schemas import (
    TallerCreate,
    TallerUpdate,
    TallerResponse,
    UserAssignmentRequest,
    TechnicianAssignmentRequest,
    IncidentResponse,
    MetricasResponse,
    BitacoraResponse,
    IsolationResponse,
)
from app.core.exceptions import NotFoundError, ConflictError, ForbiddenError, BadRequestError

router = APIRouter(prefix="/tenants", tags=["Tenant Management"])


def _handle_service_errors(exc: Exception):
    if isinstance(exc, NotFoundError):
        raise exc
    if isinstance(exc, ConflictError):
        raise exc
    if isinstance(exc, ForbiddenError):
        raise exc
    if isinstance(exc, BadRequestError):
        raise exc
    raise exc


@router.get("/talleres", response_model=List[TallerResponse])
async def list_workshops(
    current_user: Usuario = Depends(get_current_active_user),
    service: TenantManagementService = Depends(get_admin_service)
):
    try:
        talleres = await service.consultar_talleres_tenant(current_user)
        return talleres
    except Exception as exc:
        _handle_service_errors(exc)


@router.post("/talleres", response_model=TallerResponse)
async def create_workshop(
    payload: TallerCreate,
    current_user: Usuario = Depends(get_current_active_user),
    service: TenantManagementService = Depends(get_admin_service)
):
    try:
        taller = await service.registrar_actualizar_taller(current_user, payload.dict())
        await service.registrar_accion_bitacora(
            current_user,
            accion="CREAR_TALLER",
            descripcion=f"Creó taller {taller.nombre}",
            taller_id=taller.id_taller,
            tipo_entidad="taller",
            id_entidad=taller.id_taller,
            datos_despues=payload.dict()
        )
        return taller
    except Exception as exc:
        _handle_service_errors(exc)


@router.patch("/talleres/{id_taller}", response_model=TallerResponse)
async def update_workshop(
    id_taller: uuid.UUID,
    payload: TallerUpdate,
    current_user: Usuario = Depends(get_current_active_user),
    service: TenantManagementService = Depends(get_admin_service)
):
    try:
        taller = await service.registrar_actualizar_taller(current_user, payload.dict(exclude_none=True), id_taller=id_taller)
        await service.registrar_accion_bitacora(
            current_user,
            accion="ACTUALIZAR_TALLER",
            descripcion=f"Actualizó taller {taller.nombre}",
            taller_id=taller.id_taller,
            tipo_entidad="taller",
            id_entidad=taller.id_taller,
            datos_despues=payload.dict(exclude_none=True)
        )
        return taller
    except Exception as exc:
        _handle_service_errors(exc)


@router.patch("/talleres/{id_taller}/estado", response_model=TallerResponse)
async def change_workshop_state(
    id_taller: uuid.UUID,
    activo: bool = Query(..., description="Estado activo para el taller"),
    current_user: Usuario = Depends(get_current_active_user),
    service: TenantManagementService = Depends(get_admin_service)
):
    try:
        taller = await service.activar_desactivar_taller(current_user, id_taller, activo)
        await service.registrar_accion_bitacora(
            current_user,
            accion="CAMBIAR_ESTADO_TALLER",
            descripcion=f"{'Activó' if activo else 'Desactivó'} taller {taller.nombre}",
            taller_id=taller.id_taller,
            tipo_entidad="taller",
            id_entidad=taller.id_taller,
            datos_despues={"is_active": activo}
        )
        return taller
    except Exception as exc:
        _handle_service_errors(exc)


@router.post("/talleres/{id_taller}/usuarios/{id_usuario}", response_model=dict)
async def assign_user_to_workshop(
    id_taller: uuid.UUID,
    id_usuario: uuid.UUID,
    payload: UserAssignmentRequest,
    current_user: Usuario = Depends(get_current_active_user),
    service: TenantManagementService = Depends(get_admin_service)
):
    try:
        link = await service.asignar_usuario_a_taller(
            current_user,
            id_taller,
            id_usuario,
            rol_contexto=payload.rol_contexto,
            id_sucursal=payload.id_sucursal
        )
        await service.registrar_accion_bitacora(
            current_user,
            accion="ASIGNAR_USUARIO_TALLER",
            descripcion=f"Asoció usuario {id_usuario} al taller {id_taller}",
            taller_id=id_taller,
            tipo_entidad="usuario",
            id_entidad=id_usuario,
            datos_despues={"rol_contexto": payload.rol_contexto, "id_sucursal": str(payload.id_sucursal) if payload.id_sucursal else None}
        )
        return {"success": True, "message": "Usuario asignado al taller correctamente."}
    except Exception as exc:
        _handle_service_errors(exc)


@router.post("/talleres/{id_taller}/tecnicos/{id_tecnico}", response_model=dict)
async def assign_technician_to_workshop(
    id_taller: uuid.UUID,
    id_tecnico: uuid.UUID,
    payload: TechnicianAssignmentRequest,
    current_user: Usuario = Depends(get_current_active_user),
    service: TenantManagementService = Depends(get_admin_service)
):
    try:
        tecnico = await service.asociar_tecnico_a_taller(
            current_user,
            id_taller,
            id_tecnico,
            id_sucursal=payload.id_sucursal
        )
        await service.registrar_accion_bitacora(
            current_user,
            accion="ASIGNAR_TECNICO_TALLER",
            descripcion=f"Asoció técnico {tecnico.id_tecnico} al taller {id_taller}",
            taller_id=id_taller,
            tipo_entidad="tecnico",
            id_entidad=tecnico.id_tecnico,
            datos_despues={"id_sucursal": str(payload.id_sucursal) if payload.id_sucursal else None}
        )
        return {"success": True, "message": "Técnico asignado al taller correctamente."}
    except Exception as exc:
        _handle_service_errors(exc)


@router.get("/talleres/{id_taller}/incidentes", response_model=List[IncidentResponse])
async def list_workshop_incidents(
    id_taller: uuid.UUID,
    id_sucursal: Optional[uuid.UUID] = Query(None, description="Filtrar por sucursal del taller"),
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1, le=100),
    current_user: Usuario = Depends(get_current_active_user),
    service: TenantManagementService = Depends(get_admin_service)
):
    try:
        incidents = await service.filtrar_informacion_por_taller(
            current_user,
            id_taller,
            id_sucursal=id_sucursal,
            offset=page * size,
            limit=size
        )
        return incidents
    except Exception as exc:
        _handle_service_errors(exc)


@router.get("/talleres/{id_taller}/metricas", response_model=MetricasResponse)
async def get_workshop_metrics(
    id_taller: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    service: TenantManagementService = Depends(get_admin_service)
):
    try:
        return await service.consultar_metricas_operacionales(current_user, id_taller)
    except Exception as exc:
        _handle_service_errors(exc)


@router.get("/talleres/{id_taller}/bitacora", response_model=List[BitacoraResponse])
async def get_workshop_bitacora(
    id_taller: uuid.UUID,
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1, le=100),
    current_user: Usuario = Depends(get_current_active_user),
    service: TenantManagementService = Depends(get_admin_service)
):
    try:
        entries = await service.consultar_bitacora_taller(
            current_user,
            id_taller,
            offset=page * size,
            limit=size
        )
        return entries
    except Exception as exc:
        _handle_service_errors(exc)


@router.get("/verificar-aislamiento", response_model=IsolationResponse)
async def verify_tenant_isolation(
    id_taller: Optional[uuid.UUID] = Query(None, description="Taller que se desea verificar"),
    id_sucursal: Optional[uuid.UUID] = Query(None, description="Sucursal que se desea verificar"),
    current_user: Usuario = Depends(get_current_active_user),
    service: TenantManagementService = Depends(get_admin_service)
):
    return await service.verificar_aislamiento_informacion(current_user, id_taller=id_taller, id_sucursal=id_sucursal)
