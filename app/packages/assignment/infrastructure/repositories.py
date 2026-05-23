from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from geoalchemy2.functions import ST_Distance, ST_DWithin
from typing import List, Tuple
import uuid

from app.packages.assignment.domain.models import AsignacionIncidente
from app.packages.workshops.domain.models import Taller, CATEGORIA_MECANICA_GENERAL

class AssignmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_nearby_workshops(
        self, 
        point, 
        radius_km: float = 10.0, 
        limit: int = 5,
        required_specialty: str = None,
        exclude_ids: List[uuid.UUID] = None
    ) -> List[Tuple[Taller, float]]:
        """
        Busca talleres cercanos a un punto geográfico (Geography).
        Retorna una lista de tuplas (Taller, distancia_metros).
        """
        # Distancia en metros para ST_DWithin
        radius_meters = radius_km * 1000
        
        from sqlalchemy.orm import joinedload
        from app.packages.workshops.domain.models import AdministradorTaller
        
        # Consulta base
        query = select(
            Taller, 
            ST_Distance(Taller.ubicacion, point).label("distance")
        ).options(
            joinedload(Taller.administradores).joinedload(AdministradorTaller.usuario)
        ).where(
            and_(
                Taller.is_active == True,
                ST_DWithin(Taller.ubicacion, point, radius_meters)
            )
        )
        
        if exclude_ids:
            query = query.where(Taller.id_taller.not_in(exclude_ids))
        
        # Filtro de especialidad (Si se requiere)
        # En una versión avanzada, uniríamos con TallerCategoriaServicio
        # Por ahora, filtramos por talleres activos.
        
        query = query.order_by("distance").limit(limit)
        
        result = await self.session.execute(query)
        # Usamos unique() porque joinedload con columnas adicionales puede generar filas "duplicadas" en el result set
        return result.unique().all()

    async def create_assignment(self, assignment: AsignacionIncidente) -> AsignacionIncidente:
        self.session.add(assignment)
        await self.session.commit()
        await self.session.refresh(assignment)
        return assignment

    async def get_by_id(self, id_asignacion: uuid.UUID) -> AsignacionIncidente:
        result = await self.session.execute(
            select(AsignacionIncidente).where(AsignacionIncidente.id_asignacion == id_asignacion)
        )
        return result.scalars().first()
