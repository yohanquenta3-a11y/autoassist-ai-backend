from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload, selectinload
from typing import Optional, List
import uuid

from app.packages.emergencies.domain.models import Incidente, EvidenciaIncidente, HistorialIncidente
from app.packages.identity.domain.models import Vehiculo


class IncidentRepository:
    """Operaciones de BD para Incidentes y sus Evidencias."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # --- Incidente ---

    async def create_incident(self, incidente: Incidente) -> Incidente:
        self.session.add(incidente)
        await self.session.commit()
        # Recargamos con las relaciones necesarias para la respuesta
        return await self.get_by_id(incidente.id_incidente)

    async def get_by_id(self, incident_id: uuid.UUID) -> Optional[Incidente]:
        result = await self.session.execute(
            select(Incidente)
            .options(
                joinedload(Incidente.vehiculo).joinedload(Vehiculo.propietario),
                joinedload(Incidente.taller),
                joinedload(Incidente.tecnico),
                selectinload(Incidente.evidencias),
                selectinload(Incidente.historial)
            )
            .where(Incidente.id_incidente == incident_id)
        )
        return result.scalars().first()

    async def update_incident(self, incidente: Incidente) -> Incidente:
        self.session.add(incidente)
        await self.session.commit()
        return await self.get_by_id(incidente.id_incidente)

    async def cancel_incident(self, incident_id: uuid.UUID, actor: str = "CLIENTE") -> Optional[Incidente]:
        # Buscamos el incidente inicial para saber de quién es
        incidente_target = await self.get_by_id(incident_id)
        if not incidente_target or not incidente_target.vehiculo:
            return None
        
        user_id = incidente_target.vehiculo.id_usuario
        
        # Buscamos TODOS los incidentes activos de este usuario
        from app.packages.identity.domain.models import Vehiculo
        from sqlalchemy.orm import joinedload, selectinload
        result = await self.session.execute(
            select(Incidente)
            .join(Vehiculo)
            .options(
                joinedload(Incidente.tecnico),
                selectinload(Incidente.historial)
            )
            .where(Vehiculo.id_usuario == user_id)
            .where(Incidente.estado_incidente.notin_(["FINALIZADO", "CANCELADO", "COMPLETADO"]))
        )
        activos = result.scalars().all()
        
        for inc in activos:
            estado_anterior = inc.estado_incidente
            inc.estado_incidente = "CANCELADO"
            if inc.tecnico:
                inc.tecnico.estado = True
                
            historial = HistorialIncidente(
                id_incidente=inc.id_incidente,
                incidente_estado_anterior=estado_anterior,
                incidente_estado_nuevo="CANCELADO",
                historial_actor=actor,
                fecha=None
            )
            inc.historial.append(historial)
        
        await self.session.commit()
        return incidente_target

    async def get_by_workshop(self, taller_id: uuid.UUID) -> List[Incidente]:
        """Obtiene la lista de incidentes asignados a un taller."""
        result = await self.session.execute(
            select(Incidente)
            .options(
                joinedload(Incidente.vehiculo),
                joinedload(Incidente.taller),
                joinedload(Incidente.tecnico),
                selectinload(Incidente.evidencias),
                selectinload(Incidente.historial)
            )
            .where(Incidente.id_taller == taller_id)
            .order_by(Incidente.fecha_reporte.desc())
        )
        return result.scalars().all()

    async def get_all(self) -> List[Incidente]:
        """Obtiene todos los incidentes del sistema (SuperAdmin)."""
        result = await self.session.execute(
            select(Incidente)
            .options(
                joinedload(Incidente.vehiculo),
                joinedload(Incidente.taller),
                joinedload(Incidente.tecnico),
                selectinload(Incidente.evidencias),
                selectinload(Incidente.historial)
            )
            .order_by(Incidente.fecha_reporte.desc())
        )
        return result.scalars().all()

    async def get_active_by_user(self, user_id: uuid.UUID) -> Optional[Incidente]:
        """Obtiene el incidente más reciente de un usuario que no esté finalizado o cancelado."""
        result = await self.session.execute(
            select(Incidente)
            .join(Vehiculo)
            .options(
                joinedload(Incidente.vehiculo),
                joinedload(Incidente.taller),
                joinedload(Incidente.tecnico),
                selectinload(Incidente.evidencias),
                selectinload(Incidente.historial)
            )
            .where(Vehiculo.id_usuario == user_id)
            .where(Incidente.estado_incidente.notin_(["FINALIZADO", "CANCELADO", "COMPLETADO"]))
            .order_by(Incidente.fecha_reporte.desc())
        )
        return result.scalars().first()

    async def get_history_by_user(self, user_id: uuid.UUID) -> List[Incidente]:
        """Obtiene el historial completo de incidentes de un usuario."""
        import logging
        logging.getLogger("app").info(f"DEBUG: Obteniendo historial para user_id: {user_id}")
        result = await self.session.execute(
            select(Incidente)
            .join(Vehiculo, Incidente.id_vehiculo == Vehiculo.id_vehiculo)
            .options(
                joinedload(Incidente.vehiculo),
                joinedload(Incidente.taller),
                joinedload(Incidente.tecnico),
                selectinload(Incidente.evidencias),
                selectinload(Incidente.historial)
            )
            .where(Vehiculo.id_usuario == user_id)
            .order_by(Incidente.fecha_reporte.desc())
        )
        return result.scalars().unique().all()

    # --- Evidencias ---

    async def add_evidence(self, evidencia: EvidenciaIncidente) -> EvidenciaIncidente:
        self.session.add(evidencia)
        await self.session.commit()
        await self.session.refresh(evidencia)
        return evidencia

    async def get_evidences_by_incident(self, incident_id: uuid.UUID) -> List[EvidenciaIncidente]:
        result = await self.session.execute(
            select(EvidenciaIncidente).where(EvidenciaIncidente.id_incidente == incident_id)
        )
        return result.scalars().all()

    # --- Historial ---

    async def add_history(self, historial: HistorialIncidente) -> HistorialIncidente:
        self.session.add(historial)
        await self.session.commit()
        await self.session.refresh(historial)
        return historial
