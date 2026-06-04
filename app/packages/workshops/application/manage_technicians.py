import uuid
from typing import Optional
from app.packages.workshops.infrastructure.repositories import WorkshopRepository
from app.packages.identity.infrastructure.repositories import UserRepository
from app.packages.workshops.domain.models import Tecnico
from app.packages.identity.domain.models import Usuario, ROL_TECNICO
from app.packages.workshops.presentation.schemas import TecnicoCreate
from app.core.security import get_password_hash
from app.core.exceptions import ForbiddenError, NotFoundError, ConflictError

class ManageTechniciansUseCase:
    def __init__(self, workshop_repo: WorkshopRepository, user_repo: UserRepository):
        self.workshop_repo = workshop_repo
        self.user_repo = user_repo

    async def add_technician(self, admin_user: Usuario, tecnico_in: TecnicoCreate, id_sucursal: Optional[uuid.UUID] = None) -> Tecnico:
        # 1. Obtener el taller del administrador
        taller = await self.workshop_repo.get_by_admin(admin_user.id_usuario)
        if not taller:
            raise ForbiddenError("No tienes un taller registrado para agregar técnicos.")

        # 2. Verificar si el correo ya existe
        existing_user = await self.user_repo.get_by_email(tecnico_in.correo)
        if existing_user:
            raise ConflictError(f"El correo {tecnico_in.correo} ya está en uso.")

        # 3. Crear el Usuario para el mecánico
        rol_tecnico = await self.user_repo.get_rol_by_nombre(ROL_TECNICO)
        if not rol_tecnico:
             raise NotFoundError("El rol 'tecnico' no existe en el sistema.")

        import secrets
        import string

        # Generar contraseña temporal aleatoria de 8 caracteres
        alphabet = string.ascii_letters + string.digits
        temp_pass = ''.join(secrets.choice(alphabet) for _ in range(8))

        new_user = Usuario(
            id_usuario=uuid.uuid4(),
            id_rol=rol_tecnico.id_rol,
            nombre=tecnico_in.nombre,
            correo=tecnico_in.correo,
            telefono=tecnico_in.telefono,
            contrasena=get_password_hash(temp_pass), # Password temporal aleatoria
            estado=True
        )
        created_user = await self.user_repo.create_user(new_user)

        # 4. Crear el registro de Técnico
        new_tecnico = Tecnico(
            id_tecnico=uuid.uuid4(),
            id_usuario=created_user.id_usuario,
            id_taller=taller.id_taller,
            id_sucursal=id_sucursal,
            nombre=tecnico_in.nombre,
            telefono=tecnico_in.telefono,
            estado=True
        )
        saved_tecnico = await self.workshop_repo.create_technician(new_tecnico)
        # Adjuntar para que Pydantic lo serialice en el response
        saved_tecnico.temp_password = temp_pass
        return saved_tecnico

    async def list_technicians(self, admin_user: Usuario, id_sucursal: Optional[uuid.UUID] = None) -> list[Tecnico]:
        taller = await self.workshop_repo.get_by_admin(admin_user.id_usuario)
        if not taller:
            raise ForbiddenError("No tienes un taller registrado.")
        
        return await self.workshop_repo.get_technicians_by_workshop(taller.id_taller, id_sucursal=id_sucursal)
