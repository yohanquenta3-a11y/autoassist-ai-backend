import pytest
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from app.packages.finance.application.close_incident import CloseIncidentUseCase
from app.packages.emergencies.domain.models import Incidente

@pytest.mark.asyncio
async def test_close_incident_success():
    # Setup
    mock_finance_repo = MagicMock()
    mock_incident_repo = MagicMock()
    
    id_taller = uuid.uuid4()
    id_incidente = uuid.uuid4()
    monto_total = Decimal("1000.00")
    
    mock_incident = MagicMock(spec=Incidente)
    mock_incident.id_taller = id_taller
    mock_incident.estado_incidente = "EN_PROGRESO"
    mock_incident.id_tecnico = None
    mock_incident.historial = []
    
    mock_incident_repo.get_by_id = AsyncMock(return_value=mock_incident)
    mock_incident_repo.session = MagicMock()
    mock_incident_repo.session.commit = AsyncMock()
    mock_finance_repo.create_payment = AsyncMock()
    mock_finance_repo.get_payment_by_incident = AsyncMock(return_value=None)

    # Execute
    use_case = CloseIncidentUseCase(mock_finance_repo, mock_incident_repo)
    result = await use_case.execute(id_taller, id_incidente, monto_total)

    # Assertions
    assert result.monto == monto_total
    assert result.monto_comision == Decimal("100.00") # 10% de 1000
    assert result.estado_pago == "PAGADO"
    assert mock_incident.estado_incidente == "COMPLETADO"
    assert len(mock_incident.historial) == 1
    assert mock_incident.historial[0].historial_actor == "SISTEMA_FINANCIERO"
    
    mock_finance_repo.create_payment.assert_called_once()
    mock_incident_repo.session.commit.assert_called_once()
