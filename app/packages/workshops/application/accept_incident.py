import uuid
import logging
from app.packages.workshops.infrastructure.repositories import WorkshopRepository
from app.packages.emergencies.infrastructure.repositories import IncidentRepository
from app.packages.assignment.infrastructure.repositories import AssignmentRepository
from app.packages.emergencies.domain.models import HistorialIncidente
from app.core.exceptions import NotFoundError, ForbiddenError

logger = logging.getLogger(__name__)

class AcceptIncidentUseCase:
    """
    Caso de Uso (CU): Aceptación de Incidente por Taller.
    El administrador del taller acepta la emergencia y asigna un técnico.
    """
    
    def __init__(
        self, 
        workshop_repo: WorkshopRepository, 
        incident_repo: IncidentRepository,
        assignment_repo: AssignmentRepository
    ):
        self.workshop_repo = workshop_repo
        self.incident_repo = incident_repo
        self.assignment_repo = assignment_repo

    async def execute(self, workshop_id: uuid.UUID, incident_id: uuid.UUID, tecnico_id: uuid.UUID):
        # 1. Validar Incidente y Asignación
        incident = await self.incident_repo.get_by_id(incident_id)
        if not incident:
            raise NotFoundError("Incidente no encontrado.")
            
        if incident.id_taller != workshop_id:
            raise ForbiddenError("Este incidente no está asignado a tu taller.")

        # 2. Validar Técnico (debe pertenecer al taller)
        tecnico = await self.workshop_repo.get_technician_by_id(tecnico_id)
        if not tecnico or tecnico.id_taller != workshop_id:
            raise ForbiddenError("El técnico no pertenece a tu taller.")

        # 3. Actualizar la asignación
        assignment = await self.assignment_repo.get_by_incident(incident_id)
        if not assignment:
            raise NotFoundError("No se encontró el registro de asignación.")
        
        assignment.id_tecnico = tecnico_id
        assignment.estado_asignacion = "ACEPTADO"

        # 4. Actualizar estado del incidente
        old_status = incident.estado_incidente
        incident.estado_incidente = "EN_CAMINO"
        
        # 5. Registrar Historial
        historial = HistorialIncidente(
            id_incidente=incident_id,
            incidente_estado_anterior=old_status,
            incidente_estado_nuevo="EN_CAMINO",
            historial_actor=f"TALLER_{workshop_id}",
            fecha=None
        )
        incident.historial.append(historial)

        await self.incident_repo.session.commit()
        
        # 6. Notificar al Cliente (WebSocket + Push)
        try:
            from app.core.notifications import manager
            from app.core.push_notifications import push_service
            
            if incident.vehiculo and incident.vehiculo.propietario:
                user_id = str(incident.vehiculo.id_usuario)
                fcm_token = incident.vehiculo.propietario.fcm_token
                
                msg_text = f"Ayuda en camino. El técnico {tecnico.nombre} ha sido asignado."
                
                # A. WebSocket (App abierta)
                await manager.notify_user(
                    user_id,
                    {
                        "type": "INCIDENT_ACCEPTED",
                        "id": str(incident_id),
                        "message": msg_text,
                        "tecnico": {
                            "nombre": tecnico.nombre,
                            "telefono": tecnico.telefono
                        }
                    }
                )
                
                # B. Push Notification (App cerrada/fondo)
                if fcm_token:
                    import asyncio
                    asyncio.create_task(push_service.send_push_notification(
                        token=fcm_token,
                        title="¡Ayuda en camino!",
                        body=msg_text,
                        data={"incident_id": str(incident_id), "type": "INCIDENT_ACCEPTED"}
                    ))
        except Exception as e:
            logger.error(f"Error al notificar aceptación: {str(e)}")

        return incident
