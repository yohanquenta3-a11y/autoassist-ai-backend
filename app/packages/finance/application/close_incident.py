import uuid
from decimal import Decimal
from datetime import datetime
from app.packages.finance.infrastructure.repositories import FinanceRepository
from app.packages.emergencies.infrastructure.repositories import IncidentRepository
from app.packages.finance.domain.models import Pago
from app.packages.emergencies.domain.models import HistorialIncidente
from app.core.exceptions import NotFoundError, ForbiddenError

class CloseIncidentUseCase:
    """
    Caso de Uso (CU): Cierre y Pago del Incidente.
    Registra el pago final y marca el incidente como FINALIZADO.
    """
    
    def __init__(self, finance_repo: FinanceRepository, incident_repo: IncidentRepository):
        self.finance_repo = finance_repo
        self.incident_repo = incident_repo

    async def execute(self, id_taller: uuid.UUID, id_incidente: uuid.UUID, monto_total: Decimal):
        # 1. Validar incidente
        incidente = await self.incident_repo.get_by_id(id_incidente)
        if not incidente:
            raise NotFoundError("Incidente no encontrado.")
            
        if incidente.id_taller != id_taller:
            raise ForbiddenError("No puedes cerrar un incidente que no te pertenece.")

        # Idempotencia: Si ya está completado, retornar el pago existente
        if incidente.estado_incidente == "COMPLETADO":
            existing_pago = await self.finance_repo.get_payment_by_incident(id_incidente)
            if existing_pago:
                return existing_pago

        # 2. Buscar si ya existe un registro de pago (creado en la facturación)
        pago = await self.finance_repo.get_payment_by_incident(id_incidente)
        
        comision = monto_total * Decimal("0.10")
        
        if pago:
            pago.estado_pago = "PAGADO"
            pago.fecha_pago = datetime.utcnow()
            pago.monto = monto_total
            pago.monto_comision = comision
        else:
            pago = Pago(
                id_incidente=id_incidente,
                id_taller=id_taller,
                monto=monto_total,
                monto_comision=comision,
                estado_pago="PAGADO",
                fecha_pago=datetime.utcnow()
            )
        
        # 4. Actualizar incidente e Historial
        estado_anterior = incidente.estado_incidente
        incidente.estado_incidente = "COMPLETADO"
        
        # Liberar al técnico si existe
        if incidente.id_tecnico:
            from app.packages.workshops.domain.models import Tecnico
            from sqlalchemy.future import select
            result = await self.incident_repo.session.execute(
                select(Tecnico).where(Tecnico.id_tecnico == incidente.id_tecnico)
            )
            tecnico = result.scalar_one_or_none()
            if tecnico:
                tecnico.estado = True
                tecnico.estado_operativo = "DISPONIBLE"

        historial = HistorialIncidente(
            id_incidente=id_incidente,
            incidente_estado_anterior=estado_anterior,
            incidente_estado_nuevo="COMPLETADO",
            historial_actor="SISTEMA_FINANCIERO",
            fecha=None
        )
        incidente.historial.append(historial)
        
        await self.finance_repo.create_payment(pago)
        await self.incident_repo.session.commit()
        
        return pago
