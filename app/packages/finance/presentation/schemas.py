from pydantic import BaseModel, ConfigDict
from decimal import Decimal
import uuid
from typing import Optional
from datetime import datetime

class PaymentCreate(BaseModel):
    monto_total: Decimal

class BillingCreate(BaseModel):
    monto_total: Decimal
    mano_de_obra: Optional[Decimal] = None
    repuestos: Optional[Decimal] = None
    observaciones: Optional[str] = None

class PaymentResponse(BaseModel):
    id_pago: uuid.UUID
    id_incidente: uuid.UUID
    id_taller: uuid.UUID
    monto: Decimal
    monto_comision: Decimal
    estado_pago: str
    fecha_pago: Optional[datetime]
    mano_de_obra: Optional[Decimal] = None
    repuestos: Optional[Decimal] = None
    observaciones: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

