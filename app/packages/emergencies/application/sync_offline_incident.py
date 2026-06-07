import uuid
from datetime import datetime

from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.packages.emergencies.domain.models import HistorialIncidente, Incidente
from app.packages.emergencies.infrastructure.repositories import IncidentRepository
from app.packages.emergencies.presentation.schemas import OfflineIncidentSyncRequest
from app.packages.identity.domain.models import Usuario
from app.packages.identity.infrastructure.repositories import UserRepository


class SyncOfflineIncidentUseCase:
    def __init__(
        self,
        incident_repository: IncidentRepository,
        user_repository: UserRepository,
    ):
        self.incident_repository = incident_repository
        self.user_repository = user_repository

    async def execute(
        self,
        current_user: Usuario,
        payload: OfflineIncidentSyncRequest,
    ) -> tuple[Incidente, bool]:
        vehicle = await self.user_repository.get_vehicle_by_id(
            uuid.UUID(str(payload.id_vehiculo))
        )
        if not vehicle:
            raise NotFoundError("Vehiculo no encontrado.")

        if vehicle.id_usuario != current_user.id_usuario:
            raise ForbiddenError("El vehiculo no pertenece al usuario autenticado.")

        existing = await self.incident_repository.get_by_local_identifier(
            current_user.id_usuario,
            payload.identificador_local,
        )
        if existing:
            return existing, True

        active_incident = await self.incident_repository.get_active_by_user(current_user.id_usuario)
        if active_incident:
            raise BadRequestError(
                "Ya existe una emergencia activa para este usuario. Finalizala o cancelala antes de sincronizar otra."
            )

        point_wkt = f"POINT({payload.longitud} {payload.latitud})"

        incident = Incidente(
            id_vehiculo=vehicle.id_vehiculo,
            id_usuario_cliente=current_user.id_usuario,
            descripcion=payload.descripcion,
            telefono=payload.telefono,
            ubicacion_emergencia=point_wkt,
            estado_incidente="PENDIENTE",
            prioridad_incidente=payload.prioridad or "CRITICA",
            identificador_local=payload.identificador_local,
            origen_registro="OFFLINE_MOVIL",
            fecha_sincronizacion=datetime.utcnow(),
        )

        created = await self.incident_repository.create_incident(incident)

        history = HistorialIncidente(
            id_incidente=created.id_incidente,
            incidente_estado_anterior=None,
            incidente_estado_nuevo="PENDIENTE",
            historial_actor=f"CLIENTE:{current_user.nombre} (Sync Offline)",
        )
        await self.incident_repository.add_history(history)

        created = await self.incident_repository.get_by_id(created.id_incidente)
        return created, False
