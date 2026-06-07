from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Optional
from uuid import UUID

from geoalchemy2.shape import to_shape

from app.core.exceptions import ForbiddenError
from app.packages.emergencies.domain.models import HistorialIncidente, Incidente
from app.packages.identity.domain.models import ROL_ADMIN_TALLER, ROL_SUPERADMIN, Usuario
from app.packages.monitoring.infrastructure.operational_metrics_repository import OperationalMetricsRepository


FINAL_STATES = {"FINALIZADO", "COMPLETADO"}
CANCELLED_STATES = {"CANCELADO"}
ACTIVE_STATES = {
    "PENDIENTE",
    "ANALIZADO",
    "TALLER_ASIGNADO",
    "ASIGNADO",
    "EN_CAMINO",
    "TECNICO_EN_SITIO",
    "EN_ATENCION",
    "EN_PROGRESO",
    "TECNICO_RECHAZADO",
}

ASSIGNED_STATES = {"TALLER_ASIGNADO", "ASIGNADO"}
ONSITE_STATES = {"TECNICO_EN_SITIO"}
ATTENTION_STATES = {"EN_ATENCION", "EN_PROGRESO"}
COMPLETED_STATES = {"FINALIZADO", "COMPLETADO"}

SLA_LIMITS_MIN = {
    "RETRASO_ASIGNACION": 10,
    "RETRASO_LLEGADA": 30,
    "RETRASO_ATENCION": 10,
    "RETRASO_FINALIZACION": 120,
    "INCIDENTE_ESTANCADO": 45,
}
RISK_RATIO = 0.8


@dataclass
class OperationalScope:
    role: str
    id_taller: Optional[UUID]
    id_sucursal: Optional[UUID]
    is_global: bool


@dataclass
class IncidentStageTimes:
    assigned_at: Optional[datetime]
    en_camino_at: Optional[datetime]
    onsite_at: Optional[datetime]
    attention_at: Optional[datetime]
    completed_at: Optional[datetime]
    last_event_at: Optional[datetime]


def _safe_iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _minutes_between(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    if not start or not end:
        return None
    return round((_to_utc(end) - _to_utc(start)).total_seconds() / 60, 2)


def _average(values: list[Optional[float]]) -> Optional[float]:
    valid = [value for value in values if value is not None]
    if not valid:
        return None
    return round(sum(valid) / len(valid), 2)


def _workshop_name(incident: Incidente) -> str:
    if getattr(incident, "taller", None) and getattr(incident.taller, "nombre", None):
        return incident.taller.nombre
    return "Sin taller asignado"


def _branch_name(incident: Incidente) -> str:
    branch_name = getattr(incident, "branch_name", None)
    if branch_name:
        return branch_name
    if getattr(incident, "sucursal", None) and getattr(incident.sucursal, "nombre", None):
        return incident.sucursal.nombre
    return "Sin sucursal"


def _technician_name(incident: Incidente) -> Optional[str]:
    if getattr(incident, "tecnico", None) and getattr(incident.tecnico, "nombre", None):
        return incident.tecnico.nombre
    return None


def _customer_name(incident: Incidente) -> Optional[str]:
    vehicle = getattr(incident, "vehiculo", None)
    if vehicle and getattr(vehicle, "propietario", None) and getattr(vehicle.propietario, "nombre", None):
        return vehicle.propietario.nombre
    if getattr(incident, "cliente", None) and getattr(incident.cliente, "nombre", None):
        return incident.cliente.nombre
    return None


def _vehicle_label(incident: Incidente) -> Optional[str]:
    vehicle = getattr(incident, "vehiculo", None)
    if not vehicle:
        return None
    parts = [
        getattr(vehicle, "marca", None),
        getattr(vehicle, "modelo", None),
        getattr(vehicle, "matricula", None),
    ]
    compact = " ".join(str(part).strip() for part in parts if part)
    return compact or "Vehiculo sin detalle"


def _first_history_date(history: list[HistorialIncidente], states: set[str]) -> Optional[datetime]:
    ordered = sorted(history, key=lambda item: item.fecha or datetime.min)
    for item in ordered:
        if item.incidente_estado_nuevo in states:
            return item.fecha
    return None


def _extract_stage_times(incident: Incidente) -> IncidentStageTimes:
    history = list(incident.historial or [])
    assigned_at = _first_history_date(history, ASSIGNED_STATES)
    en_camino_at = _first_history_date(history, {"EN_CAMINO"})
    onsite_at = _first_history_date(history, ONSITE_STATES) or _first_history_date(history, ATTENTION_STATES)
    attention_at = _first_history_date(history, ATTENTION_STATES)
    completed_at = _first_history_date(history, COMPLETED_STATES)
    last_event_at = max((item.fecha for item in history if item.fecha), default=incident.fecha_reporte)
    return IncidentStageTimes(
        assigned_at=assigned_at,
        en_camino_at=en_camino_at,
        onsite_at=onsite_at,
        attention_at=attention_at,
        completed_at=completed_at,
        last_event_at=last_event_at,
    )


def _elapsed_minutes(start: Optional[datetime], now: datetime) -> Optional[float]:
    if not start:
        return None
    return round((_to_utc(now) - _to_utc(start)).total_seconds() / 60, 2)


def _evaluate_status(actual_min: Optional[float], limit_min: Optional[int], incident_completed: bool) -> str:
    if actual_min is None or limit_min is None:
        return "SIN_DATOS"
    if actual_min > limit_min:
        return "INCUMPLIDO"
    if not incident_completed and actual_min >= limit_min * RISK_RATIO:
        return "EN_RIESGO"
    return "CUMPLIDO"


def _build_incident_alerts(incident: Incidente, times: IncidentStageTimes, now: datetime) -> list[dict]:
    alerts: list[dict] = []
    completed = incident.estado_incidente in FINAL_STATES

    assign_actual = _minutes_between(incident.fecha_reporte, times.assigned_at) if times.assigned_at else _elapsed_minutes(incident.fecha_reporte, now)
    assign_status = _evaluate_status(assign_actual, SLA_LIMITS_MIN["RETRASO_ASIGNACION"], completed or times.assigned_at is not None)
    if assign_status != "CUMPLIDO":
        alerts.append(
            {
                "tipo_alerta": "RETRASO_ASIGNACION",
                "sla_status": assign_status,
                "tiempo_actual_min": assign_actual,
                "limite_sla_min": SLA_LIMITS_MIN["RETRASO_ASIGNACION"],
            }
        )

    if times.assigned_at:
        arrival_actual = _minutes_between(times.en_camino_at or times.assigned_at, times.onsite_at) if times.onsite_at else _elapsed_minutes(times.en_camino_at or times.assigned_at, now)
        arrival_status = _evaluate_status(arrival_actual, SLA_LIMITS_MIN["RETRASO_LLEGADA"], completed or times.onsite_at is not None)
        if arrival_status != "CUMPLIDO":
            alerts.append(
                {
                    "tipo_alerta": "RETRASO_LLEGADA",
                    "sla_status": arrival_status,
                    "tiempo_actual_min": arrival_actual,
                    "limite_sla_min": SLA_LIMITS_MIN["RETRASO_LLEGADA"],
                }
            )

    if times.onsite_at:
        attention_actual = _minutes_between(times.onsite_at, times.attention_at) if times.attention_at else _elapsed_minutes(times.onsite_at, now)
        attention_status = _evaluate_status(attention_actual, SLA_LIMITS_MIN["RETRASO_ATENCION"], completed or times.attention_at is not None)
        if attention_status != "CUMPLIDO":
            alerts.append(
                {
                    "tipo_alerta": "RETRASO_ATENCION",
                    "sla_status": attention_status,
                    "tiempo_actual_min": attention_actual,
                    "limite_sla_min": SLA_LIMITS_MIN["RETRASO_ATENCION"],
                }
            )

    if times.attention_at:
        finish_actual = _minutes_between(times.attention_at, times.completed_at) if times.completed_at else _elapsed_minutes(times.attention_at, now)
        finish_status = _evaluate_status(finish_actual, SLA_LIMITS_MIN["RETRASO_FINALIZACION"], completed or times.completed_at is not None)
        if finish_status != "CUMPLIDO":
            alerts.append(
                {
                    "tipo_alerta": "RETRASO_FINALIZACION",
                    "sla_status": finish_status,
                    "tiempo_actual_min": finish_actual,
                    "limite_sla_min": SLA_LIMITS_MIN["RETRASO_FINALIZACION"],
                }
            )

    if incident.estado_incidente in {"PENDIENTE", "ANALIZADO"} and not times.assigned_at:
        alerts.append(
            {
                "tipo_alerta": "SIN_TECNICO_ASIGNADO",
                "sla_status": assign_status,
                "tiempo_actual_min": assign_actual,
                "limite_sla_min": SLA_LIMITS_MIN["RETRASO_ASIGNACION"],
            }
        )

    if incident.estado_incidente in ACTIVE_STATES and times.last_event_at:
        stagnant_min = _elapsed_minutes(times.last_event_at, now)
        stagnant_status = _evaluate_status(stagnant_min, SLA_LIMITS_MIN["INCIDENTE_ESTANCADO"], False)
        if stagnant_status in {"EN_RIESGO", "INCUMPLIDO"}:
            alerts.append(
                {
                    "tipo_alerta": "INCIDENTE_ESTANCADO",
                    "sla_status": stagnant_status,
                    "tiempo_actual_min": stagnant_min,
                    "limite_sla_min": SLA_LIMITS_MIN["INCIDENTE_ESTANCADO"],
                }
            )

    if incident.estado_incidente in CANCELLED_STATES:
        alerts.append(
            {
                "tipo_alerta": "CANCELACION_OPERATIVA",
                "sla_status": "INCUMPLIDO",
                "tiempo_actual_min": None,
                "limite_sla_min": None,
            }
        )

    return alerts


async def resolve_operational_scope(
    *,
    repository: OperationalMetricsRepository,
    current_user: Usuario,
    requested_taller_id: Optional[UUID],
    selected_branch_id: Optional[UUID],
    requested_branch_id: Optional[UUID],
) -> OperationalScope:
    role = current_user.rol_nombre
    if role == ROL_SUPERADMIN:
        return OperationalScope(
            role="SUPERADMIN",
            id_taller=requested_taller_id,
            id_sucursal=requested_branch_id if requested_taller_id else None,
            is_global=requested_taller_id is None and requested_branch_id is None,
        )

    id_taller, id_sucursal, rol_contexto = await repository.get_user_operational_context(current_user.id_usuario)
    if not id_taller:
        raise ForbiddenError("No se encontro un contexto operativo para el usuario.")

    if rol_contexto == "admin_sucursal":
        return OperationalScope(
            role="ADMIN_SUCURSAL",
            id_taller=id_taller,
            id_sucursal=id_sucursal,
            is_global=False,
        )

    if rol_contexto == "owner" or role == ROL_ADMIN_TALLER:
        return OperationalScope(
            role="OWNER",
            id_taller=id_taller,
            id_sucursal=selected_branch_id,
            is_global=selected_branch_id is None,
        )

    raise ForbiddenError("El rol actual no tiene acceso al dashboard operacional.")


async def build_operational_dashboard(
    *,
    repository: OperationalMetricsRepository,
    scope: OperationalScope,
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    estado: Optional[str],
    prioridad: Optional[str],
    origen: Optional[str],
) -> dict:
    incidents = await repository.get_incidents(
        date_from=date_from,
        date_to=date_to,
        id_taller=scope.id_taller,
        id_sucursal=scope.id_sucursal,
        estado=estado,
        prioridad=prioridad,
        origen=origen,
    )
    now = datetime.now(UTC)

    assignment_times: list[Optional[float]] = []
    arrival_times: list[Optional[float]] = []
    completion_times: list[Optional[float]] = []
    active_alerts = 0
    sla_passed = 0
    sla_total = 0

    status_counter = Counter()
    priority_counter = Counter()
    origin_counter = Counter()
    branch_counter = Counter()
    workshop_counter = Counter()
    performance_buckets: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {
            "total_incidentes": 0,
            "finalizados": 0,
            "cancelados": 0,
            "sla_passed": 0,
            "sla_total": 0,
        }
    )
    ranking_buckets: dict[str, dict] = {}
    density_buckets: dict[tuple[float, float], dict] = {}
    recent_activity = []

    for incident in incidents:
        times = _extract_stage_times(incident)
        alerts = _build_incident_alerts(incident, times, now)
        alert_statuses = {item["sla_status"] for item in alerts if item["sla_status"] != "SIN_DATOS"}

        assignment_min = _minutes_between(incident.fecha_reporte, times.assigned_at)
        arrival_min = _minutes_between(times.en_camino_at or times.assigned_at, times.onsite_at) if times.onsite_at and (times.en_camino_at or times.assigned_at) else None
        completion_min = _minutes_between(times.attention_at, times.completed_at) if times.attention_at and times.completed_at else None

        assignment_times.append(assignment_min)
        arrival_times.append(arrival_min)
        completion_times.append(completion_min)

        if any(status in {"EN_RIESGO", "INCUMPLIDO"} for status in alert_statuses):
            active_alerts += 1
        if "INCUMPLIDO" not in alert_statuses:
            sla_passed += 1
        sla_total += 1

        status_counter[incident.estado_incidente] += 1
        priority_counter[incident.prioridad_incidente] += 1
        origin_counter[incident.origen or incident.origen_registro or "SOS"] += 1
        branch_counter[_branch_name(incident)] += 1
        workshop_counter[_workshop_name(incident)] += 1

        bucket_label = (
            _workshop_name(incident) if scope.role == "SUPERADMIN"
            else _branch_name(incident)
        )
        bucket_key = (
            str(incident.id_taller) if scope.role == "SUPERADMIN"
            else str(incident.id_sucursal or incident.id_taller or incident.id_incidente)
        )
        ranking_bucket = ranking_buckets.setdefault(
            bucket_key,
            {
                "label": bucket_label,
                "id_taller": incident.id_taller,
                "id_sucursal": incident.id_sucursal,
                "total": 0,
                "completed": 0,
                "cancelled": 0,
                "arrival_times": [],
                "completion_times": [],
                "sla_passed": 0,
                "sla_total": 0,
            },
        )
        ranking_bucket["total"] += 1
        if incident.estado_incidente in FINAL_STATES:
            ranking_bucket["completed"] += 1
        if incident.estado_incidente in CANCELLED_STATES:
            ranking_bucket["cancelled"] += 1
        if arrival_min is not None:
            ranking_bucket["arrival_times"].append(arrival_min)
        if completion_min is not None:
            ranking_bucket["completion_times"].append(completion_min)
        if "INCUMPLIDO" not in alert_statuses:
            ranking_bucket["sla_passed"] += 1
        ranking_bucket["sla_total"] += 1

        performance_key = incident.fecha_reporte.strftime("%Y-%m-%d")
        perf = performance_buckets[performance_key]
        perf["total_incidentes"] += 1
        if incident.estado_incidente in FINAL_STATES:
            perf["finalizados"] += 1
        if incident.estado_incidente in CANCELLED_STATES:
            perf["cancelados"] += 1
        if "INCUMPLIDO" not in alert_statuses:
            perf["sla_passed"] += 1
        perf["sla_total"] += 1

        if incident.ubicacion_emergencia is not None:
            try:
                point = to_shape(incident.ubicacion_emergencia)
                key = (round(point.y, 3), round(point.x, 3))
                density = density_buckets.setdefault(
                    key,
                    {
                        "latitud": round(point.y, 3),
                        "longitud": round(point.x, 3),
                        "cantidad_incidentes": 0,
                        "prioridad": incident.prioridad_incidente,
                        "estado": incident.estado_incidente,
                    },
                )
                density["cantidad_incidentes"] += 1
            except Exception:
                pass

        recent_activity.append(
            {
                "id_incidente": incident.id_incidente,
                "cliente": _customer_name(incident),
                "vehiculo": _vehicle_label(incident),
                "taller": _workshop_name(incident),
                "sucursal": _branch_name(incident),
                "estado": incident.estado_incidente,
                "prioridad": incident.prioridad_incidente,
                "fecha_reporte": _safe_iso(incident.fecha_reporte),
                "resumen": incident.resumen_ia or incident.analisis_consolidado or incident.descripcion,
            }
        )

    ranking = []
    for bucket in ranking_buckets.values():
        total = max(bucket["total"], 1)
        ranking.append(
            {
                "label": bucket["label"],
                "id_taller": bucket["id_taller"],
                "id_sucursal": bucket["id_sucursal"],
                "total_incidentes": bucket["total"],
                "completados_pct": round((bucket["completed"] / total) * 100, 2),
                "cancelados_pct": round((bucket["cancelled"] / total) * 100, 2),
                "cumplimiento_sla_pct": round((bucket["sla_passed"] / max(bucket["sla_total"], 1)) * 100, 2),
                "tiempo_promedio_llegada_min": _average(bucket["arrival_times"]),
                "tiempo_promedio_finalizacion_min": _average(bucket["completion_times"]),
            }
        )

    ranking.sort(
        key=lambda item: (
            -(item["cumplimiento_sla_pct"] or 0),
            item["tiempo_promedio_llegada_min"] if item["tiempo_promedio_llegada_min"] is not None else 999999,
        )
    )

    density = []
    for item in density_buckets.values():
        density.append(
            {
                **item,
                "intensidad": round(min(item["cantidad_incidentes"] / 5, 1), 2),
            }
        )

    performance = []
    for label in sorted(performance_buckets.keys()):
        row = performance_buckets[label]
        performance.append(
            {
                "label": label,
                "total_incidentes": int(row["total_incidentes"]),
                "finalizados": int(row["finalizados"]),
                "cancelados": int(row["cancelados"]),
                "cumplimiento_sla_pct": round((row["sla_passed"] / max(row["sla_total"], 1)) * 100, 2),
            }
        )

    return {
        "scope": {
            "role": scope.role,
            "id_taller": scope.id_taller,
            "id_sucursal": scope.id_sucursal,
            "is_global": scope.is_global,
        },
        "summary": {
            "total_incidentes": len(incidents),
            "incidentes_activos": sum(1 for incident in incidents if incident.estado_incidente in ACTIVE_STATES),
            "incidentes_finalizados": sum(1 for incident in incidents if incident.estado_incidente in FINAL_STATES),
            "incidentes_cancelados": sum(1 for incident in incidents if incident.estado_incidente in CANCELLED_STATES),
            "incidentes_no_atendidos": sum(1 for incident in incidents if incident.estado_incidente in {"PENDIENTE", "ANALIZADO"}),
            "tiempo_promedio_asignacion_min": _average(assignment_times),
            "tiempo_promedio_llegada_min": _average(arrival_times),
            "tiempo_promedio_finalizacion_min": _average(completion_times),
            "cumplimiento_sla_pct": round((sla_passed / sla_total) * 100, 2) if sla_total else None,
            "alertas_sla_activas": active_alerts,
        },
        "series": {
            "rendimiento_operativo": performance,
            "incidentes_por_estado": [{"label": key, "value": value} for key, value in status_counter.most_common()],
            "incidentes_por_prioridad": [{"label": key, "value": value} for key, value in priority_counter.most_common()],
            "incidentes_por_origen": [{"label": key, "value": value} for key, value in origin_counter.most_common()],
            "incidentes_por_sucursal": [{"label": key, "value": value} for key, value in branch_counter.most_common()],
            "incidentes_por_taller": [{"label": key, "value": value} for key, value in workshop_counter.most_common()],
        },
        "density": sorted(density, key=lambda item: item["cantidad_incidentes"], reverse=True)[:30],
        "ranking": ranking[:10],
        "recent_activity": recent_activity[:10],
    }


async def build_sla_alerts(
    *,
    repository: OperationalMetricsRepository,
    scope: OperationalScope,
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    prioridad: Optional[str],
    tipo_alerta: Optional[str],
    sla_status: Optional[str],
    estado_incidente: Optional[str],
) -> dict:
    incidents = await repository.get_incidents(
        date_from=date_from,
        date_to=date_to,
        id_taller=scope.id_taller,
        id_sucursal=scope.id_sucursal,
        estado=estado_incidente,
        prioridad=prioridad,
        origen=None,
    )
    now = datetime.now(UTC)
    alerts = []
    summary_counter = Counter()

    for incident in incidents:
        times = _extract_stage_times(incident)
        for alert in _build_incident_alerts(incident, times, now):
            if tipo_alerta and alert["tipo_alerta"] != tipo_alerta:
                continue
            if sla_status and alert["sla_status"] != sla_status:
                continue

            summary_counter[alert["sla_status"]] += 1
            alerts.append(
                {
                    "id_incidente": incident.id_incidente,
                    "tipo_alerta": alert["tipo_alerta"],
                    "sla_status": alert["sla_status"],
                    "estado_actual": incident.estado_incidente,
                    "tiempo_actual_min": alert["tiempo_actual_min"],
                    "limite_sla_min": alert["limite_sla_min"],
                    "tiempo_excedido_min": (
                        round(max((alert["tiempo_actual_min"] or 0) - (alert["limite_sla_min"] or 0), 0), 2)
                        if alert["tiempo_actual_min"] is not None and alert["limite_sla_min"] is not None
                        else None
                    ),
                    "taller": _workshop_name(incident),
                    "sucursal": _branch_name(incident),
                    "tecnico": _technician_name(incident),
                    "prioridad": incident.prioridad_incidente,
                    "fecha_reporte": _safe_iso(incident.fecha_reporte),
                    "ultimo_evento": _safe_iso(times.last_event_at),
                }
            )

    alerts.sort(
        key=lambda item: (
            0 if item["sla_status"] == "INCUMPLIDO" else 1 if item["sla_status"] == "EN_RIESGO" else 2,
            item["fecha_reporte"] or "",
        ),
        reverse=False,
    )

    return {
        "scope": {
            "role": scope.role,
            "id_taller": scope.id_taller,
            "id_sucursal": scope.id_sucursal,
            "is_global": scope.is_global,
        },
        "summary": {
            "total_alertas": len(alerts),
            "en_riesgo": summary_counter["EN_RIESGO"],
            "incumplidas": summary_counter["INCUMPLIDO"],
            "cumplidas": summary_counter["CUMPLIDO"],
            "sin_datos": summary_counter["SIN_DATOS"],
        },
        "alerts": alerts,
    }
