import uuid
import logging
from app.packages.assignment.infrastructure.repositories import AssignmentRepository
from app.packages.emergencies.infrastructure.repositories import IncidentRepository
from app.packages.assignment.domain.models import AsignacionIncidente
from app.packages.emergencies.domain.models import HistorialIncidente

logger = logging.getLogger(__name__)

class MatchWorkshopUseCase:
    """
    Caso de Uso (CU): Asignación Automática de Taller.
    Busca el taller más cercano al incidente y crea la asignación.
    """
    
    def __init__(self, assignment_repo: AssignmentRepository, incident_repo: IncidentRepository):
        self.assignment_repo = assignment_repo
        self.incident_repo = incident_repo

    async def execute(self, id_incidente: uuid.UUID, exclude_ids: list[uuid.UUID] = None):
        # 1. Obtener el incidente analizado
        incidente = await self.incident_repo.get_by_id(id_incidente)
        if not incidente or not incidente.ubicacion_emergencia:
            logger.warning(f"Incidente {id_incidente} no apto para asignación (falta ubicación)")
            return None

        logger.info(f"Buscando taller para incidente {id_incidente} en {incidente.ubicacion_emergencia} (Excluyendo: {exclude_ids})")

        # 2. Buscar talleres cercanos (Radio 15km)
        nearby = await self.assignment_repo.get_nearby_workshops(
            point=incidente.ubicacion_emergencia,
            radius_km=15.0,
            limit=1,
            exclude_ids=exclude_ids
        )

        if not nearby:
            logger.error(f"No se encontraron talleres disponibles cerca del incidente {id_incidente}")
            incidente.estado_incidente = "SIN_TALLER_DISPONIBLE"
            incidente.id_taller = None # Limpiamos si no hay nada
            await self.incident_repo.session.commit()
            return None

        # Tomamos el primero (el más cercano disponible)
        best_taller, distance_meters = nearby[0]
        logger.info(f"Taller encontrado: {best_taller.nombre} a {distance_meters:.2f}m")
            
        # 3. Crear asignación
        new_assignment = AsignacionIncidente(
            id_incidente=id_incidente,
            id_taller=best_taller.id_taller,
            id_tecnico=None,
            estado_asignacion="PENDIENTE_ACEPTACION",
            distancia_km=distance_meters / 1000.0
        )
        
        # Nota: Mi modelo AsignacionIncidente actualmente apunta a id_tecnico.
        # En una lógica real, tal vez necesitemos id_taller en AsignacionIncidente, 
        # o que el primer registro sea al AdministradorTaller.
        # Por ahora, vinculamos el incidente al taller directamente.
        
        incidente.id_taller = best_taller.id_taller
        incidente.estado_incidente = "TALLER_ASIGNADO"
        
        # Historial
        historial = HistorialIncidente(
            id_incidente=id_incidente,
            incidente_estado_anterior="ANALIZADO",
            incidente_estado_nuevo="TALLER_ASIGNADO",
            historial_actor="MATCH_ENGINE_AUTO",
            fecha=None
        )
        incidente.historial.append(historial)

        await self.assignment_repo.create_assignment(new_assignment)
        await self.incident_repo.session.commit()
        
        # 4. Notificación Real-time (WebSocket + Push)
        try:
            from app.core.notifications import manager
            from app.core.push_notifications import push_service
            
            # A. Notificar al Taller (Dashboard Web + Mobile Push para Admins)
            await manager.notify_workshop(
                str(best_taller.id_taller), 
                {"type": "NEW_ASSIGNMENT", "id": str(id_incidente)}
            )
            
            for admin in best_taller.administradores:
                if admin.usuario and admin.usuario.fcm_token:
                    import asyncio
                    asyncio.create_task(push_service.send_push_notification(
                        token=admin.usuario.fcm_token,
                        title="¡Nuevo Incidente Asignado!",
                        body=f"Un nuevo incidente requiere tu atención: {incidente.resumen_ia or 'Sin descripción'}",
                        data={"type": "NEW_ASSIGNMENT", "incident_id": str(id_incidente)}
                    ))

            # B. Notificar al Cliente (Dueño del vehículo)
            if incidente.vehiculo and incidente.vehiculo.propietario:
                user_id = str(incidente.vehiculo.id_usuario)
                fcm_token = incidente.vehiculo.propietario.fcm_token
                
                # WebSocket
                await manager.notify_user(
                    user_id,
                    {
                        "type": "WORKSHOP_ASSIGNED", 
                        "id": str(id_incidente),
                        "workshop_name": best_taller.nombre
                    }
                )
                
                # Push
                if fcm_token:
                    import asyncio
                    asyncio.create_task(push_service.send_push_notification(
                        token=fcm_token,
                        title="Taller Asignado",
                        body=f"Tu solicitud ha sido enviada a {best_taller.nombre}. Esperando respuesta.",
                        data={"type": "WORKSHOP_ASSIGNED", "incident_id": str(id_incidente)}
                    ))

            # C. Al SuperAdmin (WebSocket)
            await manager.notify_admins({"type": "NEW_ASSIGNMENT", "id": str(id_incidente)})
        except Exception as e:
            logger.error(f"Error al notificar asignación: {str(e)}")

        return new_assignment
