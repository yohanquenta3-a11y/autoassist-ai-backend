import uuid
from app.packages.emergencies.infrastructure.repositories import IncidentRepository
from app.packages.emergencies.presentation.schemas import IncidentCreate
from app.packages.emergencies.domain.models import Incidente, HistorialIncidente
from app.packages.identity.domain.models import Usuario
from app.packages.identity.infrastructure.repositories import UserRepository
from app.core.exceptions import ForbiddenError, NotFoundError


class CreateIncidentUseCase:
    def __init__(
        self,
        incident_repository: IncidentRepository,
        user_repository: UserRepository
    ):
        self.incident_repository = incident_repository
        self.user_repository = user_repository

    async def execute(self, current_user: Usuario, incident_in: IncidentCreate) -> Incidente:
        """(CU5) Reportar una emergencia: valida que el vehículo pertenece al cliente y crea el ticket en PENDIENTE."""
        # Validar que el vehículo existe y pertenece al usuario
        vehicle = await self.user_repository.get_vehicle_by_id(
            uuid.UUID(str(incident_in.id_vehiculo))
        )
        if not vehicle:
            raise NotFoundError("Vehículo no encontrado.")

        if vehicle.id_usuario != current_user.id_usuario:
            raise ForbiddenError("El vehículo no pertenece al usuario autenticado.")

        # Crear coordenada WKT para PostGIS (solo si se envía ubicación)
        point_wkt = None
        if incident_in.latitud is not None and incident_in.longitud is not None:
            point_wkt = f"POINT({incident_in.longitud} {incident_in.latitud})"

        new_incident = Incidente(
            id_vehiculo=vehicle.id_vehiculo,
            id_usuario_cliente=current_user.id_usuario,
            descripcion=incident_in.descripcion,
            telefono=incident_in.telefono,
            ubicacion_emergencia=point_wkt,
            estado_incidente="PENDIENTE",
            prioridad_incidente=incident_in.prioridad or "MEDIA",
        )

        incidente_creado = await self.incident_repository.create_incident(new_incident)

        # Registrar el primer evento de historial
        historial = HistorialIncidente(
            id_incidente=incidente_creado.id_incidente,
            incidente_estado_anterior=None,
            incidente_estado_nuevo="PENDIENTE",
            historial_actor=current_user.nombre
        )
        await self.incident_repository.add_history(historial)

        return incidente_creado
