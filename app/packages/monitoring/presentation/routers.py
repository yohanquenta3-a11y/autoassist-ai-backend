from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.packages.identity.domain.models import Usuario
from app.packages.emergencies.infrastructure.repositories import IncidentRepository
from app.packages.workshops.infrastructure.repositories import WorkshopRepository
from app.packages.emergencies.presentation.schemas import IncidentResponse
from app.packages.monitoring.presentation.schemas import GlobalStatsResponse

router = APIRouter()

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
