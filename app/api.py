from fastapi import APIRouter

from app.packages.assignment.presentation.routers import router as assignment_router
from app.packages.admin.presentation.routers import router as admin_router
from app.packages.emergencies.presentation.routers import router as emergencies_router
from app.packages.finance.presentation.routers import router as finance_router
from app.packages.identity.presentation.routers import router as identity_router
from app.packages.monitoring.presentation.routers import router as monitoring_router
from app.packages.quotations.presentation.routers import router as quotations_router
from app.packages.scheduling.presentation.routers import router as scheduling_router
from app.packages.transfers.presentation.routers import router as transfers_router
from app.packages.workshops.presentation.routers import router as workshops_router

api_router = APIRouter()

api_router.include_router(identity_router, prefix="/identity", tags=["Onboarding y Gestion de Identidad"])
api_router.include_router(emergencies_router, prefix="/emergencies", tags=["Gestion de Emergencias"])
api_router.include_router(monitoring_router, prefix="/monitoring", tags=["Monitoreo y Trazabilidad"])
api_router.include_router(assignment_router, prefix="/assignment", tags=["Asignacion Inteligente"])
api_router.include_router(workshops_router, prefix="/workshops", tags=["Operacion de Talleres"])
api_router.include_router(admin_router, prefix="/admin", tags=["Administracion"])
api_router.include_router(finance_router, prefix="/finance", tags=["Finanzas y Monetizacion"])
api_router.include_router(scheduling_router, prefix="/scheduling", tags=["Gestion de Citas (CU29)"])
api_router.include_router(quotations_router, prefix="/quotations", tags=["Cotizaciones (CU27)"])
api_router.include_router(transfers_router, prefix="/transfers", tags=["Traslados de Vehiculos"])
