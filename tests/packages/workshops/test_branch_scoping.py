import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from fastapi import Request, HTTPException, status

from app.packages.identity.domain.models import Usuario, ROL_ADMIN_TALLER, ROL_SUPERADMIN
from app.packages.workshops.domain.models import Taller, SucursalTaller, UsuarioTaller, Tecnico, AdministradorTaller
from app.packages.workshops.dependencies import get_selected_branch_id, verify_write_permission, validate_resource_branch

@pytest.mark.asyncio
async def test_get_selected_branch_id_owner_global_view():
    # Setup - Owner with no branch headers
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {}
    mock_request.query_params = {}
    
    mock_db = AsyncMock()
    
    # Mock user as Owner
    mock_user = MagicMock(spec=Usuario)
    mock_user.id_usuario = uuid.uuid4()
    mock_user.rol_nombre = ROL_ADMIN_TALLER

    # Mock DB query results (no Admin Sucursal, no Técnico, but Owner link exists)
    mock_db.execute = AsyncMock()
    
    mock_res_ut = MagicMock()
    mock_res_ut.scalars.return_value.first.return_value = None
    
    mock_res_tec = MagicMock()
    mock_res_tec.scalars.return_value.first.return_value = None
    
    mock_res_owner = MagicMock()
    mock_res_owner.scalars.return_value.first.return_value = MagicMock(spec=AdministradorTaller)
    
    mock_db.execute.side_effect = [mock_res_ut, mock_res_tec, mock_res_owner]

    # Mock WorkshopRepository
    mock_taller = MagicMock(spec=Taller)
    mock_taller.id_taller = uuid.uuid4()
    
    # We patch import/creation inside function by mocking select or repository behaviour if needed, 
    # but here we can mock get_by_admin on Repository by patching WorkshopRepository
    with unittest_mock_workshop_repository(mock_taller, None):
        result = await get_selected_branch_id(mock_request, mock_db, mock_user)
        assert result is None
        assert mock_request.state.rol_usuario == ROL_ADMIN_TALLER
        assert mock_request.state.id_taller == mock_taller.id_taller
        assert mock_request.state.id_sucursal_contexto is None

@pytest.mark.asyncio
async def test_get_selected_branch_id_owner_local_view():
    branch_uuid = uuid.uuid4()
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"X-Selected-Branch": str(branch_uuid)}
    mock_request.query_params = {}
    
    mock_db = AsyncMock()
    
    mock_user = MagicMock(spec=Usuario)
    mock_user.id_usuario = uuid.uuid4()
    mock_user.rol_nombre = ROL_ADMIN_TALLER

    mock_db.execute = AsyncMock()
    
    mock_res_ut = MagicMock()
    mock_res_ut.scalars.return_value.first.return_value = None
    mock_res_tec = MagicMock()
    mock_res_tec.scalars.return_value.first.return_value = None
    mock_res_owner = MagicMock()
    mock_res_owner.scalars.return_value.first.return_value = MagicMock(spec=AdministradorTaller)
    
    mock_db.execute.side_effect = [mock_res_ut, mock_res_tec, mock_res_owner]

    mock_taller = MagicMock(spec=Taller)
    mock_taller.id_taller = uuid.uuid4()
    mock_branch = MagicMock(spec=SucursalTaller)
    mock_branch.id_sucursal = branch_uuid
    mock_branch.is_active = True
    
    with unittest_mock_workshop_repository(mock_taller, mock_branch):
        result = await get_selected_branch_id(mock_request, mock_db, mock_user)
        assert result == branch_uuid
        assert mock_request.state.id_sucursal_contexto == branch_uuid

@pytest.mark.asyncio
async def test_verify_write_permission_owner_global_denied():
    mock_user = MagicMock(spec=Usuario)
    mock_user.id_usuario = uuid.uuid4()
    mock_user.rol_nombre = ROL_ADMIN_TALLER
    
    mock_db = AsyncMock()
    mock_res_owner = MagicMock()
    mock_res_owner.scalars.return_value.first.return_value = MagicMock(spec=AdministradorTaller)
    
    mock_res_ut = MagicMock()
    mock_res_ut.scalars.return_value.first.return_value = None
    
    mock_db.execute.side_effect = [mock_res_owner, mock_res_ut]

    # Global view (selected_branch_id = None)
    with pytest.raises(HTTPException) as exc_info:
        await verify_write_permission(None, mock_user, mock_db)
    
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "Vista Global" in exc_info.value.detail

@pytest.mark.asyncio
async def test_validate_resource_branch_mismatch():
    mock_user = MagicMock(spec=Usuario)
    mock_user.rol_nombre = ROL_ADMIN_TALLER
    
    mock_db = AsyncMock()
    mock_res_owner = MagicMock()
    mock_res_owner.scalars.return_value.first.return_value = MagicMock(spec=AdministradorTaller)
    mock_res_ut = MagicMock()
    mock_res_ut.scalars.return_value.first.return_value = None
    mock_db.execute.side_effect = [mock_res_ut, mock_res_owner]

    branch_a = uuid.uuid4()
    branch_b = uuid.uuid4()

    # Selected A, resource is B
    with pytest.raises(HTTPException) as exc_info:
        await validate_resource_branch(branch_b, branch_a, mock_user, mock_db)
        
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "Discrepancia" in exc_info.value.detail

# --- Helper context to mock WorkshopRepository import inside functions ---
import contextlib
from unittest.mock import patch

@contextlib.contextmanager
def unittest_mock_workshop_repository(mock_taller, mock_branch):
    with patch("app.packages.workshops.infrastructure.repositories.WorkshopRepository") as mock_repo_class:
        mock_repo = MagicMock()
        mock_repo.get_by_admin = AsyncMock(return_value=mock_taller)
        mock_repo.get_branch_by_id = AsyncMock(return_value=mock_branch)
        mock_repo_class.return_value = mock_repo
        yield mock_repo
