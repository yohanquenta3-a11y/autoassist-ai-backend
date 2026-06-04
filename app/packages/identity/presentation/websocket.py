from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional
from app.core.notifications import manager
from app.core.security import decode_token
from app.packages.identity.infrastructure.repositories import UserRepository
from app.core.database import AsyncSessionLocal
import asyncio

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    id_sucursal: Optional[str] = Query(None)
):
    """
    Endpoint de WebSocket para notificaciones en tiempo real.
    """
    db = AsyncSessionLocal()
    try:
        # 1. Validar Token
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=1008)
            return

        # 2. Obtener info del usuario para saber su rol y taller
        user_repo = UserRepository(db)
        user = await user_repo.get_by_id(user_id)
        if not user:
            await websocket.close(code=1008)
            return

        is_admin = user.rol_nombre == "superadmin"
        
        # Scoping validation for branches
        if not is_admin:
            from app.packages.workshops.domain.models import UsuarioTaller, AdministradorTaller, Tecnico
            from sqlalchemy import select
            import uuid

            # Check if Admin Sucursal
            result_ut = await db.execute(
                select(UsuarioTaller).where(
                    UsuarioTaller.id_usuario == user.id_usuario,
                    UsuarioTaller.rol_contexto == "admin_sucursal",
                    UsuarioTaller.estado == True
                )
            )
            ut_link = result_ut.scalars().first()

            # Check if Técnico
            result_tec = await db.execute(
                select(Tecnico).where(
                    Tecnico.id_usuario == user.id_usuario,
                    Tecnico.estado == True
                )
            )
            tec = result_tec.scalars().first()

            # Check if Owner
            result_owner = await db.execute(
                select(AdministradorTaller).where(AdministradorTaller.id_usuario == user.id_usuario)
            )
            is_owner = result_owner.scalars().first() is not None

            # Resolve query param id_sucursal
            clean_sucursal_param = None
            if id_sucursal:
                cleaned = id_sucursal.strip().lower()
                if cleaned not in ("", "null", "undefined", "none"):
                    try:
                        clean_sucursal_param = uuid.UUID(cleaned)
                    except ValueError:
                        await websocket.close(code=1008)
                        return

            # Scoping logic
            if is_owner and not ut_link:
                # Owner must specify a branch to connect
                if not clean_sucursal_param:
                    await websocket.close(code=1008)
                    return
                
                # Check Owner's workshop
                from app.packages.workshops.infrastructure.repositories import WorkshopRepository
                workshop_repo = WorkshopRepository(db)
                taller = await workshop_repo.get_by_admin(user.id_usuario)
                if not taller:
                    await websocket.close(code=1008)
                    return
                
                # Validate selected branch belongs to workshop
                branch = await workshop_repo.get_branch_by_id(clean_sucursal_param, taller.id_taller)
                if not branch or not branch.is_active:
                    await websocket.close(code=1008)
                    return

            elif ut_link:
                # Admin Sucursal
                if not ut_link.id_sucursal:
                    await websocket.close(code=1008)
                    return
                if clean_sucursal_param and clean_sucursal_param != ut_link.id_sucursal:
                    await websocket.close(code=1008)
                    return

            elif tec:
                # Técnico
                if not tec.id_sucursal:
                    await websocket.close(code=1008)
                    return
                if clean_sucursal_param and clean_sucursal_param != tec.id_sucursal:
                    await websocket.close(code=1008)
                    return

        # Buscar taller vinculado
        workshop_id = None
        from app.packages.workshops.infrastructure.repositories import WorkshopRepository
        workshop_repo = WorkshopRepository(db)
        taller = await workshop_repo.get_by_admin(user_id)
        if taller:
            workshop_id = str(taller.id_taller)

        # 3. Conectar al manager
        await manager.connect(user_id, is_admin, websocket, workshop_id)
        
        # 4. Mantener la conexión abierta
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(user_id, is_admin, websocket, workshop_id)
            
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error en WebSocket: {e}")
        try:
            await websocket.close(code=1011)
        except:
            pass
    finally:
        # Cerrar sesión de DB de forma segura
        try:
            await db.close()
        except:
            pass
