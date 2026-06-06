import pytest
import uuid
from datetime import date, datetime, timedelta, timezone, time
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import BadRequestError, NotFoundError, ForbiddenError

# Import all project models to configure SQLAlchemy registries for isolated tests
import app.packages.identity.domain.models
import app.packages.workshops.domain.models
import app.packages.emergencies.domain.models
import app.packages.assignment.domain.models
import app.packages.finance.domain.models
import app.packages.scheduling.domain.models

from app.packages.identity.domain.models import Usuario
from app.packages.workshops.domain.models import Tecnico, SucursalTaller, Taller
from app.packages.emergencies.domain.models import Incidente, HistorialIncidente
from app.packages.scheduling.domain.models import Cita
from app.packages.scheduling.domain.services import SchedulingService, LOCAL_TZ
from app.packages.scheduling.domain.schemas import SlotAvailabilityResponse

# ... (rest of tests unchanged up to test_create_appointment_success) ...
@pytest.mark.asyncio
async def test_get_available_slots_sunday():
    # Setup
    mock_db = AsyncMock()
    service = SchedulingService(mock_db)
    
    # Sunday target date (e.g. 2026-06-07 is a Sunday)
    sunday = date(2026, 6, 7)
    
    slots = await service.get_available_slots(uuid.uuid4(), sunday)
    assert len(slots) == 0

@pytest.mark.asyncio
async def test_get_available_slots_out_of_range():
    # Setup
    mock_db = AsyncMock()
    service = SchedulingService(mock_db)
    
    # Target date is far in the future
    far_future = date.today() + timedelta(days=15)
    
    slots = await service.get_available_slots(uuid.uuid4(), far_future)
    assert len(slots) == 0

@pytest.mark.asyncio
async def test_create_appointment_duplicate_incident():
    mock_db = AsyncMock()
    service = SchedulingService(mock_db)
    
    creator = MagicMock(spec=Usuario)
    creator.id_usuario = uuid.uuid4()
    creator.rol_nombre = "tecnico"
    
    incident_id = uuid.uuid4()
    
    # Mock existing active appointment
    existing_appt = MagicMock(spec=Cita)
    service.repo.get_active_by_incident = AsyncMock(return_value=existing_appt)
    
    with pytest.raises(BadRequestError) as exc_info:
        await service.create_appointment(
            creator=creator,
            id_incidente_origen=incident_id,
            id_vehiculo=uuid.uuid4(),
            id_tecnico=None,
            fecha_hora=datetime.now(timezone.utc),
            motivo="Seguimiento",
            observaciones=None,
            prioridad="MEDIA"
        )
    assert "Ya existe una cita posterior activa" in str(exc_info.value.detail)

@pytest.mark.asyncio
async def test_create_appointment_success():
    mock_db = AsyncMock()
    service = SchedulingService(mock_db)
    
    creator = MagicMock(spec=Usuario)
    creator.id_usuario = uuid.uuid4()
    creator.rol_nombre = "tecnico"
    creator.nombre = "Tech User"
    
    incident_id = uuid.uuid4()
    vehiculo_id = uuid.uuid4()
    taller_id = uuid.uuid4()
    sucursal_id = uuid.uuid4()
    
    # 1. No active appointments exist
    service.repo.get_active_by_incident = AsyncMock(return_value=None)
    service.repo.get_active_by_sucursal_and_date = AsyncMock(return_value=[])
    
    # 2. Mock incident object
    mock_incident = MagicMock(spec=Incidente)
    mock_incident.estado_incidente = "EN_ATENCION"
    mock_incident.id_taller = taller_id
    mock_incident.id_sucursal = sucursal_id
    mock_incident.id_usuario_cliente = uuid.uuid4()
    mock_incident.id_tecnico = creator.id_usuario
    
    mock_db.execute = AsyncMock()
    
    # Mock select incident scalar execution
    mock_res_inc = MagicMock()
    mock_res_inc.scalars.return_value.first.return_value = mock_incident
    
    # Mock active technicians query (returns empty list, capacity = 2)
    mock_res_tecs = MagicMock()
    mock_res_tecs.scalars.return_value.all.return_value = []
    
    # Mock database executes in order
    mock_db.execute.side_effect = [mock_res_inc, mock_res_tecs]
    
    # Date must be tomorrow (a Saturday for 2026-06-06 or check weekday to ensure it's not Sunday)
    tomorrow = datetime.now(LOCAL_TZ).date() + timedelta(days=1)
    if tomorrow.weekday() == 6:  # if Sunday, shift by another day
        tomorrow += timedelta(days=1)
        
    # Valid local time slot: 10:00 AM local
    local_dt = datetime.combine(tomorrow, time(hour=10, minute=0), tzinfo=LOCAL_TZ)
    utc_dt = local_dt.astimezone(timezone.utc)
    
    # Mock Repository create return
    mock_created = MagicMock(spec=Cita)
    mock_created.id_cita = uuid.uuid4()
    mock_created.id_incidente_origen = incident_id
    mock_created.estado = "PENDIENTE_CONFIRMACION"
    
    service.repo.create_appointment = AsyncMock(return_value=mock_created)
    
    appt = await service.create_appointment(
        creator=creator,
        id_incidente_origen=incident_id,
        id_vehiculo=vehiculo_id,
        id_tecnico=None,
        fecha_hora=utc_dt,
        motivo="Revisión de pastillas de freno",
        observaciones="Cliente reporta ruidos",
        prioridad="ALTA"
    )
    
    assert appt.estado == "PENDIENTE_CONFIRMACION"
    service.repo.create_appointment.assert_called_once()

@pytest.mark.asyncio
async def test_confirm_appointment_success():
    mock_db = AsyncMock()
    service = SchedulingService(mock_db)
    
    client = MagicMock(spec=Usuario)
    client.id_usuario = uuid.uuid4()
    client.rol_nombre = "cliente"
    client.nombre = "Client User"
    
    appt_id = uuid.uuid4()
    mock_appt = MagicMock(spec=Cita)
    mock_appt.id_cita = appt_id
    mock_appt.id_cliente = client.id_usuario
    mock_appt.id_incidente_origen = uuid.uuid4()
    mock_appt.id_taller = uuid.uuid4()
    mock_appt.id_sucursal = uuid.uuid4()
    mock_appt.estado = "PENDIENTE_CONFIRMACION"
    
    service.repo.get_by_id = AsyncMock(return_value=mock_appt)
    service.repo.update_appointment = AsyncMock(return_value=mock_appt)
    
    confirmed = await service.confirm_appointment(appt_id, client)
    assert confirmed.estado == "CONFIRMADA"
    service.repo.update_appointment.assert_called_once()

@pytest.mark.asyncio
async def test_cancel_appointment_forbidden_client():
    mock_db = AsyncMock()
    service = SchedulingService(mock_db)
    
    another_client = MagicMock(spec=Usuario)
    another_client.id_usuario = uuid.uuid4()
    another_client.rol_nombre = "cliente"
    
    appt_id = uuid.uuid4()
    mock_appt = MagicMock(spec=Cita)
    mock_appt.id_cita = appt_id
    mock_appt.id_cliente = uuid.uuid4()  # Mismatching owner
    
    service.repo.get_by_id = AsyncMock(return_value=mock_appt)
    
    with pytest.raises(ForbiddenError) as exc_info:
        await service.cancel_appointment(appt_id, another_client)
    assert "No tiene permisos" in str(exc_info.value.detail)
