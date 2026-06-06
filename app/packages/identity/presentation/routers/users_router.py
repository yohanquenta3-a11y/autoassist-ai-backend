from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.packages.identity.domain.models import Usuario, ROL_SUPERADMIN, ROL_ADMIN_TALLER, ROL_CLIENTE
from app.packages.identity.infrastructure.repositories import UserRepository
from app.packages.identity.presentation.schemas.auth_schemas import UserResponse, UserAdminCreate
from app.packages.identity.presentation.schemas.auth_schemas import UserResponse, UserAdminCreate
from app.packages.identity.presentation.schemas.user_schemas import UserProfileUpdate, VehicleCreate, VehicleResponse
from app.packages.identity.application.user_use_cases.update_profile import UpdateProfileUseCase
from app.packages.identity.application.user_use_cases.register_vehicle import RegisterVehicleUseCase
from app.packages.identity.application.user_use_cases.create_user_admin import CreateUserAdminUseCase
from app.packages.identity.application.user_use_cases.create_user_admin import CreateUserAdminUseCase
from app.packages.workshops.infrastructure.repositories import WorkshopRepository
from app.packages.workshops.dependencies import get_selected_branch_id
from app.core.exceptions import ForbiddenError, NotFoundError
import uuid
from typing import Optional

users_router = APIRouter(tags=["Gestión de Usuarios y Perfiles"])

def get_user_repository(session: AsyncSession = Depends(get_db)):
    return UserRepository(session)

def get_workshop_repository(session: AsyncSession = Depends(get_db)):
    return WorkshopRepository(session)

@users_router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user_admin(
    user_in: UserAdminCreate,
    current_user: Usuario = Depends(get_current_active_user),
    user_repo: UserRepository = Depends(get_user_repository),
    workshop_repo: WorkshopRepository = Depends(get_workshop_repository)
):
    """
    (Admin) Crear un nuevo usuario manualmente.
    - SuperAdmin: Puede crear cualquier rol en cualquier taller.
    - Owner (admin_taller en contexto owner): Puede crear admin_taller, tecnico y cliente.
    - AdminTaller (admin_taller en contexto admin_sucursal): Solo puede crear tecnico y cliente.
    """
    if current_user.rol_nombre not in [ROL_SUPERADMIN, ROL_ADMIN_TALLER]:
        raise ForbiddenError("No tienes permisos para crear usuarios.")

    # Restricciones Multi-tenant para Admin de Taller / Owner
    if current_user.rol_nombre == ROL_ADMIN_TALLER:
        if current_user.rol_contexto == "owner":
            # Owner puede crear admin_taller, tecnico, cliente
            if user_in.rol_nombre not in ["admin_taller", "tecnico", "cliente"]:
                raise ForbiddenError("Como Owner, solo puedes crear administradores de taller, técnicos y clientes.")
        elif current_user.rol_contexto == "admin_sucursal":
            # Admin de Sucursal solo puede crear tecnico y cliente
            if user_in.rol_nombre not in ["tecnico", "cliente"]:
                raise ForbiddenError("Como Administrador de Sucursal, solo puedes crear técnicos y clientes.")
        else:
            raise ForbiddenError("No tienes permisos contextuales en este taller.")
        
        if not current_user.id_taller:
            raise ForbiddenError("No estás asociado a ningún taller activo.")
        
        # Forzar que el taller sea el del creador
        user_in.id_taller = current_user.id_taller

    use_case = CreateUserAdminUseCase(user_repo, workshop_repo)
    return await use_case.execute(
        user_in,
        creator_context=current_user.rol_contexto,
        creator_sucursal_id=current_user.id_sucursal
    )

@users_router.get("", response_model=List[UserResponse])
async def list_users(
    role: Optional[str] = None,
    id_taller: Optional[uuid.UUID] = None,
    current_user: Usuario = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    selected_branch_id: Optional[uuid.UUID] = Depends(get_selected_branch_id)
):
    """
    (Admin) Listado de usuarios con filtros globales y multi-tenant.
    - SuperAdmin: Puede filtrar por cualquier taller.
    - AdminTaller: Solo puede ver usuarios vinculados a SU taller.
    """
    if current_user.rol_nombre not in [ROL_SUPERADMIN, ROL_ADMIN_TALLER]:
        raise ForbiddenError("No tienes permisos para acceder a la gestión de usuarios.")

    user_repo = UserRepository(db)
    workshop_repo = WorkshopRepository(db)

    # Lógica Multi-tenant
    if current_user.rol_nombre == ROL_ADMIN_TALLER:
        taller = await workshop_repo.get_by_admin(current_user.id_usuario)
        if not taller:
            raise ForbiddenError("No tienes un taller vinculado para gestionar usuarios.")
        # Forzamos el filtro a su taller
        id_taller = taller.id_taller

    return await user_repo.get_all_with_filters(role=role, workshop_id=id_taller, branch_id=selected_branch_id)

@users_router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: Usuario = Depends(get_current_active_user)):
    """Visulizar Perfil: Retorna el usuario extraído del JWT."""
    return current_user

@users_router.put("/me", response_model=UserResponse)
async def update_users_me(
    profile_in: UserProfileUpdate,
    current_user: Usuario = Depends(get_current_active_user),
    repo: UserRepository = Depends(get_user_repository)
):
    """(CU3) Gestionar Perfil: Actualizar información personal del usuario JWT."""
    use_case = UpdateProfileUseCase(repo)
    updated_user = await use_case.execute(current_user, profile_in)
    return updated_user

@users_router.post("/me/vehicles", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
async def create_vehicle_for_me(
    vehicle_in: VehicleCreate,
    current_user: Usuario = Depends(get_current_active_user),
    repo: UserRepository = Depends(get_user_repository)
):
    """(CU4) Registrar Vehículo: Agrega un vehículo al garaje del cliente autenticado JWT."""
    use_case = RegisterVehicleUseCase(repo)
    vehicle = await use_case.execute(current_user, vehicle_in)
    return vehicle

@users_router.get("/me/vehicles", response_model=List[VehicleResponse])
async def list_my_vehicles(
    current_user: Usuario = Depends(get_current_active_user),
    repo: UserRepository = Depends(get_user_repository)
):
    """Consultar Vehículos: Retorna toda la flota del cliente."""
    return await repo.get_vehicles_by_user(current_user.id_usuario)

@users_router.get("/{user_id}/vehicles", response_model=List[VehicleResponse])
async def list_user_vehicles(
    user_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    repo: UserRepository = Depends(get_user_repository),
    workshop_repo: WorkshopRepository = Depends(get_workshop_repository)
):
    """(Admin) Consulta los vehÃ­culos de un cliente para crear citas directas."""
    if current_user.rol_nombre not in [ROL_SUPERADMIN, ROL_ADMIN_TALLER]:
        raise ForbiddenError("No tienes permisos para consultar vehÃ­culos de otros usuarios.")

    target_user = await repo.get_by_id(user_id)
    if not target_user or target_user.rol_nombre != ROL_CLIENTE:
        raise NotFoundError("Cliente no encontrado.")

    if current_user.rol_nombre == ROL_ADMIN_TALLER:
        taller = await workshop_repo.get_by_admin(current_user.id_usuario)
        if not taller:
            raise ForbiddenError("No tienes un taller vinculado para consultar vehÃ­culos.")
        relation = await workshop_repo.get_user_taller_by_user(user_id)
        if not relation or relation.id_taller != taller.id_taller:
            raise ForbiddenError("No puedes consultar vehÃ­culos de clientes de otro taller.")

    return await repo.get_vehicles_by_user(user_id)

@users_router.put("/me/vehicles/{vehicle_id}", response_model=VehicleResponse)
async def update_my_vehicle(
    vehicle_id: uuid.UUID,
    vehicle_in: VehicleCreate,
    current_user: Usuario = Depends(get_current_active_user),
    repo: UserRepository = Depends(get_user_repository)
):
    """Actualizar Vehículo: Modifica los datos de un vehículo propio."""
    vehicle = await repo.get_vehicle_by_id(vehicle_id)
    if not vehicle or vehicle.id_usuario != current_user.id_usuario:
        raise NotFoundError("Vehículo no encontrado o no pertenece al usuario.")
    
    vehicle.matricula = vehicle_in.matricula
    vehicle.marca = vehicle_in.marca
    vehicle.modelo = vehicle_in.modelo
    vehicle.ano = vehicle_in.ano
    vehicle.color = vehicle_in.color
    
    return await repo.update_vehicle(vehicle)

@users_router.delete("/me/vehicles/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_vehicle(
    vehicle_id: uuid.UUID,
    current_user: Usuario = Depends(get_current_active_user),
    repo: UserRepository = Depends(get_user_repository)
):
    """Eliminar Vehículo: Borra un vehículo del garaje del cliente."""
    vehicle = await repo.get_vehicle_by_id(vehicle_id)
    if not vehicle or vehicle.id_usuario != current_user.id_usuario:
        raise NotFoundError("Vehículo no encontrado o no pertenece al usuario.")
    
    await repo.delete_vehicle(vehicle)
    return None
