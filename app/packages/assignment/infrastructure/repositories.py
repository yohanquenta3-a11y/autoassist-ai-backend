from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from geoalchemy2.functions import ST_Distance, ST_DWithin
from typing import List, Tuple
import uuid

from app.packages.assignment.domain.models import AsignacionIncidente
from app.packages.workshops.domain.models import Taller, SucursalTaller, CATEGORIA_MECANICA_GENERAL

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
    ) -> List[Tuple[SucursalTaller, float]]:
        """
        Busca sucursales de talleres cercanas a un punto geográfico (Geography).
        Retorna una lista de tuplas (SucursalTaller, distancia_metros).
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Distancia en metros para ST_DWithin
        radius_meters = radius_km * 1000
        
        from sqlalchemy.orm import joinedload
        from app.packages.workshops.domain.models import SucursalTaller, Taller, AdministradorTaller
        
        # 1. Logear advertencias sobre sucursales activas sin ubicación configurada
        try:
            no_loc_query = select(SucursalTaller).join(Taller).where(
                and_(
                    SucursalTaller.is_active == True,
                    Taller.is_active == True,
                    SucursalTaller.ubicacion.is_(None)
                )
            )
            no_loc_res = await self.session.execute(no_loc_query)
            no_loc_branches = no_loc_res.scalars().all()
            for branch in no_loc_branches:
                logger.warning(
                    f"⚠️ CONFIG: La sucursal '{branch.nombre}' (ID: {branch.id_sucursal}) "
                    f"del taller '{branch.taller.nombre if branch.taller else branch.id_taller}' está ACTIVA "
                    f"pero no tiene coordenadas físicas (ubicacion es null). No participará en la asignación."
                )
        except Exception as e:
            logger.error(f"Error al verificar sucursales sin ubicacion: {e}")

        # 2. Búsqueda de sucursales cercanas con ubicacion válida
        query = select(
            SucursalTaller, 
            ST_Distance(SucursalTaller.ubicacion, point).label("distance")
        ).join(
            Taller, SucursalTaller.id_taller == Taller.id_taller
        ).options(
            joinedload(SucursalTaller.taller).joinedload(Taller.administradores).joinedload(AdministradorTaller.usuario)
        ).where(
            and_(
                SucursalTaller.is_active == True,
                Taller.is_active == True,
                SucursalTaller.ubicacion.is_not(None),
                ST_DWithin(SucursalTaller.ubicacion, point, radius_meters)
            )
        )
        
        if exclude_ids:
            query = query.where(SucursalTaller.id_taller.notin_(exclude_ids))
        
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

    async def get_by_incident(self, id_incidente: uuid.UUID) -> AsignacionIncidente:
        result = await self.session.execute(
            select(AsignacionIncidente)
            .where(AsignacionIncidente.id_incidente == id_incidente)
            .order_by(AsignacionIncidente.fecha_asignacion.desc())
        )
        return result.scalars().first()
