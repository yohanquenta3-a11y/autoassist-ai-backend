import logging
import uuid
from typing import Optional
from sqlalchemy import insert
from app.core.database import AsyncSessionLocal
from app.packages.identity.domain.models import Bitacora

logger = logging.getLogger(__name__)

def mask_sensitive_data(data):
    if not isinstance(data, dict):
        return data
    masked = {}
    sensitive_keys = {
        "contrasena", "password", "token", "contraseña", "access_token", 
        "temp_password", "contrasena_hash", "client_secret", "secret",
        "authorization", "jwt"
    }
    for k, v in data.items():
        if k.lower() in sensitive_keys:
            masked[k] = "[ENMASCARADO]"
        elif isinstance(v, dict):
            masked[k] = mask_sensitive_data(v)
        elif isinstance(v, list):
            masked[k] = [mask_sensitive_data(item) if isinstance(item, dict) else item for item in v]
        else:
            masked[k] = v
    return masked

async def save_audit_log(
    user_id: str,
    ip: str,
    method: str,
    path: str,
    status_code: int,
    descripcion: str = None,
    rol_usuario: str = None,
    id_taller: Optional[uuid.UUID] = None,
    id_sucursal_contexto: Optional[uuid.UUID] = None,
    id_sucursal_afectada: Optional[uuid.UUID] = None,
    tipo_entidad: str = None,
    id_entidad: Optional[uuid.UUID] = None,
    datos_antes: dict = None,
    datos_despues: dict = None
):
    """Tarea en segundo plano para guardar la bitácora de auditoría enriquecida."""
    async with AsyncSessionLocal() as db:
        try:
            # Mask data
            masked_antes = mask_sensitive_data(datos_antes) if datos_antes else None
            masked_despues = mask_sensitive_data(datos_despues) if datos_despues else None
            
            # Check user_id uuid conversion
            actor_uuid = None
            if user_id and user_id != "LOGIN_PENDING":
                try:
                    actor_uuid = uuid.UUID(str(user_id))
                except ValueError:
                    pass

            stmt = insert(Bitacora).values(
                id_usuario_actor=actor_uuid or uuid.UUID("00000000-0000-0000-0000-000000000000"),
                rol_usuario=rol_usuario,
                id_taller=id_taller,
                id_sucursal_contexto=id_sucursal_contexto,
                id_sucursal_afectada=id_sucursal_afectada,
                tipo_entidad=tipo_entidad,
                id_entidad=id_entidad,
                ip=ip,
                accion=f"{method} {path}",
                descripcion=descripcion or f"Status: {response.status_code if 'response' in locals() else status_code}",
                datos_antes=masked_antes,
                datos_despues=masked_despues
            )
            await db.execute(stmt)
            await db.commit()
        except Exception as e:
            logger.error(f"Error guardando bitácora: {str(e)}")
