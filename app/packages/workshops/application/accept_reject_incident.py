import uuid
import logging
from app.packages.emergencies.infrastructure.repositories import IncidentRepository
from app.packages.assignment.application.match_workshop import MatchWorkshopUseCase
from app.packages.assignment.infrastructure.repositories import AssignmentRepository
from app.packages.emergencies.domain.models import HistorialIncidente, VerificacionTecnico
from app.core.exceptions import ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)

class AcceptRejectIncidentUseCase:
    def __init__(self, incident_repo: IncidentRepository, assignment_repo: AssignmentRepository, workshop_repo=None):
        self.incident_repo = incident_repo
        self.assignment_repo = assignment_repo
        self.workshop_repo = workshop_repo
        self.match_use_case = MatchWorkshopUseCase(assignment_repo, incident_repo)

    async def accept(self, id_taller: uuid.UUID, id_incidente: uuid.UUID, id_tecnico: uuid.UUID, actor_nombre: str):
        incidente = await self.incident_repo.get_by_id(id_incidente)
        if not incidente:
            raise NotFoundError("Incidente no encontrado.")
        
        if incidente.id_taller != id_taller:
            raise ForbiddenError("Este incidente no está asignado a tu taller.")

        # Marcar al técnico como ocupado y en camino usando el id_tecnico directo
        if self.workshop_repo:
            tecnico = await self.workshop_repo.get_technician_by_id(id_tecnico)
            if tecnico:
                tecnico.estado = False
                tecnico.estado_operativo = "EN_CAMINO"

        # Actualizar el estado de la asignación a ACEPTADO
        id_asignacion = None
        if self.assignment_repo:
            assignment = await self.assignment_repo.get_by_incident(id_incidente)
            if assignment:
                assignment.estado_asignacion = "ACEPTADO"
                assignment.id_tecnico = id_tecnico
                id_asignacion = assignment.id_asignacion

        # Generar código de verificación segura del técnico (PIN de 6 dígitos)
        import secrets
        verification_code = "".join(secrets.choice("0123456789") for _ in range(6))

        verificacion = VerificacionTecnico(
            id_incidente=id_incidente,
            id_asignacion=id_asignacion,
            id_tecnico=id_tecnico,
            metodo_verificacion="PIN",
            codigo_verificacion=verification_code,
            estado_verificacion="PENDIENTE",
            resultado="PENDIENTE",
            intentos=0
        )
        self.incident_repo.session.add(verificacion)

        estado_anterior = incidente.estado_incidente
        incidente.estado_incidente = "EN_CAMINO"
        incidente.id_tecnico = id_tecnico

        historial = HistorialIncidente(
            id_incidente=id_incidente,
            incidente_estado_anterior=estado_anterior,
            incidente_estado_nuevo="EN_CAMINO",
            historial_actor=actor_nombre
        )
        incidente.historial.append(historial)
        
        await self.incident_repo.session.commit()
        return incidente

    async def reject(self, id_taller: uuid.UUID, id_incidente: uuid.UUID, actor_nombre: str):
        incidente = await self.incident_repo.get_by_id(id_incidente)
        if not incidente:
            raise NotFoundError("Incidente no encontrado.")
        
        if incidente.id_taller != id_taller:
            raise ForbiddenError("No puedes rechazar un incidente que no tienes asignado.")

        # 1. Registrar el rechazo en el historial
        estado_anterior = incidente.estado_incidente
        historial = HistorialIncidente(
            id_incidente=id_incidente,
            incidente_estado_anterior=estado_anterior,
            incidente_estado_nuevo="RECHAZADO_POR_TALLER",
            historial_actor=actor_nombre
        )
        incidente.historial.append(historial)

        # 2. Obtener lista de talleres que ya rechazaron para no repetir
        # Buscamos en el historial quiénes han sido actores de "RECHAZADO_POR_TALLER"
        # Para este ciclo simplificado, solo excluiremos al taller actual.
        # En una versión PRO, buscaríamos todos los IDs en el historial.
        rejected_ids = [id_taller]

        # 3. Limpiar taller actual y buscar siguiente
        incidente.id_taller = None
        incidente.estado_incidente = "BUSCANDO_REASIGNACION"
        await self.incident_repo.session.commit()

        # 4. Disparar re-asignación
        logger.info(f"Disparando re-asignación para {id_incidente} excluyendo {rejected_ids}")
        return await self.match_use_case.execute(id_incidente, exclude_ids=rejected_ids)
