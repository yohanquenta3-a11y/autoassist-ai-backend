import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from app.packages.assignment.application.match_workshop import MatchWorkshopUseCase
from app.packages.emergencies.domain.models import Incidente
from app.packages.workshops.domain.models import Taller, SucursalTaller

@pytest.mark.asyncio
async def test_match_workshop_found():
    # 1. Setup
    mock_assign_repo = MagicMock()
    mock_incident_repo = MagicMock()
    
    incident_id = uuid.uuid4()
    workshop_id = uuid.uuid4()
    branch_id = uuid.uuid4()
    
    # Mock Incidente
    mock_incident = MagicMock(spec=Incidente)
    mock_incident.id_incidente = incident_id
    mock_incident.ubicacion_emergencia = "POINT(0 0)"
    mock_incident.id_taller = None
    mock_incident.id_sucursal = None
    mock_incident.historial = []
    
    # Mock Taller encontrado
    mock_taller = MagicMock(spec=Taller)
    mock_taller.id_taller = workshop_id
    mock_taller.nombre = "Taller Central"
    mock_taller.administradores = []
    
    # Mock Sucursal encontrada
    mock_branch = MagicMock(spec=SucursalTaller)
    mock_branch.id_sucursal = branch_id
    mock_branch.id_taller = workshop_id
    mock_branch.nombre = "Casa Matriz"
    mock_branch.taller = mock_taller
    
    mock_incident_repo.get_by_id = AsyncMock(return_value=mock_incident)
    mock_assign_repo.get_nearby_workshops = AsyncMock(return_value=[(mock_branch, 500.0)]) # 500m de distancia
    mock_assign_repo.create_assignment = AsyncMock()
    
    mock_incident_repo.session = MagicMock()
    mock_incident_repo.session.commit = AsyncMock()

    # 2. Execute
    use_case = MatchWorkshopUseCase(mock_assign_repo, mock_incident_repo)
    result = await use_case.execute(incident_id)

    # 3. Assertions
    assert result is not None
    assert mock_incident.id_taller == workshop_id
    assert mock_incident.id_sucursal == branch_id
    assert mock_incident.estado_incidente == "TALLER_ASIGNADO"
    assert len(mock_incident.historial) == 1
    mock_assign_repo.create_assignment.assert_called_once()

@pytest.mark.asyncio
async def test_match_workshop_not_found():
    # Setup para cuando no hay talleres cerca
    mock_assign_repo = MagicMock()
    mock_incident_repo = MagicMock()
    
    incident_id = uuid.uuid4()
    mock_incident = MagicMock(spec=Incidente)
    mock_incident.ubicacion_emergencia = "POINT(0 0)"
    mock_incident.id_taller = None
    
    mock_incident_repo.get_by_id = AsyncMock(return_value=mock_incident)
    mock_assign_repo.get_nearby_workshops = AsyncMock(return_value=[]) # Lista vacía

    mock_incident_repo.session = MagicMock()
    mock_incident_repo.session.commit = AsyncMock()

    use_case = MatchWorkshopUseCase(mock_assign_repo, mock_incident_repo)
    result = await use_case.execute(incident_id)

    # Assertions
    assert result is None # No se creó asignación
    assert mock_incident.id_taller is None
