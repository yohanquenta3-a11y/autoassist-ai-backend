import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from app.packages.emergencies.presentation.routers import get_latest_tracking
from app.packages.emergencies.domain.models import Incidente
from app.packages.assignment.domain.models import AsignacionIncidente
from app.packages.workshops.domain.models import TrackingTecnico, SucursalTaller, Taller

@pytest.mark.asyncio
async def test_get_latest_tracking_real_priority():
    # Setup
    mock_db = AsyncMock()
    mock_user = MagicMock()
    incident_id = uuid.uuid4()
    assignment_id = uuid.uuid4()

    # Mock incident
    mock_incident = MagicMock(spec=Incidente)
    mock_incident.id_incidente = incident_id
    mock_incident.ubicacion_emergencia = None # No directions calculation needed for simplicity
    
    # Mock incident repo return value
    with patch("app.packages.emergencies.presentation.routers.IncidentRepository") as mock_repo_class:
        mock_repo = MagicMock()
        mock_repo.get_by_id = AsyncMock(return_value=mock_incident)
        mock_repo_class.return_value = mock_repo

        # Mock query return for assignment
        mock_res_assign = MagicMock()
        mock_assign = MagicMock(spec=AsignacionIncidente)
        mock_assign.id_asignacion = assignment_id
        mock_res_assign.scalars.return_value.first.return_value = mock_assign

        # Mock query return for tracking
        mock_res_track = MagicMock()
        mock_tracking = MagicMock(spec=TrackingTecnico)
        mock_tracking.latitud = -17.78
        mock_tracking.longitud = -63.18
        mock_tracking.velocidad = 45.0
        mock_tracking.fecha_registro = MagicMock()
        mock_tracking.fecha_registro.isoformat.return_value = "2026-06-04T12:00:00"
        mock_res_track.scalars.return_value.first.return_value = mock_tracking

        mock_db.execute.side_effect = [mock_res_assign, mock_res_track]

        # Execute
        result = await get_latest_tracking(incident_id, mock_user, mock_db)

        # Assertions
        assert result["latitud"] == -17.78
        assert result["longitud"] == -63.18
        assert result["velocidad"] == 45.0
        assert result["is_estimated"] is False
        assert result["has_tracking"] is True
        assert result["timestamp"] == "2026-06-04T12:00:00"

@pytest.mark.asyncio
async def test_get_latest_tracking_no_fallback():
    # Setup
    mock_db = AsyncMock()
    mock_user = MagicMock()
    incident_id = uuid.uuid4()
    assignment_id = uuid.uuid4()
    sucursal_id = uuid.uuid4()

    # Mock incident with sucursal id
    mock_incident = MagicMock(spec=Incidente)
    mock_incident.id_incidente = incident_id
    mock_incident.id_sucursal = sucursal_id
    mock_incident.id_taller = None
    mock_incident.ubicacion_emergencia = None

    # Mock incident repo return value
    with patch("app.packages.emergencies.presentation.routers.IncidentRepository") as mock_repo_class:
        mock_repo = MagicMock()
        mock_repo.get_by_id = AsyncMock(return_value=mock_incident)
        mock_repo_class.return_value = mock_repo

        # Mock query return for assignment
        mock_res_assign = MagicMock()
        mock_assign = MagicMock(spec=AsignacionIncidente)
        mock_assign.id_asignacion = assignment_id
        mock_res_assign.scalars.return_value.first.return_value = mock_assign

        # Mock query return for tracking (None)
        mock_res_track = MagicMock()
        mock_res_track.scalars.return_value.first.return_value = None

        mock_db.execute.side_effect = [mock_res_assign, mock_res_track]

        # Execute
        result = await get_latest_tracking(incident_id, mock_user, mock_db)

        # Assertions
        assert result["latitud"] is None
        assert result["longitud"] is None
        assert result["is_estimated"] is False
        assert result["has_tracking"] is False
        assert result["timestamp"] is None
