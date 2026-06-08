from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.packages.admin.application.tenant_management import TenantManagementService


async def get_admin_service(db: AsyncSession = Depends(get_db)) -> TenantManagementService:
    return TenantManagementService(db)
