import uuid
from app.packages.identity.infrastructure.repositories import UserRepository
from app.packages.identity.presentation.schemas.auth_schemas import UserAdminCreate
from app.packages.identity.domain.models import Usuario
from app.packages.workshops.infrastructure.repositories import WorkshopRepository
from app.packages.workshops.domain.models import AdministradorTaller, Tecnico
from app.core.security import get_password_hash
from app.core.exceptions import ConflictError, NotFoundError

class CreateUserAdminUseCase:
    def __init__(self, user_repo: UserRepository, workshop_repo: WorkshopRepository):
        self.user_repo = user_repo
        self.workshop_repo = workshop_repo

    async def execute(self, user_in: UserAdminCreate) -> Usuario:
        # 1. Validar correo único
        existing = await self.user_repo.get_by_email(user_in.correo)
        if existing:
            raise ConflictError("El correo electrónico ya está en uso.")

        # 2. Buscar Rol
        rol = await self.user_repo.get_rol_by_nombre(user_in.rol_nombre)
        if not rol:
            raise NotFoundError(f"El rol '{user_in.rol_nombre}' no existe.")

        # 3. Crear Usuario
        new_user = Usuario(
            nombre=user_in.nombre,
            correo=user_in.correo,
            telefono=user_in.telefono,
            contrasena=get_password_hash(user_in.contrasena),
            id_rol=rol.id_rol
        )
        user = await self.user_repo.create_user(new_user)

        # 4. Lógica de vinculación a taller si aplica
        if user_in.rol_nombre == "admin_taller" and user_in.id_taller:
            admin_link = AdministradorTaller(
                id_usuario=user.id_usuario,
                id_taller=user_in.id_taller
            )
            await self.workshop_repo.link_admin(admin_link)
            
        elif user_in.rol_nombre == "tecnico" and user_in.id_taller:
            tecnico = Tecnico(
                id_usuario=user.id_usuario,
                id_taller=user_in.id_taller,
                nombre=user.nombre,
                telefono=user.telefono,
                estado=True
            )
            await self.workshop_repo.create_technician(tecnico)

        return user
