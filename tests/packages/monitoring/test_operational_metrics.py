from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.packages.monitoring.application.operational_metrics import (
    build_operational_dashboard,
    build_sla_alerts,
    resolve_operational_scope,
)


@pytest.mark.asyncio
async def test_resolve_operational_scope_for_owner():
    repository = AsyncMock()
    repository.get_user_operational_context.return_value = (
        uuid4(),
        None,
        "owner",
    )

    current_user = SimpleNamespace(id_usuario=uuid4(), rol_nombre="admin_taller")
    branch_id = uuid4()

    scope = await resolve_operational_scope(
        repository=repository,
        current_user=current_user,
        requested_taller_id=None,
        selected_branch_id=branch_id,
        requested_branch_id=None,
    )

    assert scope.role == "OWNER"
    assert scope.id_sucursal == branch_id
    assert scope.is_global is False


@pytest.mark.asyncio
async def test_build_operational_dashboard_aggregates_real_metrics():
    repository = AsyncMock()

    vehicle = SimpleNamespace(
        marca="Toyota",
        modelo="Corolla",
        matricula="123ABC",
        propietario=SimpleNamespace(nombre="Cliente 1"),
    )
    history = [
        SimpleNamespace(
            incidente_estado_nuevo="TALLER_ASIGNADO",
            fecha=datetime(2026, 6, 1, 10, 10, tzinfo=UTC),
        ),
        SimpleNamespace(
            incidente_estado_nuevo="EN_CAMINO",
            fecha=datetime(2026, 6, 1, 10, 15, tzinfo=UTC),
        ),
        SimpleNamespace(
            incidente_estado_nuevo="TECNICO_EN_SITIO",
            fecha=datetime(2026, 6, 1, 10, 35, tzinfo=UTC),
        ),
        SimpleNamespace(
            incidente_estado_nuevo="EN_ATENCION",
            fecha=datetime(2026, 6, 1, 10, 45, tzinfo=UTC),
        ),
        SimpleNamespace(
            incidente_estado_nuevo="COMPLETADO",
            fecha=datetime(2026, 6, 1, 11, 30, tzinfo=UTC),
        ),
    ]
    incident = SimpleNamespace(
        id_incidente=uuid4(),
        id_taller=uuid4(),
        id_sucursal=uuid4(),
        vehiculo=vehicle,
        taller=SimpleNamespace(nombre="Taller Uno"),
        tecnico=SimpleNamespace(nombre="Tecnico Uno"),
        historial=history,
        evidencias=[],
        verificaciones=[],
        pago=None,
        sucursal=SimpleNamespace(nombre="Sucursal A"),
        branch_name="Sucursal A",
        ubicacion_emergencia=None,
        fecha_reporte=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
        estado_incidente="COMPLETADO",
        prioridad_incidente="ALTA",
        origen="SOS",
        origen_registro="ONLINE",
        resumen_ia="Bateria descargada",
        analisis_consolidado=None,
        descripcion="Auxilio",
    )

    repository.get_incidents.return_value = [incident]

    response = await build_operational_dashboard(
        repository=repository,
        scope=SimpleNamespace(role="OWNER", id_taller=incident.id_taller, id_sucursal=None, is_global=True),
        date_from=None,
        date_to=None,
        estado=None,
        prioridad=None,
        origen=None,
    )

    assert response["summary"]["total_incidentes"] == 1
    assert response["summary"]["incidentes_finalizados"] == 1
    assert response["summary"]["tiempo_promedio_asignacion_min"] == 10.0
    assert response["summary"]["tiempo_promedio_llegada_min"] == 20.0
    assert response["summary"]["tiempo_promedio_finalizacion_min"] == 45.0


@pytest.mark.asyncio
async def test_build_operational_dashboard_handles_missing_relations_without_crashing():
    repository = AsyncMock()
    incident = SimpleNamespace(
        id_incidente=uuid4(),
        id_taller=None,
        id_sucursal=None,
        vehiculo=None,
        taller=None,
        tecnico=None,
        cliente=None,
        historial=[],
        evidencias=[],
        verificaciones=[],
        pago=None,
        sucursal=None,
        branch_name=None,
        ubicacion_emergencia=None,
        fecha_reporte=datetime(2026, 6, 2, 9, 0, tzinfo=UTC),
        estado_incidente="PENDIENTE",
        prioridad_incidente="MEDIA",
        origen=None,
        origen_registro="ONLINE",
        resumen_ia=None,
        analisis_consolidado=None,
        descripcion="Sin relaciones cargadas",
    )
    repository.get_incidents.return_value = [incident]

    response = await build_operational_dashboard(
        repository=repository,
        scope=SimpleNamespace(role="SUPERADMIN", id_taller=None, id_sucursal=None, is_global=True),
        date_from=None,
        date_to=None,
        estado=None,
        prioridad=None,
        origen=None,
    )

    assert response["summary"]["total_incidentes"] == 1
    assert response["series"]["incidentes_por_taller"][0]["label"] == "Sin taller asignado"
    assert response["series"]["incidentes_por_sucursal"][0]["label"] == "Sin sucursal"
    assert response["recent_activity"][0]["taller"] == "Sin taller asignado"
    assert response["recent_activity"][0]["sucursal"] == "Sin sucursal"


@pytest.mark.asyncio
async def test_build_sla_alerts_flags_delayed_assignment():
    repository = AsyncMock()
    vehicle = SimpleNamespace(
        marca="Nissan",
        modelo="Sentra",
        matricula="456DEF",
        propietario=SimpleNamespace(nombre="Cliente 2"),
    )
    incident = SimpleNamespace(
        id_incidente=uuid4(),
        id_taller=uuid4(),
        id_sucursal=uuid4(),
        vehiculo=vehicle,
        taller=SimpleNamespace(nombre="Taller Dos"),
        tecnico=None,
        historial=[],
        evidencias=[],
        verificaciones=[],
        pago=None,
        sucursal=SimpleNamespace(nombre="Sucursal B"),
        branch_name="Sucursal B",
        ubicacion_emergencia=None,
        fecha_reporte=datetime.now(UTC) - timedelta(minutes=25),
        estado_incidente="PENDIENTE",
        prioridad_incidente="CRITICA",
        origen="SOS",
        origen_registro="ONLINE",
        resumen_ia=None,
        analisis_consolidado=None,
        descripcion="Sin asignar",
    )
    repository.get_incidents.return_value = [incident]

    response = await build_sla_alerts(
        repository=repository,
        scope=SimpleNamespace(role="OWNER", id_taller=incident.id_taller, id_sucursal=None, is_global=True),
        date_from=None,
        date_to=None,
        prioridad=None,
        tipo_alerta=None,
        sla_status=None,
        estado_incidente=None,
    )

    assert response["summary"]["total_alertas"] >= 1
    assert any(alert["tipo_alerta"] == "RETRASO_ASIGNACION" for alert in response["alerts"])


@pytest.mark.asyncio
async def test_build_operational_dashboard_returns_null_sla_when_empty():
    repository = AsyncMock()
    repository.get_incidents.return_value = []

    response = await build_operational_dashboard(
        repository=repository,
        scope=SimpleNamespace(role="OWNER", id_taller=uuid4(), id_sucursal=None, is_global=True),
        date_from=None,
        date_to=None,
        estado=None,
        prioridad=None,
        origen=None,
    )

    assert response["summary"]["total_incidentes"] == 0
    assert response["summary"]["cumplimiento_sla_pct"] is None
