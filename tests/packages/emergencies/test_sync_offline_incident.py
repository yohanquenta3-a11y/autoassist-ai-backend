import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BadRequestError, ForbiddenError
from app.packages.emergencies.application.sync_offline_incident import SyncOfflineIncidentUseCase
from app.packages.emergencies.domain.models import Incidente
from app.packages.emergencies.presentation.schemas import OfflineIncidentSyncRequest
from app.packages.identity.domain.models import Usuario, Vehiculo
import app.packages.workshops.domain.models  # noqa: F401


@pytest.mark.asyncio
async def test_sync_offline_incident_returns_existing_when_identifier_repeats():
    repo = AsyncMock()
    user_repo = AsyncMock()
    service = SyncOfflineIncidentUseCase(repo, user_repo)

    user = MagicMock(spec=Usuario)
    user.id_usuario = uuid.uuid4()
    user.nombre = "Cliente"

    vehicle = MagicMock(spec=Vehiculo)
    vehicle.id_usuario = user.id_usuario
    vehicle.id_vehiculo = uuid.uuid4()

    existing = MagicMock(spec=Incidente)
    existing.id_incidente = uuid.uuid4()
    existing.estado_incidente = "ANALIZADO"

    user_repo.get_vehicle_by_id.return_value = vehicle
    repo.get_by_local_identifier.return_value = existing

    payload = OfflineIncidentSyncRequest(
        identificador_local="offline-12345678",
        id_vehiculo=vehicle.id_vehiculo,
        descripcion="Bateria descargada",
        latitud=-17.7833,
        longitud=-63.1821,
    )

    incident, duplicated = await service.execute(user, payload)

    assert incident is existing
    assert duplicated is True
    repo.create_incident.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_offline_incident_creates_new_incident():
    repo = AsyncMock()
    user_repo = AsyncMock()
    service = SyncOfflineIncidentUseCase(repo, user_repo)

    user = MagicMock(spec=Usuario)
    user.id_usuario = uuid.uuid4()
    user.nombre = "Cliente"

    vehicle = MagicMock(spec=Vehiculo)
    vehicle.id_usuario = user.id_usuario
    vehicle.id_vehiculo = uuid.uuid4()

    created = MagicMock(spec=Incidente)
    created.id_incidente = uuid.uuid4()
    created.estado_incidente = "PENDIENTE"

    user_repo.get_vehicle_by_id.return_value = vehicle
    repo.get_by_local_identifier.return_value = None
    repo.get_active_by_user.return_value = None
    repo.create_incident.return_value = created
    repo.get_by_id.return_value = created

    payload = OfflineIncidentSyncRequest(
        identificador_local="offline-abcdefgh",
        id_vehiculo=vehicle.id_vehiculo,
        descripcion="Motor recalentado",
        telefono="70000000",
        latitud=-17.8,
        longitud=-63.18,
        prioridad="CRITICA",
    )

    incident, duplicated = await service.execute(user, payload)

    assert incident is created
    assert duplicated is False
    repo.create_incident.assert_awaited_once()
    repo.add_history.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_offline_incident_rejects_foreign_vehicle():
    repo = AsyncMock()
    user_repo = AsyncMock()
    service = SyncOfflineIncidentUseCase(repo, user_repo)

    user = MagicMock(spec=Usuario)
    user.id_usuario = uuid.uuid4()

    vehicle = MagicMock(spec=Vehiculo)
    vehicle.id_usuario = uuid.uuid4()
    vehicle.id_vehiculo = uuid.uuid4()

    user_repo.get_vehicle_by_id.return_value = vehicle

    payload = OfflineIncidentSyncRequest(
        identificador_local="offline-foreign1",
        id_vehiculo=vehicle.id_vehiculo,
        descripcion="Prueba",
        latitud=-17.8,
        longitud=-63.18,
    )

    with pytest.raises(ForbiddenError):
        await service.execute(user, payload)


@pytest.mark.asyncio
async def test_sync_offline_incident_rejects_when_other_active_incident_exists():
    repo = AsyncMock()
    user_repo = AsyncMock()
    service = SyncOfflineIncidentUseCase(repo, user_repo)

    user = MagicMock(spec=Usuario)
    user.id_usuario = uuid.uuid4()

    vehicle = MagicMock(spec=Vehiculo)
    vehicle.id_usuario = user.id_usuario
    vehicle.id_vehiculo = uuid.uuid4()

    active = MagicMock(spec=Incidente)
    active.id_incidente = uuid.uuid4()

    user_repo.get_vehicle_by_id.return_value = vehicle
    repo.get_by_local_identifier.return_value = None
    repo.get_active_by_user.return_value = active

    payload = OfflineIncidentSyncRequest(
        identificador_local="offline-active1",
        id_vehiculo=vehicle.id_vehiculo,
        descripcion="Prueba activa",
        latitud=-17.8,
        longitud=-63.18,
    )

    with pytest.raises(BadRequestError):
        await service.execute(user, payload)
