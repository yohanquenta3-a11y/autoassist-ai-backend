import logging
from datetime import datetime, date, time, timedelta, timezone
import uuid
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_

from app.core.exceptions import BadRequestError, NotFoundError, ForbiddenError
from app.packages.scheduling.infrastructure.repositories import SchedulingRepository
from app.packages.scheduling.domain.models import Cita
from app.packages.scheduling.domain.schemas import SlotAvailabilityResponse
from app.packages.workshops.domain.models import Tecnico, SucursalTaller, UsuarioTaller
from app.packages.identity.domain.models import Usuario, Vehiculo

# GMT-4 timezone for Bolivia (local timezone for taller operations)
LOCAL_TZ = timezone(timedelta(hours=-4))
logger = logging.getLogger(__name__)

class SchedulingService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SchedulingRepository(db)

    def _ensure_action_state(self, appt: Cita, allowed_states: List[str], action_name: str) -> None:
        if appt.estado not in allowed_states:
            raise BadRequestError(
                f"No se puede {action_name.lower()} una cita en estado {appt.estado}."
            )

    def _ensure_action_scope(self, appt: Cita, user: Usuario, selected_branch_id: Optional[uuid.UUID]) -> None:
        if user.rol_nombre == "cliente":
            if appt.id_cliente != user.id_usuario:
                raise ForbiddenError("No tiene permisos para modificar esta cita.")
            return

        if selected_branch_id is None:
            raise ForbiddenError("Operación denegada. Debe seleccionar una sucursal activa.")

        if appt.id_sucursal != selected_branch_id:
            raise ForbiddenError("No tiene permisos para modificar citas de otra sucursal.")

    async def _append_incident_history(
        self,
        *,
        incident_id: Optional[uuid.UUID],
        id_taller: Optional[uuid.UUID],
        id_sucursal: Optional[uuid.UUID],
        historial_actor: str,
        id_usuario_actor: uuid.UUID,
        default_estado: Optional[str] = None,
    ) -> None:
        """
        Stores scheduling-related traceability in HistorialIncidente without violating
        the non-null incident state constraint.
        """
        if not incident_id:
            return

        try:
            from app.packages.emergencies.domain.models import HistorialIncidente, Incidente

            result = await self.db.execute(
                select(Incidente).where(Incidente.id_incidente == incident_id)
            )
            incident = result.scalars().first()
            if not incident:
                logger.warning("No se encontró el incidente %s para registrar historial de cita.", incident_id)
                return

            estado = incident.estado_incidente or default_estado or "PENDIENTE"
            history = HistorialIncidente(
                id_incidente=incident.id_incidente,
                id_taller=id_taller or incident.id_taller,
                id_sucursal=id_sucursal or incident.id_sucursal,
                incidente_estado_anterior=estado,
                incidente_estado_nuevo=estado,
                historial_actor=historial_actor,
                id_usuario_actor=id_usuario_actor,
            )
            self.db.add(history)
            await self.db.commit()
        except Exception as exc:
            await self.db.rollback()
            logger.warning(
                "No se pudo registrar historial de cita para incidente %s: %s",
                incident_id,
                exc,
            )

    async def get_available_slots(
        self,
        sucursal_id: uuid.UUID,
        target_date: date,
        tecnico_id: Optional[uuid.UUID] = None
    ) -> List[SlotAvailabilityResponse]:
        """
        Generates 60-minute slots between 08:00 and 18:00 (local time)
        and flags availability based on active appointments and capacity.
        """
        # Rule: Only Mon-Sat (Sunday is 6 in python weekday() or weekday 0-6 where Monday=0)
        # weekday(): Monday=0, Sunday=6
        if target_date.weekday() == 6:
            return []

        # Validate date is within next 7 days
        today = datetime.now(LOCAL_TZ).date()
        max_date = today + timedelta(days=7)
        if target_date < today or target_date > max_date:
            return []

        # Fetch active appointments for that sucursal and date
        appointments = await self.repo.get_active_by_sucursal_and_date(sucursal_id, target_date)

        # Calculate branch capacity based on active technicians
        result_tecs = await self.db.execute(
            select(Tecnico).where(
                and_(
                    Tecnico.id_sucursal == sucursal_id,
                    Tecnico.estado == True
                )
            )
        )
        active_tecs = list(result_tecs.scalars().all())
        branch_capacity = max(len(active_tecs), 2)  # Default capacity of 2 if no active techs

        # Generate slots from 08:00 to 18:00 (last slot starts at 17:00)
        candidate_hours = list(range(8, 18))  # 8, 9, 10, 11, 12, 13, 14, 15, 16, 17
        slots: List[SlotAvailabilityResponse] = []
        now_utc = datetime.now(timezone.utc)

        for hour in candidate_hours:
            # Construct local datetime
            slot_local = datetime.combine(
                target_date, 
                time(hour=hour, minute=0), 
                tzinfo=LOCAL_TZ
            )
            # Convert to UTC for matching with database
            slot_utc = slot_local.astimezone(timezone.utc)

            # 1. Skip past slots (slot start time is in the past)
            if slot_utc <= now_utc:
                slots.append(SlotAvailabilityResponse(
                    fecha_hora=slot_utc,
                    disponible=False,
                    motivo="Horario en el pasado"
                ))
                continue

            # 2. Count concurrent appointments in this slot
            concurrent_count = 0
            tech_busy = False

            for appt in appointments:
                # Compare in UTC
                appt_utc = appt.fecha_hora.replace(tzinfo=timezone.utc) if appt.fecha_hora.tzinfo is None else appt.fecha_hora.astimezone(timezone.utc)
                if appt_utc == slot_utc:
                    concurrent_count += 1
                    if tecnico_id and appt.id_tecnico == tecnico_id:
                        tech_busy = True

            # 3. Check capacity limits
            if concurrent_count >= branch_capacity:
                slots.append(SlotAvailabilityResponse(
                    fecha_hora=slot_utc,
                    disponible=False,
                    motivo="Capacidad de la sucursal completada"
                ))
            elif tech_busy:
                slots.append(SlotAvailabilityResponse(
                    fecha_hora=slot_utc,
                    disponible=False,
                    motivo="Técnico no disponible en este horario"
                ))
            else:
                slots.append(SlotAvailabilityResponse(
                    fecha_hora=slot_utc,
                    disponible=True
                ))

        return slots

    async def create_appointment(
        self,
        creator: Usuario,
        id_incidente_origen: Optional[uuid.UUID],
        id_vehiculo: uuid.UUID,
        id_tecnico: Optional[uuid.UUID],
        fecha_hora: datetime,
        motivo: str,
        observaciones: Optional[str],
        prioridad: str
    ) -> Cita:
        """Creates a follow-up appointment verifying availability and rules."""
        # 1. Validate incident origin if provided
        incident = None
        id_taller = None
        id_sucursal = None
        id_cliente = None

        if id_incidente_origen:
            # Validate single active appointment per incident
            existing = await self.repo.get_active_by_incident(id_incidente_origen)
            if existing:
                raise BadRequestError("Ya existe una cita posterior activa para este incidente.")

            # Load incident details
            from app.packages.emergencies.domain.models import Incidente
            result_inc = await self.db.execute(
                select(Incidente).where(Incidente.id_incidente == id_incidente_origen)
            )
            incident = result_inc.scalars().first()
            if not incident:
                raise NotFoundError("Incidente de origen no encontrado.")

            # Rule check: incident must be in EN_ATENCION, FINALIZADO or COMPLETADO
            if incident.estado_incidente.upper() not in ["EN_ATENCION", "FINALIZADO", "COMPLETADO"]:
                raise BadRequestError("El incidente debe encontrarse en atención, finalizado o completado.")

            id_taller = incident.id_taller
            id_sucursal = incident.id_sucursal
            id_cliente = incident.id_usuario_cliente
        else:
            raise BadRequestError("Debe proporcionar un incidente de origen para agendar una cita posterior.")

        if not id_sucursal or not id_taller:
            raise BadRequestError("El incidente debe tener un taller y sucursal asignados.")

        # 2. Check slot availability
        # Convert incoming datetime to target date and local time for slot checks
        fecha_hora_local = fecha_hora.astimezone(LOCAL_TZ)
        target_date = fecha_hora_local.date()
        
        # Verify slot is within operating hours (08:00 - 18:00 Mon-Sat)
        if fecha_hora_local.minute != 0 or fecha_hora_local.second != 0 or fecha_hora_local.hour < 8 or fecha_hora_local.hour >= 18 or target_date.weekday() == 6:
            raise BadRequestError("Horario fuera del horario operativo (Mon-Sat 08:00 - 18:00, slots de 60 mins).")

        available_slots = await self.get_available_slots(id_sucursal, target_date, id_tecnico)
        is_slot_available = False
        
        # Match incoming datetime (normalized to UTC) with available slots
        incoming_utc = fecha_hora.astimezone(timezone.utc)
        for slot in available_slots:
            if slot.fecha_hora.astimezone(timezone.utc) == incoming_utc and slot.disponible:
                is_slot_available = True
                break

        if not is_slot_available:
            raise BadRequestError("El horario seleccionado no está disponible.")

        # 3. Create Cita
        # Roles mapping
        rol_creador = "ADMIN"
        if creator.rol_nombre == "tecnico":
            rol_creador = "TECNICO"
            # Rule: Técnico can only create appointments for incidents assigned to him
            if incident.id_tecnico != creator.id_usuario and incident.id_tecnico is not None:
                # Check if creator has a Técnico model mapping
                result_tec = await self.db.execute(
                    select(Tecnico).where(Tecnico.id_usuario == creator.id_usuario)
                )
                tec = result_tec.scalars().first()
                if not tec or incident.id_tecnico != tec.id_tecnico:
                    raise BadRequestError("Solo el técnico asignado a este incidente puede crear la cita posterior.")
        elif creator.rol_nombre == "cliente":
            rol_creador = "CLIENTE"

        appointment = Cita(
            id_incidente_origen=id_incidente_origen,
            id_cliente=id_cliente,
            id_vehiculo=id_vehiculo,
            id_taller=id_taller,
            id_sucursal=id_sucursal,
            id_tecnico=id_tecnico,
            fecha_hora=incoming_utc.replace(tzinfo=None),  # Store naive UTC
            duracion_minutos=60,
            estado="PENDIENTE_CONFIRMACION",  # Initial state always PENDIENTE_CONFIRMACION
            tipo="POST_AUXILIO",
            motivo=motivo,
            observaciones=observaciones,
            prioridad=prioridad,
            creado_por=creator.id_usuario,
            rol_creador=rol_creador
        )

        created = await self.repo.create_appointment(appointment)

        # 4. Log in HistorialIncidente without breaking the appointment flow
        await self._append_incident_history(
            incident_id=id_incidente_origen,
            id_taller=id_taller,
            id_sucursal=id_sucursal,
            historial_actor=f"{rol_creador}:{creator.nombre} (Cita Creada)",
            id_usuario_actor=creator.id_usuario,
            default_estado=incident.estado_incidente,
        )

        return created

    async def create_direct_appointment(
        self,
        creator: Usuario,
        id_cliente: uuid.UUID,
        id_vehiculo: uuid.UUID,
        id_sucursal: uuid.UUID,
        id_tecnico: Optional[uuid.UUID],
        fecha_hora: datetime,
        motivo: str,
        observaciones: Optional[str],
        prioridad: str,
        selected_branch_id: Optional[uuid.UUID] = None,
    ) -> Cita:
        """Creates a direct appointment without incident traceability."""
        if creator.rol_nombre not in ["admin_taller", "superadmin"]:
            raise ForbiddenError("No tiene permisos para crear citas directas.")

        branch_result = await self.db.execute(
            select(SucursalTaller).where(SucursalTaller.id_sucursal == id_sucursal)
        )
        branch = branch_result.scalars().first()
        if not branch:
            raise NotFoundError("Sucursal no encontrada.")

        if selected_branch_id and branch.id_sucursal != selected_branch_id:
            raise ForbiddenError("No tiene permisos para crear citas en otra sucursal.")

        if creator.rol_nombre == "admin_taller" and creator.rol_contexto == "admin_sucursal" and creator.id_sucursal and branch.id_sucursal != creator.id_sucursal:
            raise ForbiddenError("No tiene permisos para crear citas en otra sucursal.")

        client_result = await self.db.execute(
            select(Usuario).where(Usuario.id_usuario == id_cliente)
        )
        client = client_result.scalars().first()
        if not client or client.rol_nombre != "cliente":
            raise NotFoundError("Cliente no encontrado.")

        vehicle_result = await self.db.execute(
            select(Vehiculo).where(Vehiculo.id_vehiculo == id_vehiculo)
        )
        vehicle = vehicle_result.scalars().first()
        if not vehicle:
            raise NotFoundError("Vehículo no encontrado.")
        if vehicle.id_usuario != client.id_usuario:
            raise BadRequestError("El vehículo seleccionado no pertenece al cliente.")

        relation_result = await self.db.execute(
            select(UsuarioTaller).where(
                UsuarioTaller.id_usuario == client.id_usuario,
                UsuarioTaller.id_taller == branch.id_taller,
                UsuarioTaller.estado == True
            )
        )
        relation = relation_result.scalars().first()
        if not relation:
            raise ForbiddenError("El cliente no está vinculado a esta sucursal/taller.")

        fecha_hora_local = fecha_hora.astimezone(LOCAL_TZ)
        target_date = fecha_hora_local.date()
        if fecha_hora_local.minute != 0 or fecha_hora_local.second != 0 or fecha_hora_local.hour < 8 or fecha_hora_local.hour >= 18 or target_date.weekday() == 6:
            raise BadRequestError("Horario fuera del horario operativo (Mon-Sat 08:00 - 18:00, slots de 60 mins).")

        available_slots = await self.get_available_slots(branch.id_sucursal, target_date, id_tecnico)
        incoming_utc = fecha_hora.astimezone(timezone.utc)
        is_slot_available = any(
            slot.fecha_hora.astimezone(timezone.utc) == incoming_utc and slot.disponible
            for slot in available_slots
        )
        if not is_slot_available:
            raise BadRequestError("El horario seleccionado no está disponible.")

        appointment = Cita(
            id_incidente_origen=None,
            id_cliente=client.id_usuario,
            id_vehiculo=vehicle.id_vehiculo,
            id_taller=branch.id_taller,
            id_sucursal=branch.id_sucursal,
            id_tecnico=id_tecnico,
            fecha_hora=incoming_utc.replace(tzinfo=None),
            duracion_minutos=60,
            estado="PENDIENTE_CONFIRMACION",
            tipo="DIRECTA",
            motivo=motivo,
            observaciones=observaciones,
            prioridad=prioridad,
            creado_por=creator.id_usuario,
            rol_creador="ADMIN"
        )

        return await self.repo.create_appointment(appointment)

    async def confirm_appointment(
        self,
        appointment_id: uuid.UUID,
        user: Usuario,
        selected_branch_id: Optional[uuid.UUID] = None,
    ) -> Cita:
        appt = await self.repo.get_by_id(appointment_id)
        if not appt:
            raise NotFoundError("Cita no encontrada.")

        self._ensure_action_scope(appt, user, selected_branch_id)
        self._ensure_action_state(appt, ["PENDIENTE_CONFIRMACION", "REPROGRAMACION_SOLICITADA"], "confirmar")

        appt.estado = "CONFIRMADA"
        updated = await self.repo.update_appointment(appt)

        await self._append_incident_history(
            incident_id=appt.id_incidente_origen,
            id_taller=appt.id_taller,
            id_sucursal=appt.id_sucursal,
            historial_actor=f"{user.rol_nombre.upper()}:{user.nombre} (Cita Confirmada)",
            id_usuario_actor=user.id_usuario,
            default_estado=appt.estado,
        )

        return updated

    async def reschedule_appointment(
        self,
        appointment_id: uuid.UUID,
        new_fecha_hora: datetime,
        observaciones: Optional[str],
        user: Usuario,
        selected_branch_id: Optional[uuid.UUID] = None,
    ) -> Cita:
        appt = await self.repo.get_by_id(appointment_id)
        if not appt:
            raise NotFoundError("Cita no encontrada.")

        self._ensure_action_scope(appt, user, selected_branch_id)
        self._ensure_action_state(appt, ["PENDIENTE_CONFIRMACION", "CONFIRMADA", "REPROGRAMACION_SOLICITADA"], "reprogramar")

        # Check availability for the new slot
        new_fecha_hora_local = new_fecha_hora.astimezone(LOCAL_TZ)
        target_date = new_fecha_hora_local.date()

        if new_fecha_hora_local.date() < datetime.now(LOCAL_TZ).date():
            raise BadRequestError("No se puede reprogramar a una fecha pasada.")

        if new_fecha_hora_local.minute != 0 or new_fecha_hora_local.second != 0 or new_fecha_hora_local.hour < 8 or new_fecha_hora_local.hour >= 18 or target_date.weekday() == 6:
            raise BadRequestError("Horario fuera del horario operativo (Mon-Sat 08:00 - 18:00, slots de 60 mins).")

        available_slots = await self.get_available_slots(appt.id_sucursal, target_date, appt.id_tecnico)
        is_slot_available = False
        incoming_utc = new_fecha_hora.astimezone(timezone.utc)
        
        for slot in available_slots:
            if slot.fecha_hora.astimezone(timezone.utc) == incoming_utc and slot.disponible:
                is_slot_available = True
                break

        if not is_slot_available:
            raise BadRequestError("El horario seleccionado no está disponible.")

        # Set new state
        # Client requests reschedule -> REPROGRAMACION_SOLICITADA
        # Admin or Tech proposes reschedule -> PENDIENTE_CONFIRMACION
        rol_actor = user.rol_nombre.upper()
        if user.rol_nombre == "cliente":
            appt.estado = "REPROGRAMACION_SOLICITADA"
        else:
            appt.estado = "PENDIENTE_CONFIRMACION"

        appt.fecha_hora = incoming_utc.replace(tzinfo=None)
        if observaciones:
            appt.observaciones = observaciones

        updated = await self.repo.update_appointment(appt)

        await self._append_incident_history(
            incident_id=appt.id_incidente_origen,
            id_taller=appt.id_taller,
            id_sucursal=appt.id_sucursal,
            historial_actor=f"{rol_actor}:{user.nombre} (Reprogramación Solicitada)",
            id_usuario_actor=user.id_usuario,
            default_estado=appt.estado,
        )

        return updated

    async def cancel_appointment(
        self,
        appointment_id: uuid.UUID,
        user: Usuario,
        selected_branch_id: Optional[uuid.UUID] = None,
    ) -> Cita:
        appt = await self.repo.get_by_id(appointment_id)
        if not appt:
            raise NotFoundError("Cita no encontrada.")

        self._ensure_action_scope(appt, user, selected_branch_id)
        self._ensure_action_state(appt, ["PENDIENTE_CONFIRMACION", "CONFIRMADA", "REPROGRAMACION_SOLICITADA"], "cancelar")

        appt.estado = "CANCELADA"
        updated = await self.repo.update_appointment(appt)

        await self._append_incident_history(
            incident_id=appt.id_incidente_origen,
            id_taller=appt.id_taller,
            id_sucursal=appt.id_sucursal,
            historial_actor=f"{user.rol_nombre.upper()}:{user.nombre} (Cita Cancelada)",
            id_usuario_actor=user.id_usuario,
            default_estado=appt.estado,
        )

        return updated

    async def complete_appointment(
        self,
        appointment_id: uuid.UUID,
        user: Usuario,
        selected_branch_id: Optional[uuid.UUID] = None,
    ) -> Cita:
        appt = await self.repo.get_by_id(appointment_id)
        if not appt:
            raise NotFoundError("Cita no encontrada.")

        self._ensure_action_scope(appt, user, selected_branch_id)
        self._ensure_action_state(appt, ["CONFIRMADA"], "completar")

        appt.estado = "COMPLETADA"
        updated = await self.repo.update_appointment(appt)

        await self._append_incident_history(
            incident_id=appt.id_incidente_origen,
            id_taller=appt.id_taller,
            id_sucursal=appt.id_sucursal,
            historial_actor=f"{user.rol_nombre.upper()}:{user.nombre} (Cita Completada)",
            id_usuario_actor=user.id_usuario,
            default_estado=appt.estado,
        )

        return updated
