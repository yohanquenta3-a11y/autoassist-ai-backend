from datetime import datetime, time
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.packages.identity.domain.models import Usuario
from app.packages.emergencies.infrastructure.repositories import IncidentRepository
from app.packages.monitoring.application.operational_metrics import (
    build_operational_dashboard,
    build_sla_alerts,
    resolve_operational_scope,
)
from app.packages.monitoring.infrastructure.operational_metrics_repository import OperationalMetricsRepository
from app.packages.monitoring.presentation.schemas import (
    GlobalStatsResponse,
    OperationalDashboardResponse,
    SlaAlertsResponse,
)
from app.packages.workshops.dependencies import get_selected_branch_id
from app.packages.emergencies.presentation.schemas import IncidentResponse

router = APIRouter()


def _parse_date_start(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.combine(datetime.fromisoformat(value).date(), time.min)


def _parse_date_end(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.combine(datetime.fromisoformat(value).date(), time.max)

@router.get("/{incident_id}/tracking", response_model=IncidentResponse)
async def track_incident(
    incident_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """(Fase 4) Consultar el estado en tiempo real de una emergencia para el cliente."""
    from app.core.exceptions import NotFoundError, ForbiddenError
    incident_repo = IncidentRepository(db)
    
    incidente = await incident_repo.get_by_id(incident_id)
    if not incidente:
        raise NotFoundError("Incidente no encontrado.")
        
    # VALIDACIÓN SAAS: Verificar que el incidente pertenece al usuario logueado
    if incidente.id_usuario_cliente != current_user.id_usuario:
        raise ForbiddenError("No tienes permiso para ver el estado de esta emergencia.")
    
    return incidente

@router.get("/stats", response_model=GlobalStatsResponse)
async def get_global_stats(
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """(CU22) Centro de Mando: Estadísticas globales para el SuperAdmin."""
    from sqlalchemy import func, select
    from app.packages.identity.domain.models import ROL_SUPERADMIN
    from app.packages.workshops.domain.models import Taller
    from app.packages.emergencies.domain.models import Incidente
    from app.packages.finance.domain.models import Pago
    from app.core.exceptions import ForbiddenError

    if current_user.rol_nombre != ROL_SUPERADMIN:
        raise ForbiddenError("Acceso exclusivo para SuperAdmin.")

    # 1. Total Talleres
    total_talleres = await db.scalar(select(func.count(Taller.id_taller)))
    
    # 2. Total Incidentes
    total_incidentes = await db.scalar(select(func.count(Incidente.id_incidente)))
    
    # 3. Total Comisiones (Suma de la tabla Pago)
    total_comisiones = await db.scalar(select(func.sum(Pago.monto_comision))) or 0
    
    # 4. Emergencias Activas (Que no estén en estado FINALIZADO)
    emergencias_activas = await db.scalar(
        select(func.count(Incidente.id_incidente))
        .where(Incidente.estado_incidente != "FINALIZADO")
    )

    return {
        "total_talleres": total_talleres,
        "total_incidentes": total_incidentes,
        "total_comisiones": total_comisiones,
        "emergencias_activas": emergencias_activas
    }


@router.get("/operational/dashboard", response_model=OperationalDashboardResponse)
async def get_operational_dashboard(
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    id_taller: Optional[UUID] = Query(None),
    id_sucursal: Optional[UUID] = Query(None),
    estado: Optional[str] = Query(None),
    prioridad: Optional[str] = Query(None),
    origen: Optional[str] = Query(None),
):
    repository = OperationalMetricsRepository(db)
    scope = await resolve_operational_scope(
        repository=repository,
        current_user=current_user,
        requested_taller_id=id_taller,
        selected_branch_id=selected_branch_id,
        requested_branch_id=id_sucursal,
    )
    return await build_operational_dashboard(
        repository=repository,
        scope=scope,
        date_from=_parse_date_start(date_from),
        date_to=_parse_date_end(date_to),
        estado=estado,
        prioridad=prioridad,
        origen=origen,
    )


@router.get("/operational/sla-alerts", response_model=SlaAlertsResponse)
async def get_operational_sla_alerts(
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    id_taller: Optional[UUID] = Query(None),
    id_sucursal: Optional[UUID] = Query(None),
    prioridad: Optional[str] = Query(None),
    tipo_alerta: Optional[str] = Query(None),
    sla_status: Optional[str] = Query(None),
    estado_incidente: Optional[str] = Query(None),
):
    repository = OperationalMetricsRepository(db)
    scope = await resolve_operational_scope(
        repository=repository,
        current_user=current_user,
        requested_taller_id=id_taller,
        selected_branch_id=selected_branch_id,
        requested_branch_id=id_sucursal,
    )
    return await build_sla_alerts(
        repository=repository,
        scope=scope,
        date_from=_parse_date_start(date_from),
        date_to=_parse_date_end(date_to),
        prioridad=prioridad,
        tipo_alerta=tipo_alerta,
        sla_status=sla_status,
        estado_incidente=estado_incidente,
    )
