from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.packages.identity.domain.models import Bitacora, ROL_ADMIN_TALLER, ROL_SUPERADMIN, Usuario
from app.packages.identity.presentation.schemas.audit_schemas import AuditLogResponse, PaginatedAuditLogResponse
from app.packages.workshops.dependencies import get_selected_branch_id
from app.packages.workshops.domain.models import SucursalTaller, Taller

SYSTEM_ADMIN_ROLES = {ROL_SUPERADMIN, "admin_sistema", "root"}


router = APIRouter(prefix="/audit", tags=["Audit"])


async def _resolve_audit_scope(
    *,
    db: AsyncSession,
    current_user: Usuario,
    requested_taller_id: Optional[UUID],
    requested_branch_id: Optional[UUID],
    selected_branch_id: Optional[UUID],
) -> tuple[Optional[UUID], Optional[UUID]]:
    role = current_user.rol_nombre

    if role in SYSTEM_ADMIN_ROLES:
        if requested_branch_id and requested_taller_id:
            branch = await db.scalar(
                select(SucursalTaller).where(
                    SucursalTaller.id_sucursal == requested_branch_id,
                    SucursalTaller.id_taller == requested_taller_id,
                )
            )
            if not branch:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="La sucursal solicitada no pertenece al taller seleccionado.",
                )
        return requested_taller_id, requested_branch_id

    if role == ROL_ADMIN_TALLER and current_user.rol_contexto == "owner":
        if not current_user.id_taller:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No se encontro el taller asociado al usuario actual.",
            )
        return current_user.id_taller, selected_branch_id

    if role == ROL_ADMIN_TALLER and current_user.rol_contexto == "admin_sucursal":
        if not current_user.id_taller or not current_user.id_sucursal:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No se encontro la sucursal asociada al usuario actual.",
            )
        return current_user.id_taller, current_user.id_sucursal

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No tiene permisos para ver la bitacora de auditoria.",
    )


@router.get("/logs", response_model=PaginatedAuditLogResponse)
async def get_audit_logs(
    db: AsyncSession = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user),
    selected_branch_id: Optional[UUID] = Depends(get_selected_branch_id),
    accion: Optional[str] = Query(None, description="Filtrar por accion o metodo"),
    usuario_nombre: Optional[str] = Query(None, description="Buscar por nombre de usuario"),
    fecha_inicio: Optional[datetime] = Query(None),
    fecha_fin: Optional[datetime] = Query(None),
    id_taller: Optional[UUID] = Query(None),
    id_sucursal: Optional[UUID] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    scope_taller_id, scope_branch_id = await _resolve_audit_scope(
        db=db,
        current_user=current_user,
        requested_taller_id=id_taller,
        requested_branch_id=id_sucursal,
        selected_branch_id=selected_branch_id,
    )

    branch_context = aliased(SucursalTaller)
    branch_affected = aliased(SucursalTaller)

    stmt = (
        select(
            Bitacora,
            Usuario.nombre.label("nombre_usuario"),
            Taller.nombre.label("taller_nombre"),
            func.coalesce(branch_context.nombre, branch_affected.nombre).label("sucursal_nombre"),
        )
        .outerjoin(Usuario, Bitacora.id_usuario_actor == Usuario.id_usuario)
        .outerjoin(Taller, Bitacora.id_taller == Taller.id_taller)
        .outerjoin(
            branch_context,
            and_(
                Bitacora.id_sucursal_contexto == branch_context.id_sucursal,
                or_(Bitacora.id_taller.is_(None), Bitacora.id_taller == branch_context.id_taller),
            ),
        )
        .outerjoin(
            branch_affected,
            and_(
                Bitacora.id_sucursal_afectada == branch_affected.id_sucursal,
                or_(Bitacora.id_taller.is_(None), Bitacora.id_taller == branch_affected.id_taller),
            ),
        )
        .order_by(Bitacora.fecha_hora.desc())
    )

    filters = []
    if scope_taller_id is not None:
        filters.append(Bitacora.id_taller == scope_taller_id)
    if scope_branch_id is not None:
        filters.append(
            or_(
                Bitacora.id_sucursal_contexto == scope_branch_id,
                Bitacora.id_sucursal_afectada == scope_branch_id,
            )
        )
    if accion:
        filters.append(Bitacora.accion.ilike(f"%{accion}%"))
    if usuario_nombre:
        filters.append(
            or_(
                Usuario.nombre.ilike(f"%{usuario_nombre}%"),
                Usuario.correo.ilike(f"%{usuario_nombre}%"),
            )
        )
    if fecha_inicio:
        filters.append(Bitacora.fecha_hora >= fecha_inicio)
    if fecha_fin:
        filters.append(Bitacora.fecha_hora <= fecha_fin)

    if filters:
        stmt = stmt.where(*filters)

    count_stmt = (
        select(func.count(Bitacora.id_bitacora))
        .select_from(Bitacora)
        .outerjoin(Usuario, Bitacora.id_usuario_actor == Usuario.id_usuario)
        .outerjoin(Taller, Bitacora.id_taller == Taller.id_taller)
        .outerjoin(
            branch_context,
            and_(
                Bitacora.id_sucursal_contexto == branch_context.id_sucursal,
                or_(Bitacora.id_taller.is_(None), Bitacora.id_taller == branch_context.id_taller),
            ),
        )
        .outerjoin(
            branch_affected,
            and_(
                Bitacora.id_sucursal_afectada == branch_affected.id_sucursal,
                or_(Bitacora.id_taller.is_(None), Bitacora.id_taller == branch_affected.id_taller),
            ),
        )
    )
    if filters:
        count_stmt = count_stmt.where(*filters)

    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    total_pages = max((total + page_size - 1) // page_size, 1) if total > 0 else 0

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(stmt)
    rows = result.all()

    logs: list[AuditLogResponse] = []
    for row in rows:
        bitacora, nombre_usuario, taller_nombre, sucursal_nombre = row
        logs.append(
            AuditLogResponse(
                id_bitacora=bitacora.id_bitacora,
                id_usuario=bitacora.id_usuario_actor,
                nombre_usuario=nombre_usuario,
                rol_usuario=bitacora.rol_usuario,
                ip=bitacora.ip,
                accion=bitacora.accion,
                descripcion=bitacora.descripcion,
                tipo_entidad=bitacora.tipo_entidad,
                id_entidad=bitacora.id_entidad,
                id_taller=bitacora.id_taller,
                taller_nombre=taller_nombre,
                id_sucursal=bitacora.id_sucursal_contexto or bitacora.id_sucursal_afectada,
                sucursal_nombre=sucursal_nombre,
                fecha_hora=bitacora.fecha_hora,
            )
        )

    return PaginatedAuditLogResponse(
        items=logs,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
