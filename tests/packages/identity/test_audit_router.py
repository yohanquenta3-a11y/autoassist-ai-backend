from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.packages.identity.domain.models import ROL_SUPERADMIN
from app.packages.identity.presentation.routers.audit_router import (
    _resolve_audit_scope,
    get_audit_logs,
)


@pytest.mark.asyncio
async def test_resolve_audit_scope_for_owner_ignores_foreign_workshop_filter():
    owner = SimpleNamespace(
        rol_nombre="admin_taller",
        rol_contexto="owner",
        id_taller=uuid4(),
        id_sucursal=None,
    )
    foreign_workshop = uuid4()
    selected_branch = uuid4()

    scope = await _resolve_audit_scope(
        db=AsyncMock(),
        current_user=owner,
        requested_taller_id=foreign_workshop,
        requested_branch_id=None,
        selected_branch_id=selected_branch,
    )

    assert scope == (owner.id_taller, selected_branch)


@pytest.mark.asyncio
async def test_get_audit_logs_maps_real_bitacora_fields():
    db = AsyncMock()
    actor_id = uuid4()
    workshop_id = uuid4()
    branch_id = uuid4()
    bitacora = SimpleNamespace(
        id_bitacora=uuid4(),
        id_usuario_actor=actor_id,
        rol_usuario="admin_taller",
        id_taller=workshop_id,
        id_sucursal_contexto=branch_id,
        id_sucursal_afectada=None,
        tipo_entidad="taller",
        id_entidad=uuid4(),
        ip="127.0.0.1",
        accion="PATCH /api/v1/workshops/me",
        descripcion="Actualizacion de taller",
        fecha_hora=datetime(2026, 6, 7, 8, 30, tzinfo=UTC),
    )
    db.execute.side_effect = [
        SimpleNamespace(scalar_one=lambda: 1),
        SimpleNamespace(
            all=lambda: [(bitacora, "Owner Demo", "Taller Norte", "Sucursal Centro")]
        ),
    ]

    current_user = SimpleNamespace(
        rol_nombre=ROL_SUPERADMIN,
        rol_contexto=None,
        id_taller=None,
        id_sucursal=None,
    )

    response = await get_audit_logs(
        db=db,
        current_user=current_user,
        selected_branch_id=None,
        accion=None,
        usuario_nombre=None,
        fecha_inicio=None,
        fecha_fin=None,
        id_taller=None,
        id_sucursal=None,
        page=1,
        page_size=20,
    )

    assert response.total == 1
    assert response.page == 1
    assert response.page_size == 20
    assert len(response.items) == 1
    assert response.items[0].id_usuario == actor_id
    assert response.items[0].taller_nombre == "Taller Norte"
    assert response.items[0].sucursal_nombre == "Sucursal Centro"
    assert response.items[0].rol_usuario == "admin_taller"


@pytest.mark.asyncio
async def test_resolve_audit_scope_for_admin_sistema_keeps_requested_filters():
    admin_sistema = SimpleNamespace(
        rol_nombre="admin_sistema",
        rol_contexto=None,
        id_taller=None,
        id_sucursal=None,
    )
    workshop_id = uuid4()
    branch_id = uuid4()

    scope = await _resolve_audit_scope(
        db=AsyncMock(),
        current_user=admin_sistema,
        requested_taller_id=workshop_id,
        requested_branch_id=branch_id,
        selected_branch_id=None,
    )

    assert scope == (workshop_id, branch_id)
