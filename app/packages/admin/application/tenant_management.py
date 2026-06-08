import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.packages.admin.infrastructure.repositories import TenantRepository
from app.packages.workshops.domain.models import Taller, UsuarioTaller, Tecnico
from app.packages.emergencies.domain.models import Incidente
from app.packages.identity.domain.models import Usuario, Bitacora, ROL_SUPERADMIN
from app.core.exceptions import NotFoundError, ForbiddenError, ConflictError, BadRequestError


class TenantManagementService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TenantRepository(db)

    async def validar_permiso_global(self, current_user: Usuario) -> None:
        if current_user.rol_nombre != ROL_SUPERADMIN:
            raise ForbiddenError("Solo el SuperAdministrador puede gestionar talleres y tenants.")

    async def verificar_acceso_taller(self, current_user: Usuario, taller_id: uuid.UUID) -> None:
        if current_user.rol_nombre == ROL_SUPERADMIN:
            return
        if not current_user.id_taller or current_user.id_taller != taller_id:
            raise ForbiddenError("No tiene permiso para acceder a la información de este taller.")

    async def consultar_talleres_tenant(self, current_user: Usuario) -> list[Taller]:
        await self.validar_permiso_global(current_user)
        return await self.repo.get_all_workshops()

    async def consultar_taller_tenant(self, current_user: Usuario, taller_id: uuid.UUID) -> Taller:
        await self.validar_permiso_global(current_user)
        taller = await self.repo.get_workshop(taller_id)
        if not taller:
            raise NotFoundError("Taller no encontrado.")
        return taller

    async def registrar_actualizar_taller(
        self,
        current_user: Usuario,
        taller_data: dict,
        id_taller: Optional[uuid.UUID] = None
    ) -> Taller:
        await self.validar_permiso_global(current_user)

        if id_taller:
            taller = await self.repo.get_workshop(id_taller)
            if not taller:
                raise NotFoundError("Taller no encontrado.")
            for key, value in taller_data.items():
                setattr(taller, key, value)
            return await self.repo.update_workshop(taller)

        taller = Taller(**taller_data)
        return await self.repo.create_workshop(taller)

    async def activar_desactivar_taller(self, current_user: Usuario, taller_id: uuid.UUID, activo: bool) -> Taller:
        await self.validar_permiso_global(current_user)
        taller = await self.repo.get_workshop(taller_id)
        if not taller:
            raise NotFoundError("Taller no encontrado.")
        taller.is_active = activo
        return await self.repo.update_workshop(taller)

    async def asignar_usuario_a_taller(
        self,
        current_user: Usuario,
        taller_id: uuid.UUID,
        id_usuario: uuid.UUID,
        rol_contexto: str = "miembro",
        id_sucursal: Optional[uuid.UUID] = None
    ) -> UsuarioTaller:
        await self.validar_permiso_global(current_user)

        taller = await self.repo.get_workshop(taller_id)
        if not taller:
            raise NotFoundError("Taller no encontrado.")

        usuario = await self.repo.get_user(id_usuario)
        if not usuario:
            raise NotFoundError("Usuario no encontrado.")

        if id_sucursal is not None:
            branch = await self.repo.get_branch(id_sucursal, taller_id)
            if not branch:
                raise BadRequestError("La sucursal especificada no pertenece a este taller.")

        existing_links = await self.repo.get_user_workshop_links(id_usuario)
        if any(link.id_taller == taller_id and link.rol_contexto == rol_contexto and link.estado for link in existing_links):
            raise ConflictError("El usuario ya está asignado a este taller con el mismo rol.")
        if any(link.id_taller and link.id_taller != taller_id and link.estado for link in existing_links):
            raise ConflictError("El usuario ya está asociado a otro taller. No se permiten asociaciones cruzadas.")

        user_taller = UsuarioTaller(
            id_usuario=id_usuario,
            id_taller=taller_id,
            id_sucursal=id_sucursal,
            rol_contexto=rol_contexto,
            estado=True
        )
        return await self.repo.add_user_to_workshop(user_taller)

    async def asociar_tecnico_a_taller(
        self,
        current_user: Usuario,
        taller_id: uuid.UUID,
        id_tecnico: uuid.UUID,
        id_sucursal: Optional[uuid.UUID] = None
    ) -> Tecnico:
        await self.validar_permiso_global(current_user)

        taller = await self.repo.get_workshop(taller_id)
        if not taller:
            raise NotFoundError("Taller no encontrado.")

        tecnico = await self.repo.get_technician(id_tecnico)
        if not tecnico:
            raise NotFoundError("Técnico no encontrado.")

        if id_sucursal is not None:
            branch = await self.repo.get_branch(id_sucursal, taller_id)
            if not branch:
                raise BadRequestError("La sucursal especificada no pertenece a este taller.")

        if tecnico.id_taller == taller_id and tecnico.id_sucursal == id_sucursal:
            raise ConflictError("El técnico ya está asociado a este taller y sucursal.")

        tecnico.id_taller = taller_id
        tecnico.id_sucursal = id_sucursal
        tecnico.estado = True
        return await self.repo.update_technician(tecnico)

    async def filtrar_informacion_por_taller(
        self,
        current_user: Usuario,
        taller_id: uuid.UUID,
        id_sucursal: Optional[uuid.UUID] = None,
        offset: int = 0,
        limit: int = 50
    ) -> list[Incidente]:
        await self.verificar_acceso_taller(current_user, taller_id)
        return await self.repo.get_incidents_by_workshop(taller_id, id_sucursal=id_sucursal, offset=offset, limit=limit)

    async def consultar_metricas_operacionales(
        self,
        current_user: Usuario,
        taller_id: uuid.UUID
    ) -> dict:
        await self.verificar_acceso_taller(current_user, taller_id)
        return await self.repo.get_operational_metrics(taller_id)

    async def consultar_bitacora_taller(
        self,
        current_user: Usuario,
        taller_id: uuid.UUID,
        offset: int = 0,
        limit: int = 50
    ) -> list[Bitacora]:
        await self.verificar_acceso_taller(current_user, taller_id)
        return await self.repo.get_bitacora_by_workshop(taller_id, offset=offset, limit=limit)

    async def verificar_aislamiento_informacion(
        self,
        current_user: Usuario,
        id_taller: Optional[uuid.UUID] = None,
        id_sucursal: Optional[uuid.UUID] = None
    ) -> dict:
        if current_user.rol_nombre == ROL_SUPERADMIN:
            return {
                "rol": current_user.rol_nombre,
                "id_taller": None,
                "id_sucursal": None,
                "puede_acceder": True,
                "mensaje": "SuperAdministrador con acceso global."
            }
        acceso = current_user.id_taller is not None and (
            id_taller is None or current_user.id_taller == id_taller
        )
        if id_sucursal is not None and current_user.id_sucursal is not None:
            acceso = acceso and current_user.id_sucursal == id_sucursal
        return {
            "rol": current_user.rol_nombre,
            "id_taller": current_user.id_taller,
            "id_sucursal": current_user.id_sucursal,
            "puede_acceder": acceso,
            "mensaje": "El usuario solo puede acceder a la información de su taller/tenant." if not acceso else "El aislamiento de información se cumple."
        }

    async def registrar_accion_bitacora(
        self,
        current_user: Usuario,
        accion: str,
        descripcion: str,
        taller_id: Optional[uuid.UUID] = None,
        id_sucursal_contexto: Optional[uuid.UUID] = None,
        id_sucursal_afectada: Optional[uuid.UUID] = None,
        tipo_entidad: Optional[str] = None,
        id_entidad: Optional[uuid.UUID] = None,
        datos_antes: Optional[dict] = None,
        datos_despues: Optional[dict] = None
    ) -> Bitacora:
        bitacora = Bitacora(
            id_usuario_actor=current_user.id_usuario,
            rol_usuario=current_user.rol_nombre,
            id_taller=taller_id,
            id_sucursal_contexto=id_sucursal_contexto,
            id_sucursal_afectada=id_sucursal_afectada,
            tipo_entidad=tipo_entidad,
            id_entidad=id_entidad,
            ip="unknown",
            accion=accion,
            descripcion=descripcion,
            datos_antes=datos_antes,
            datos_despues=datos_despues
        )
        return await self.repo.create_bitacora_entry(bitacora)
