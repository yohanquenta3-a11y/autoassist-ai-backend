from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.packages.identity.domain.models import Rol, Usuario, Vehiculo
from app.packages.transfers.domain.models import HistorialTraslado, SolicitudTraslado
from app.packages.workshops.domain.models import (
    AdministradorTaller,
    SucursalTaller,
    Taller,
    Tecnico,
    UsuarioTaller,
)


DEMO_PASSWORD = "Recuperatorio2026!"
CLIENT_EMAIL = "cliente.transfer.demo@autoassist.com"
ADMIN_EMAIL = "admin.transfer.demo@autoassist.com"
TECH_EMAIL = "tecnico.transfer.demo@autoassist.com"
WORKSHOP_NIT = "TRANSFERS-DEMO-2026"
VEHICLE_PLATE = "TRF-2047"


async def get_or_create_role(session, nombre: str, descripcion: str) -> Rol:
    result = await session.execute(select(Rol).where(Rol.nombre == nombre))
    role = result.scalars().first()
    if role:
        return role
    role = Rol(nombre=nombre, descripcion=descripcion, estado=True)
    session.add(role)
    await session.flush()
    return role


async def get_or_create_user(session, *, role: Rol, email: str, name: str, phone: str) -> Usuario:
    result = await session.execute(select(Usuario).where(Usuario.correo == email))
    user = result.scalars().first()
    if user:
        user.estado = True
        user.telefono = phone
        return user
    user = Usuario(
        id_rol=role.id_rol,
        nombre=name,
        telefono=phone,
        correo=email,
        contrasena=get_password_hash(DEMO_PASSWORD),
        estado=True,
    )
    session.add(user)
    await session.flush()
    return user


async def get_or_create_workshop(session) -> Taller:
    result = await session.execute(select(Taller).where(Taller.nit == WORKSHOP_NIT))
    workshop = result.scalars().first()
    if workshop:
        workshop.is_active = True
        return workshop
    workshop = Taller(
        nombre="AutoAssist Traslados Demo",
        nit=WORKSHOP_NIT,
        telefono="+59176304135",
        email="traslados.demo@autoassist.com",
        direccion="Av. Demo Recuperatorio, Santa Cruz",
        is_active=True,
    )
    session.add(workshop)
    await session.flush()
    return workshop


async def get_or_create_branch(session, workshop: Taller) -> SucursalTaller:
    result = await session.execute(
        select(SucursalTaller).where(
            SucursalTaller.id_taller == workshop.id_taller,
            SucursalTaller.nombre == "Sucursal Traslados Demo",
        )
    )
    branch = result.scalars().first()
    if branch:
        branch.is_active = True
        return branch
    branch = SucursalTaller(
        id_taller=workshop.id_taller,
        nombre="Sucursal Traslados Demo",
        telefono="+59176304135",
        email="sucursal.traslados.demo@autoassist.com",
        direccion="Zona Centro Demo, Santa Cruz",
        is_active=True,
    )
    session.add(branch)
    await session.flush()
    return branch


async def ensure_admin_link(session, admin: Usuario, workshop: Taller) -> None:
    result = await session.execute(
        select(AdministradorTaller).where(AdministradorTaller.id_usuario == admin.id_usuario)
    )
    link = result.scalars().first()
    if link:
        link.id_taller = workshop.id_taller
        return
    session.add(AdministradorTaller(id_usuario=admin.id_usuario, id_taller=workshop.id_taller))


async def ensure_user_taller(session, user: Usuario, workshop: Taller, branch: SucursalTaller, role_context: str) -> None:
    result = await session.execute(
        select(UsuarioTaller).where(
            UsuarioTaller.id_usuario == user.id_usuario,
            UsuarioTaller.id_taller == workshop.id_taller,
            UsuarioTaller.rol_contexto == role_context,
        )
    )
    relation = result.scalars().first()
    if relation:
        relation.id_sucursal = branch.id_sucursal if role_context != "owner" else relation.id_sucursal
        relation.estado = True
        return
    session.add(
        UsuarioTaller(
            id_usuario=user.id_usuario,
            id_taller=workshop.id_taller,
            id_sucursal=None if role_context == "owner" else branch.id_sucursal,
            rol_contexto=role_context,
            estado=True,
        )
    )


async def get_or_create_vehicle(session, client: Usuario) -> Vehiculo:
    result = await session.execute(select(Vehiculo).where(Vehiculo.matricula == VEHICLE_PLATE))
    vehicle = result.scalars().first()
    if vehicle:
        vehicle.id_usuario = client.id_usuario
        return vehicle
    vehicle = Vehiculo(
        id_usuario=client.id_usuario,
        matricula=VEHICLE_PLATE,
        marca="Toyota",
        modelo="Corolla Transfer Demo",
        ano=2020,
        color="Blanco",
    )
    session.add(vehicle)
    await session.flush()
    return vehicle


async def get_or_create_technician(session, tech_user: Usuario, workshop: Taller, branch: SucursalTaller) -> Tecnico:
    result = await session.execute(select(Tecnico).where(Tecnico.id_usuario == tech_user.id_usuario))
    technician = result.scalars().first()
    if technician:
        technician.id_taller = workshop.id_taller
        technician.id_sucursal = branch.id_sucursal
        technician.estado = True
        technician.estado_operativo = "DISPONIBLE"
        technician.nombre = tech_user.nombre
        technician.telefono = tech_user.telefono
        return technician
    technician = Tecnico(
        id_usuario=tech_user.id_usuario,
        id_taller=workshop.id_taller,
        id_sucursal=branch.id_sucursal,
        nombre=tech_user.nombre,
        telefono=tech_user.telefono,
        estado=True,
        estado_operativo="DISPONIBLE",
    )
    session.add(technician)
    await session.flush()
    return technician


async def get_or_create_transfer(
    session,
    *,
    transfer_type: str,
    initial_state: str,
    reason: str,
    client: Usuario,
    vehicle: Vehiculo,
    workshop: Taller,
    branch: SucursalTaller,
        technician: Tecnico | None,
    scheduled_at: datetime | None,
) -> SolicitudTraslado:
    legacy_reasons = {
        ("FLETE_INMEDIATO", "Flete inmediato de vehiculo"): [
            "DEMO CU47 - Flete inmediato de vehiculo",
        ],
        ("PREVENTIVO", "Traslado preventivo de vehiculo"): [
            "DEMO CU48 - Traslado preventivo de vehiculo",
        ],
    }.get((transfer_type, reason), [])
    result = await session.execute(
        select(SolicitudTraslado).where(
            SolicitudTraslado.id_cliente == client.id_usuario,
            SolicitudTraslado.id_vehiculo == vehicle.id_vehiculo,
            SolicitudTraslado.tipo_traslado == transfer_type,
            SolicitudTraslado.motivo.in_([reason, *legacy_reasons]),
        )
    )
    transfer = result.scalars().first()
    if transfer:
        transfer.estado = initial_state
        transfer.id_taller = workshop.id_taller
        transfer.id_sucursal = branch.id_sucursal
        transfer.id_tecnico = technician.id_tecnico if technician else None
        transfer.fecha_programada = scheduled_at
        transfer.motivo = reason
        transfer.observaciones = "Solicitud registrada para prueba operativa."
        return transfer

    transfer = SolicitudTraslado(
        tipo_traslado=transfer_type,
        estado=initial_state,
        id_cliente=client.id_usuario,
        id_vehiculo=vehicle.id_vehiculo,
        id_taller=workshop.id_taller,
        id_sucursal=branch.id_sucursal,
        id_tecnico=technician.id_tecnico if technician else None,
        origen_direccion="Av. Demo Cliente #123",
        origen_latitud=Decimal("-17.7833000"),
        origen_longitud=Decimal("-63.1821000"),
        destino_direccion="Sucursal Traslados Demo",
        destino_latitud=Decimal("-17.7800000"),
        destino_longitud=Decimal("-63.1800000"),
        fecha_programada=scheduled_at,
        motivo=reason,
        observaciones="Solicitud registrada para prueba operativa.",
        telefono_contacto="+59176304135",
        creado_por=client.id_usuario,
        rol_creador="CLIENTE",
    )
    session.add(transfer)
    await session.flush()
    session.add(
        HistorialTraslado(
            id_traslado=transfer.id_traslado,
            estado_anterior=None,
            estado_nuevo=initial_state,
            historial_actor=f"CLIENTE:{client.nombre}",
            id_usuario_actor=client.id_usuario,
            comentario="Registro inicial del traslado",
        )
    )
    return transfer


async def main() -> None:
    async with AsyncSessionLocal() as session:
        cliente_role = await get_or_create_role(session, "cliente", "Cliente")
        admin_role = await get_or_create_role(session, "admin_taller", "Administrador de taller")
        tech_role = await get_or_create_role(session, "tecnico", "Tecnico")

        workshop = await get_or_create_workshop(session)
        branch = await get_or_create_branch(session, workshop)

        client = await get_or_create_user(
            session,
            role=cliente_role,
            email=CLIENT_EMAIL,
            name="Cliente Transfer Demo",
            phone="+59176304135",
        )
        admin = await get_or_create_user(
            session,
            role=admin_role,
            email=ADMIN_EMAIL,
            name="Admin Transfer Demo",
            phone="+59176304135",
        )
        tech_user = await get_or_create_user(
            session,
            role=tech_role,
            email=TECH_EMAIL,
            name="Tecnico Transfer Demo",
            phone="+59176304135",
        )

        await ensure_admin_link(session, admin, workshop)
        await ensure_user_taller(session, admin, workshop, branch, "owner")
        await ensure_user_taller(session, client, workshop, branch, "cliente")

        vehicle = await get_or_create_vehicle(session, client)
        technician = await get_or_create_technician(session, tech_user, workshop, branch)

        immediate = await get_or_create_transfer(
            session,
            transfer_type="FLETE_INMEDIATO",
            initial_state="SOLICITADO",
            reason="Flete inmediato de vehiculo",
            client=client,
            vehicle=vehicle,
            workshop=workshop,
            branch=branch,
            technician=None,
            scheduled_at=None,
        )
        scheduled = await get_or_create_transfer(
            session,
            transfer_type="PREVENTIVO",
            initial_state="PROGRAMADO",
            reason="Traslado preventivo de vehiculo",
            client=client,
            vehicle=vehicle,
            workshop=workshop,
            branch=branch,
            technician=None,
            scheduled_at=(datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None),
        )

        await session.commit()

        print("Seed de traslados listo.")
        print(f"Cliente: {CLIENT_EMAIL} / {DEMO_PASSWORD}")
        print(f"Admin taller: {ADMIN_EMAIL} / {DEMO_PASSWORD}")
        print(f"Tecnico: {TECH_EMAIL} / {DEMO_PASSWORD}")
        print(f"id_taller: {workshop.id_taller}")
        print(f"id_sucursal: {branch.id_sucursal}")
        print(f"id_tecnico: {technician.id_tecnico}")
        print(f"id_vehiculo: {vehicle.id_vehiculo}")
        print(f"Flete inmediato id_traslado: {immediate.id_traslado}")
        print(f"Traslado preventivo id_traslado: {scheduled.id_traslado}")


if __name__ == "__main__":
    asyncio.run(main())
