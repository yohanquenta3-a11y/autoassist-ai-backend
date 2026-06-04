import uuid
from typing import Optional
from fastapi import Request, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.packages.identity.domain.models import Usuario, ROL_ADMIN_TALLER, ROL_SUPERADMIN
from app.packages.workshops.domain.models import Taller, SucursalTaller, UsuarioTaller, Tecnico, AdministradorTaller

async def get_selected_branch_id(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
) -> Optional[uuid.UUID]:
    """
    Dependency that extracts and validates the selected branch ID from the context (X-Selected-Branch header or id_sucursal query parameter).
    - If the user is Owner (rol_nombre == ROL_ADMIN_TALLER and has AdministradorTaller entry):
      - If no branch is specified, returns None (global view).
      - If a branch is specified, validates that it belongs to the Owner's workshop.
    - If the user is Admin Sucursal or Técnico, returns their assigned branch ID, ignoring any headers or params.
    """
    role = current_user.rol_nombre
    request.state.rol_usuario = role
    if role == ROL_SUPERADMIN:
        return None

    # Check if user is Admin Sucursal
    result_ut = await db.execute(
        select(UsuarioTaller).where(
            UsuarioTaller.id_usuario == current_user.id_usuario,
            UsuarioTaller.rol_contexto == "admin_sucursal",
            UsuarioTaller.estado == True
        )
    )
    ut_link = result_ut.scalars().first()
    if ut_link:
        if not ut_link.id_sucursal:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El administrador de sucursal no tiene una sucursal asignada."
            )
        request.state.id_taller = ut_link.id_taller
        request.state.id_sucursal_contexto = ut_link.id_sucursal
        return ut_link.id_sucursal

    # Check if user is Técnico
    result_tec = await db.execute(
        select(Tecnico).where(
            Tecnico.id_usuario == current_user.id_usuario,
            Tecnico.estado == True
        )
    )
    tec = result_tec.scalars().first()
    if tec:
        request.state.id_taller = tec.id_taller
        request.state.id_sucursal_contexto = tec.id_sucursal
        return tec.id_sucursal

    # Check if user is Owner (admin_taller linked to a workshop via AdministradorTaller)
    result_owner = await db.execute(
        select(AdministradorTaller).where(AdministradorTaller.id_usuario == current_user.id_usuario)
    )
    is_owner = result_owner.scalars().first() is not None

    if is_owner or role == ROL_ADMIN_TALLER:
        # Extract Owner workshop
        from app.packages.workshops.infrastructure.repositories import WorkshopRepository
        repo = WorkshopRepository(db)
        taller = await repo.get_by_admin(current_user.id_usuario)
        if not taller:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El usuario no tiene un taller registrado."
            )
        request.state.id_taller = taller.id_taller

        # Extract query parameter or header (prioritize explicit query param over global header context)
        branch_query = request.query_params.get("id_sucursal")
        branch_header = request.headers.get("x-selected-branch") or request.headers.get("X-Selected-Branch")
        raw_branch = branch_query if branch_query is not None else branch_header

        # Clean string
        branch_id_str = None
        if raw_branch:
            cleaned = raw_branch.strip().lower()
            if cleaned not in ("", "null", "undefined", "none", "all", "global"):
                branch_id_str = raw_branch

        if not branch_id_str:
            request.state.id_sucursal_contexto = None
            return None  # Global view

        try:
            branch_uuid = uuid.UUID(branch_id_str)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Formato de sucursal (UUID) inválido."
            )

        # Validate that branch belongs to Owner's workshop
        branch = await repo.get_branch_by_id(branch_uuid, taller.id_taller)
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="La sucursal seleccionada no pertenece a su taller."
            )
        if not branch.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="La sucursal seleccionada se encuentra inactiva."
            )
        request.state.id_sucursal_contexto = branch_uuid
        return branch_uuid

    return None

async def verify_write_permission(
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id),
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
) -> uuid.UUID:
    """
    Dependency that enforces that the user has write permissions in their current context.
    - Owner: Cannot write in global view (returns 403). Must select a branch.
    - Admin Sucursal/Técnico: Can write (selected_branch_id will be their assigned branch).
    - SuperAdmin: Bypasses check (returns None or dummy).
    """
    role = current_user.rol_nombre
    if role == ROL_SUPERADMIN:
        return None

    # Check if Owner
    result_owner = await db.execute(
        select(AdministradorTaller).where(AdministradorTaller.id_usuario == current_user.id_usuario)
    )
    is_owner = result_owner.scalars().first() is not None

    if is_owner or role == ROL_ADMIN_TALLER:
        # Check if Admin Sucursal to make sure they are not just Owner
        result_ut = await db.execute(
            select(UsuarioTaller).where(
                UsuarioTaller.id_usuario == current_user.id_usuario,
                UsuarioTaller.rol_contexto == "admin_sucursal",
                UsuarioTaller.estado == True
            )
        )
        is_admin_sucursal = result_ut.scalars().first() is not None

        if not is_admin_sucursal and selected_branch_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operación denegada en Vista Global. El Owner debe seleccionar una sucursal para realizar modificaciones."
            )

    if selected_branch_id is None:
        # If still None (e.g. clients without workshop/branch), write is forbidden under workshop scope
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operación de escritura denegada. Se requiere un contexto de sucursal activo."
        )

    return selected_branch_id

async def validate_resource_branch(
    resource_branch_id: Optional[uuid.UUID],
    selected_branch_id: Optional[uuid.UUID],
    current_user: Usuario,
    db: AsyncSession
) -> None:
    """
    Validates that the resource being modified matches the branch selected by the user.
    - Owner: resource_branch_id must match selected_branch_id (and selected_branch_id cannot be None).
    - Admin Sucursal / Técnico: resource_branch_id must match their assigned branch (which is selected_branch_id).
    """
    role = current_user.rol_nombre
    if role == ROL_SUPERADMIN:
        return

    # Check if Admin Sucursal
    result_ut = await db.execute(
        select(UsuarioTaller).where(
            UsuarioTaller.id_usuario == current_user.id_usuario,
            UsuarioTaller.rol_contexto == "admin_sucursal",
            UsuarioTaller.estado == True
        )
    )
    is_admin_sucursal = result_ut.scalars().first() is not None

    # Check if Owner
    result_owner = await db.execute(
        select(AdministradorTaller).where(AdministradorTaller.id_usuario == current_user.id_usuario)
    )
    is_owner = result_owner.scalars().first() is not None

    if is_owner and not is_admin_sucursal:
        if selected_branch_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operación denegada en Vista Global. El Owner debe seleccionar una sucursal para realizar modificaciones."
            )
        if resource_branch_id != selected_branch_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Discrepancia de sucursal. El recurso pertenece a la sucursal {resource_branch_id}, pero su sucursal activa es {selected_branch_id}."
            )
    elif is_admin_sucursal or role == ROL_ADMIN_TALLER or role == "tecnico":
        # Check that resource matches their assigned branch
        if resource_branch_id != selected_branch_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para modificar recursos de otra sucursal."
            )
