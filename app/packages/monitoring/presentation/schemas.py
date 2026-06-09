from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class GlobalStatsResponse(BaseModel):
    total_talleres: int
    total_incidentes: int
    total_comisiones: Decimal
    emergencias_activas: int


class OperationalScopeResponse(BaseModel):
    role: str
    id_taller: Optional[UUID] = None
    id_sucursal: Optional[UUID] = None
    is_global: bool


class LabelValueResponse(BaseModel):
    label: str
    value: int


class OperationalPerformancePointResponse(BaseModel):
    label: str
    total_incidentes: int
    finalizados: int
    cancelados: int
    cumplimiento_sla_pct: Optional[float] = None


class DensityPointResponse(BaseModel):
    latitud: float
    longitud: float
    cantidad_incidentes: int
    prioridad: Optional[str] = None
    estado: Optional[str] = None
    intensidad: float


class RankingItemResponse(BaseModel):
    label: str
    id_taller: Optional[UUID] = None
    id_sucursal: Optional[UUID] = None
    total_incidentes: int
    completados_pct: float
    cancelados_pct: float
    cumplimiento_sla_pct: float
    tiempo_promedio_llegada_min: Optional[float] = None
    tiempo_promedio_finalizacion_min: Optional[float] = None


class RecentActivityItemResponse(BaseModel):
    id_incidente: UUID
    cliente: Optional[str] = None
    vehiculo: Optional[str] = None
    taller: Optional[str] = None
    sucursal: Optional[str] = None
    estado: str
    prioridad: str
    fecha_reporte: Optional[str] = None
    resumen: Optional[str] = None


class OperationalDashboardSummaryResponse(BaseModel):
    total_incidentes: int
    incidentes_activos: int
    incidentes_finalizados: int
    incidentes_cancelados: int
    incidentes_no_atendidos: int
    tiempo_promedio_asignacion_min: Optional[float] = None
    tiempo_promedio_llegada_min: Optional[float] = None
    tiempo_promedio_finalizacion_min: Optional[float] = None
    cumplimiento_sla_pct: Optional[float] = None
    alertas_sla_activas: int


class OperationalDashboardSeriesResponse(BaseModel):
    rendimiento_operativo: list[OperationalPerformancePointResponse]
    incidentes_por_estado: list[LabelValueResponse]
    incidentes_por_prioridad: list[LabelValueResponse]
    incidentes_por_origen: list[LabelValueResponse]
    incidentes_por_tipo: list[LabelValueResponse]
    incidentes_por_sucursal: list[LabelValueResponse]
    incidentes_por_taller: list[LabelValueResponse]


class OperationalDashboardResponse(BaseModel):
    scope: OperationalScopeResponse
    summary: OperationalDashboardSummaryResponse
    series: OperationalDashboardSeriesResponse
    density: list[DensityPointResponse]
    ranking: list[RankingItemResponse]
    recent_activity: list[RecentActivityItemResponse]


class SlaAlertSummaryResponse(BaseModel):
    total_alertas: int
    en_riesgo: int
    incumplidas: int
    cumplidas: int
    sin_datos: int


class SlaAlertItemResponse(BaseModel):
    id_incidente: UUID
    tipo_alerta: str
    sla_status: str
    estado_actual: str
    tiempo_actual_min: Optional[float] = None
    limite_sla_min: Optional[float] = None
    tiempo_excedido_min: Optional[float] = None
    taller: Optional[str] = None
    sucursal: Optional[str] = None
    tecnico: Optional[str] = None
    prioridad: str
    fecha_reporte: Optional[str] = None
    ultimo_evento: Optional[str] = None


class SlaAlertsResponse(BaseModel):
    scope: OperationalScopeResponse
    summary: SlaAlertSummaryResponse
    alerts: list[SlaAlertItemResponse]
