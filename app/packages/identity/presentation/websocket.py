from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.core.notifications import manager
from app.core.security import decode_token
from app.packages.identity.infrastructure.repositories import UserRepository
from app.core.database import AsyncSessionLocal
import asyncio

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...)
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
