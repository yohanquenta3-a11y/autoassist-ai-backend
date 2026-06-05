from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
from typing import List, Optional
import stripe

from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.core.config import settings
from app.packages.identity.domain.models import Usuario
from app.packages.workshops.infrastructure.repositories import WorkshopRepository
from app.packages.emergencies.infrastructure.repositories import IncidentRepository
from app.packages.finance.infrastructure.repositories import FinanceRepository
from app.packages.finance.presentation.schemas import PaymentCreate, PaymentResponse, BillingCreate
from app.packages.finance.application.close_incident import CloseIncidentUseCase
from app.packages.finance.presentation.stripe_webhook import router as webhook_router


stripe.api_key = settings.STRIPE_SECRET_KEY

router = APIRouter()
router.include_router(webhook_router)

@router.post("/emergencies/{incident_id}/pay", response_model=PaymentResponse)
async def process_payment(
    incident_id: uuid.UUID,
    payment_in: PaymentCreate,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """(Fase 5) Registrar el pago final de una emergencia y cerrar el caso."""
    from app.core.exceptions import ForbiddenError
    
    workshop_repo = WorkshopRepository(db)
    incident_repo = IncidentRepository(db)
    finance_repo = FinanceRepository(db)
    
    # 1. Obtener taller del usuario
    taller = await workshop_repo.get_by_admin(current_user.id_usuario)
    if not taller:
        raise ForbiddenError("No eres administrador de un taller.")
        
    # 2. Ejecutar cierre
    use_case = CloseIncidentUseCase(finance_repo, incident_repo)
    pago = await use_case.execute(
        id_taller=taller.id_taller,
        id_incidente=incident_id,
        monto_total=payment_in.monto_total
    )

    # 3. Notificar estado COMPLETADO por WebSockets
    try:
        incident = await incident_repo.get_by_id(incident_id)
        if incident:
            from app.core.notifications import manager as notify_manager
            from app.core.websocket import manager as ws_manager
            
            status_event = {
                "type": "STATUS_UPDATED",
                "data": {
                    "id_incidente": str(incident_id),
                    "estado_anterior": "FINALIZADO",
                    "estado_nuevo": "COMPLETADO",
                    "id_taller": str(incident.id_taller),
                    "id_tecnico": str(incident.id_tecnico) if incident.id_tecnico else None,
                }
            }
            await notify_manager.notify_workshop(str(incident.id_taller), status_event)
            await notify_manager.notify_admins(status_event)
            await notify_manager.notify_user(str(incident.id_usuario_cliente), status_event)
            await ws_manager.broadcast_to_incident(str(incident_id), status_event)
    except Exception:
        pass  # Evitar que un error en WS aborte la transacción de pago

    return pago

@router.post("/emergencies/{incident_id}/payment-intent")
async def create_payment_intent(
    incident_id: uuid.UUID,
    payment_in: PaymentCreate,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Generar un PaymentIntent en Stripe para el pago de la emergencia."""
    from app.core.exceptions import NotFoundError, BadRequestError

    # 1. Validar incidente y taller
    incident_repo = IncidentRepository(db)
    incident = await incident_repo.get_by_id(incident_id)
    if not incident:
        raise NotFoundError("Incidente no encontrado.")
    
    if not incident.id_taller:
        raise BadRequestError("El incidente no tiene un taller asignado.")

    try:
        # Stripe espera el monto en centavos (ej: 10.00 USD -> 1000 centavos)
        amount_cents = int(payment_in.monto_total * 100)
        
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            metadata={
                "incident_id": str(incident_id),
                "id_taller": str(incident.id_taller),
                "monto_total": str(payment_in.monto_total)
            },
            automatic_payment_methods={
                "enabled": True,
            },
        )
        return {"clientSecret": intent.client_secret}
    except Exception as e:
        raise BadRequestError(f"Error al crear el PaymentIntent de Stripe: {str(e)}")

@router.get("/reports", response_model=List[PaymentResponse])
async def get_financial_reports(
    workshop_id: Optional[uuid.UUID] = Query(None),
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """(CU19/CU25) Obtener reportes de pagos. Multi-tenant."""
    from sqlalchemy import select
    from app.packages.finance.domain.models import Pago
    
    query = select(Pago)
    
    # Lógica de Seguridad Multi-tenant
    if current_user.rol_nombre == "admin_taller":
        workshop_repo = WorkshopRepository(db)
        workshop = await workshop_repo.get_by_admin(current_user.id_usuario)
        if not workshop:
            return []
        query = query.where(Pago.id_taller == workshop.id_taller)
    elif current_user.rol_nombre == "superadmin":
        if workshop_id:
            query = query.where(Pago.id_taller == workshop_id)
    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Acceso denegado")
        
    result = await db.execute(query.order_by(Pago.fecha_pago.desc()))
    return result.scalars().all()


@router.post("/emergencies/{incident_id}/billing", response_model=PaymentResponse)
async def register_billing(
    incident_id: uuid.UUID,
    billing_in: BillingCreate,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """(Admin Web / Técnico) Registrar el cobro/precio final de un incidente finalizado por el técnico o en atención."""
    from app.core.exceptions import NotFoundError, ForbiddenError, BadRequestError
    from app.packages.finance.domain.models import Pago
    from app.packages.emergencies.domain.models import HistorialIncidente
    from decimal import Decimal
    from sqlalchemy.future import select
    
    # 1. Validar permisos de rol
    if current_user.rol_nombre not in ("admin_taller", "superadmin", "tecnico"):
        raise ForbiddenError("No tienes permisos para registrar el cobro de este incidente.")
        
    incident_repo = IncidentRepository(db)
    incident = await incident_repo.get_by_id(incident_id)
    if not incident:
        raise NotFoundError("Incidente no encontrado.")
        
    # 2. Validaciones estrictas de datos de cobro
    if billing_in.mano_de_obra is not None and billing_in.mano_de_obra < 0:
        raise BadRequestError("El costo de mano de obra no puede ser negativo.")
    if billing_in.repuestos is not None and billing_in.repuestos < 0:
        raise BadRequestError("El costo de repuestos no puede ser negativo.")
    if billing_in.monto_total <= 0:
        raise BadRequestError("El monto total a cobrar debe ser mayor a 0.")
        
    expected_total = (billing_in.mano_de_obra or Decimal("0")) + (billing_in.repuestos or Decimal("0"))
    if billing_in.monto_total != expected_total:
        raise BadRequestError("El monto total a cobrar debe ser exactamente la suma de mano de obra y repuestos.")
        
    # 3. Validar alcance y estados permitidos según el rol
    if current_user.rol_nombre == "tecnico":
        from app.packages.workshops.domain.models import Tecnico
        res = await db.execute(select(Tecnico).where(Tecnico.id_usuario == current_user.id_usuario))
        tecnico = res.scalars().first()
        if not tecnico or incident.id_tecnico != tecnico.id_tecnico:
            raise ForbiddenError("No puedes facturar un incidente que no tienes asignado.")
            
        if incident.estado_incidente in ("CANCELADO", "COMPLETADO", "TECNICO_RECHAZADO"):
            raise BadRequestError(f"No se puede registrar el cobro en un incidente con estado {incident.estado_incidente}.")
            
        if incident.estado_incidente == "TECNICO_EN_SITIO":
            raise BadRequestError("El técnico debe ser verificado por el cliente antes de registrar el cobro.")
            
    elif current_user.rol_nombre == "admin_taller":
        workshop_repo = WorkshopRepository(db)
        taller = await workshop_repo.get_by_admin(current_user.id_usuario)
        if not taller or incident.id_taller != taller.id_taller:
            raise ForbiddenError("No puedes facturar un incidente que no pertenece a tu taller.")
            
    if incident.estado_incidente not in ("FINALIZADO", "EN_ATENCION"):
        raise BadRequestError("El incidente debe estar en estado FINALIZADO o EN_ATENCION para ser facturado.")
        
    # 4. Buscar si ya existe un pago
    finance_repo = FinanceRepository(db)
    pago = await finance_repo.get_payment_by_incident(incident_id)
    
    comision = billing_in.monto_total * Decimal("0.10")
    
    if not pago:
        pago = Pago(
            id_incidente=incident_id,
            id_taller=incident.id_taller,
            monto=billing_in.monto_total,
            monto_comision=comision,
            estado_pago="PENDIENTE",
            mano_de_obra=billing_in.mano_de_obra,
            repuestos=billing_in.repuestos,
            observaciones=billing_in.observaciones
        )
        db.add(pago)
    else:
        pago.monto = billing_in.monto_total
        pago.monto_comision = comision
        pago.mano_de_obra = billing_in.mano_de_obra
        pago.repuestos = billing_in.repuestos
        pago.observaciones = billing_in.observaciones
        pago.estado_pago = "PENDIENTE"
        
    # Cambiar estado del incidente a FINALIZADO si no lo estaba ya
    estado_anterior = incident.estado_incidente
    if incident.estado_incidente != "FINALIZADO":
        incident.estado_incidente = "FINALIZADO"
        
    # Si el técnico está registrando la facturación, liberarlo (hacerlo disponible para nuevas asignaciones)
    if incident.tecnico:
        incident.tecnico.estado = True
        
    historial = HistorialIncidente(
        id_incidente=incident_id,
        incidente_estado_anterior=estado_anterior,
        incidente_estado_nuevo="FINALIZADO",
        historial_actor=f"{current_user.rol_nombre.upper()}:{current_user.nombre}",
        fecha=None
    )
    incident.historial.append(historial)
        
    await db.commit()
    await db.refresh(pago)
    
    # 3. Emitir WebSocket de actualización
    try:
        from app.core.notifications import manager as notify_manager
        from app.core.websocket import manager as ws_manager
        
        status_event = {
            "type": "STATUS_UPDATED",
            "data": {
                "id_incidente": str(incident_id),
                "estado_anterior": estado_anterior,
                "estado_nuevo": "FINALIZADO",
                "id_taller": str(incident.id_taller),
                "id_tecnico": str(incident.id_tecnico) if incident.id_tecnico else None,
                "monto_total": float(pago.monto),
                "mano_de_obra": float(pago.mano_de_obra) if pago.mano_de_obra else None,
                "repuestos": float(pago.repuestos) if pago.repuestos else None,
                "observaciones": pago.observaciones
            }
        }
        await notify_manager.notify_workshop(str(incident.id_taller), status_event)
        await notify_manager.notify_admins(status_event)
        await notify_manager.notify_user(str(incident.id_usuario_cliente), status_event)
        await ws_manager.broadcast_to_incident(str(incident_id), status_event)
    except Exception:
        pass
        
    return pago


@router.post("/emergencies/{incident_id}/mock-payment-success")
async def mock_payment_success(
    incident_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """(Fase 5 - Simulación) Procesar el pago simulado desde la app móvil del cliente para completar el incidente."""
    from app.core.exceptions import NotFoundError, BadRequestError
    from app.packages.emergencies.infrastructure.repositories import IncidentRepository
    from app.packages.finance.infrastructure.repositories import FinanceRepository
    from app.packages.emergencies.domain.models import HistorialIncidente
    from app.packages.workshops.domain.models import Tecnico
    from sqlalchemy.future import select
    from datetime import datetime

    incident_repo = IncidentRepository(db)
    finance_repo = FinanceRepository(db)

    # 1. Obtener incidente
    incident = await incident_repo.get_by_id(incident_id)
    if not incident:
        raise NotFoundError("Incidente no encontrado.")

    # 2. Validar que esté en estado FINALIZADO (o COMPLETADO para idempotencia)
    if incident.estado_incidente == "COMPLETADO":
        pago = await finance_repo.get_payment_by_incident(incident_id)
        return {
            "status": "success",
            "message": "El incidente ya se encuentra completado/pagado.",
            "id_incidente": str(incident_id),
            "monto": float(pago.monto) if pago else 0.0
        }

    if incident.estado_incidente != "FINALIZADO":
        raise BadRequestError(f"El incidente debe estar en estado FINALIZADO para procesar el pago. Estado actual: {incident.estado_incidente}")

    # 3. Validar que exista cobro registrado (monto > 0)
    pago = await finance_repo.get_payment_by_incident(incident_id)
    if not pago or pago.monto <= 0:
        raise BadRequestError("No se ha registrado un cobro válido para este incidente.")

    # 4. Actualizar el pago a PAGADO
    pago.estado_pago = "PAGADO"
    pago.fecha_pago = datetime.utcnow()

    # 5. Cambiar el estado del incidente a COMPLETADO
    estado_anterior = incident.estado_incidente
    incident.estado_incidente = "COMPLETADO"

    # 6. Liberar al técnico asignado (hacerlo disponible para nuevas emergencias)
    if incident.id_tecnico:
        result = await db.execute(
            select(Tecnico).where(Tecnico.id_tecnico == incident.id_tecnico)
        )
        tecnico = result.scalar_one_or_none()
        if tecnico:
            tecnico.estado = True
            tecnico.estado_operativo = "DISPONIBLE"

    # 7. Registrar en el historial de incidentes
    historial = HistorialIncidente(
        id_incidente=incident_id,
        incidente_estado_anterior=estado_anterior,
        incidente_estado_nuevo="COMPLETADO",
        historial_actor=f"CLIENTE:{current_user.nombre}",
        fecha=None
    )
    incident.historial.append(historial)

    await db.commit()
    await db.refresh(pago)

    # 8. Notificar el estado COMPLETADO a la web (Angular) y móvil (Flutter) mediante WebSocket
    try:
        from app.core.notifications import manager as notify_manager
        from app.core.websocket import manager as ws_manager

        status_event = {
            "type": "STATUS_UPDATED",
            "data": {
                "id_incidente": str(incident_id),
                "estado_anterior": estado_anterior,
                "estado_nuevo": "COMPLETADO",
                "id_taller": str(incident.id_taller),
                "id_tecnico": str(incident.id_tecnico) if incident.id_tecnico else None,
                "monto_total": float(pago.monto),
                "metodo_pago": "TARJETA_SIMULADA",
                "detalle": "Pago simulado exitoso desde la app del cliente"
            }
        }
        await notify_manager.notify_workshop(str(incident.id_taller), status_event)
        await notify_manager.notify_admins(status_event)
        await notify_manager.notify_user(str(incident.id_usuario_cliente), status_event)
        await ws_manager.broadcast_to_incident(str(incident_id), status_event)
    except Exception:
        pass

    return {
        "status": "success",
        "message": "Pago simulado procesado correctamente. Incidente completado.",
        "id_incidente": str(incident_id),
        "monto": float(pago.monto)
    }
