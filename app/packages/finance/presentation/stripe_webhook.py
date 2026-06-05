import logging
from decimal import Decimal
import uuid
import stripe
import asyncio
from fastapi import APIRouter, Request, Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.notifications import manager
from app.core.push_notifications import push_service
from app.packages.finance.infrastructure.repositories import FinanceRepository
from app.packages.emergencies.infrastructure.repositories import IncidentRepository
from app.packages.finance.application.close_incident import CloseIncidentUseCase

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/stripe-webhooks")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Webhook de Stripe para recibir confirmaciones de pago asíncronas.
    Verifica la firma y ejecuta el cierre de incidente en base de datos.
    """
    if not stripe_signature:
        logger.error("Signature header missing in Stripe webhook request")
        raise HTTPException(status_code=400, detail="Missing signature header")

    payload = await request.body()
    
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        logger.error(f"Invalid payload: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid signature: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    logger.info(f"Stripe Webhook Event Received: {event['type']}")

    if event["type"] == "payment_intent.succeeded":
        payment_intent = event["data"]["object"]
        metadata = payment_intent.get("metadata", {})
        
        incident_id_str = metadata.get("incident_id")
        id_taller_str = metadata.get("id_taller")
        monto_total_str = metadata.get("monto_total")

        if not incident_id_str or not id_taller_str or not monto_total_str:
            logger.error("Missing metadata in PaymentIntent object for closing incident")
            return {"status": "ignored", "reason": "missing_metadata"}

        try:
            incident_id = uuid.UUID(incident_id_str)
            id_taller = uuid.UUID(id_taller_str)
            monto_total = Decimal(monto_total_str)
            
            logger.info(f"Processing payment confirmation for incident {incident_id} of workshop {id_taller} with amount {monto_total}")
            
            finance_repo = FinanceRepository(db)
            incident_repo = IncidentRepository(db)
            
            use_case = CloseIncidentUseCase(finance_repo, incident_repo)
            await use_case.execute(
                id_taller=id_taller,
                id_incidente=incident_id,
                monto_total=monto_total
            )
            logger.info(f"Successfully closed incident {incident_id} through webhook")

            # Recuperar el incidente para notificar al conductor
            incident = await incident_repo.get_by_id(incident_id)
            if incident and incident.vehiculo:
                user_id = str(incident.vehiculo.id_usuario)
                
                # A. WebSocket
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
                from app.core.websocket import manager as ws_manager
                await manager.notify_user(user_id, status_event)
                await manager.notify_user(user_id, {
                    "type": "PAYMENT_CONFIRMED",
                    "incident_id": str(incident_id),
                    "status": "COMPLETADO"
                })
                await manager.notify_workshop(str(incident.id_taller), status_event)
                await manager.notify_admins(status_event)
                await ws_manager.broadcast_to_incident(str(incident_id), status_event)
                
                # B. Push Notification
                fcm_token = incident.vehiculo.propietario.fcm_token if incident.vehiculo.propietario else None
                if fcm_token:
                    logger.info(f"📲 PUSH: Notificando pago confirmado al conductor...")
                    asyncio.create_task(push_service.send_push_notification(
                        token=fcm_token,
                        title="Pago Exitoso",
                        body="Tu pago ha sido confirmado. ¡Gracias por usar Smart Mechanic!",
                        data={"type": "PAYMENT_CONFIRMED", "incident_id": str(incident_id)}
                    ))
            
        except Exception as e:
            logger.error(f"Error processing close incident: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Internal database error: {str(e)}")

    return {"status": "success"}
