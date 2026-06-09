from __future__ import annotations

import asyncio
import csv
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from geoalchemy2.elements import WKTElement
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal, Base
from app.core.security import get_password_hash
from app.packages.assignment.domain.models import AsignacionIncidente
from app.packages.emergencies.domain.models import (
    EvidenciaIncidente,
    HistorialIncidente,
    Incidente,
    VerificacionTecnico,
)
from app.packages.finance.domain.models import Pago
from app.packages.identity.domain.models import Rol, Usuario, Vehiculo
from app.packages.quotations.domain.models import Cotizacion, SolicitudCotizacion, SolicitudCotizacionTaller
from app.packages.scheduling.domain.models import Cita
from app.packages.workshops.domain.models import (
    AdministradorTaller,
    CategoriaServicio,
    DisponibilidadTecnico,
    SucursalTaller,
    Taller,
    TallerCategoriaServicio,
    Tecnico,
    UsuarioTaller,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_CREDENTIALS = BACKEND_ROOT / "MULTITENANT_DEMO_CREDENTIALS_2026-06-09.md"
CSV_CREDENTIALS = BACKEND_ROOT / "MULTITENANT_DEMO_CREDENTIALS_2026-06-09.csv"


@dataclass
class AccountRow:
    nombre: str
    correo: str
    rol: str
    contexto: str
    taller: str
    sucursal: str
    password: str


WORKSHOP_SEED = [
    {
        "key": "torque",
        "name": "Red Torque Norte",
        "nit": "301000101",
        "phone": "3-310-4101",
        "email": "contacto@torquenorte.bo",
        "address": "Av. San Martin, Equipetrol, Santa Cruz de la Sierra",
        "point": (-17.7757, -63.1966),
        "owner": {
            "name": "Rodrigo Salvatierra",
            "phone": "70010001",
            "email": "owner@torquenorte.bo",
            "password": "OwnerTorque2026!",
        },
        "branches": [
            {
                "key": "equipetrol",
                "name": "Equipetrol",
                "phone": "3-310-4102",
                "email": "equipetrol@torquenorte.bo",
                "address": "Canal Isuto, Equipetrol Norte, Santa Cruz de la Sierra",
                "point": (-17.7709, -63.1962),
                "admin": {
                    "name": "Daniela Roca",
                    "phone": "70010011",
                    "email": "equipetrol.admin@torquenorte.bo",
                    "password": "AdminTorqueEq2026!",
                },
                "techs": [
                    {"name": "Carlos Aguilar", "phone": "70010021", "email": "c.aguilar@torquenorte.bo", "password": "TecTorqueEq12026!"},
                    {"name": "Joaquin Almos", "phone": "70010022", "email": "j.almos@torquenorte.bo", "password": "TecTorqueEq22026!"},
                ],
            },
            {
                "key": "urubo",
                "name": "Urubo",
                "phone": "3-310-4103",
                "email": "urubo@torquenorte.bo",
                "address": "Av. Jorge Roca, Urubo, Santa Cruz de la Sierra",
                "point": (-17.7515, -63.2209),
                "admin": {
                    "name": "Paola Cuellar",
                    "phone": "70010012",
                    "email": "urubo.admin@torquenorte.bo",
                    "password": "AdminTorqueUr2026!",
                },
                "techs": [
                    {"name": "Sebastian Smit", "phone": "70010023", "email": "s.smit@torquenorte.bo", "password": "TecTorqueUr12026!"},
                    {"name": "Leonardo Carrasco", "phone": "70010024", "email": "l.carrasco@torquenorte.bo", "password": "TecTorqueUr22026!"},
                ],
            },
        ],
    },
    {
        "key": "andina",
        "name": "Andina Motor Care",
        "nit": "301000202",
        "phone": "3-320-5201",
        "email": "contacto@andinamotor.bo",
        "address": "Av. Santos Dumont, Santa Cruz de la Sierra",
        "point": (-17.8217, -63.1711),
        "owner": {
            "name": "Valeria Montero",
            "phone": "70020001",
            "email": "owner@andinamotor.bo",
            "password": "OwnerAndina2026!",
        },
        "branches": [
            {
                "key": "santos_dumont",
                "name": "Santos Dumont",
                "phone": "3-320-5202",
                "email": "santosdumont@andinamotor.bo",
                "address": "Av. Santos Dumont, 4to anillo, Santa Cruz de la Sierra",
                "point": (-17.8231, -63.1701),
                "admin": {
                    "name": "Alejandro Sejas",
                    "phone": "70020011",
                    "email": "santosdumont.admin@andinamotor.bo",
                    "password": "AdminAndinaSd2026!",
                },
                "techs": [
                    {"name": "Yohan Mamani", "phone": "70020021", "email": "y.mamani@andinamotor.bo", "password": "TecAndinaSd12026!"},
                    {"name": "Ruben Mendez", "phone": "70020022", "email": "r.mendez@andinamotor.bo", "password": "TecAndinaSd22026!"},
                ],
            },
            {
                "key": "plan_3000",
                "name": "Plan 3000",
                "phone": "3-320-5203",
                "email": "plan3000@andinamotor.bo",
                "address": "Av. Paurito, Plan 3000, Santa Cruz de la Sierra",
                "point": (-17.8476, -63.1401),
                "admin": {
                    "name": "Lucia Pedraza",
                    "phone": "70020012",
                    "email": "plan3000.admin@andinamotor.bo",
                    "password": "AdminAndinaP32026!",
                },
                "techs": [
                    {"name": "Mario Vaca", "phone": "70020023", "email": "m.vaca@andinamotor.bo", "password": "TecAndinaP312026!"},
                    {"name": "Hector Suazo", "phone": "70020024", "email": "h.suazo@andinamotor.bo", "password": "TecAndinaP322026!"},
                ],
            },
        ],
    },
    {
        "key": "rutasur",
        "name": "Ruta Sur Service",
        "nit": "301000303",
        "phone": "3-330-6301",
        "email": "contacto@rutasur.bo",
        "address": "Av. Cristo Redentor, Santa Cruz de la Sierra",
        "point": (-17.7524, -63.1817),
        "owner": {
            "name": "Marcelo Paniagua",
            "phone": "70030001",
            "email": "owner@rutasur.bo",
            "password": "OwnerRutaSur2026!",
        },
        "branches": [
            {
                "key": "cristo_redentor",
                "name": "Cristo Redentor",
                "phone": "3-330-6302",
                "email": "cristo@rutasur.bo",
                "address": "Av. Cristo Redentor, 3er anillo, Santa Cruz de la Sierra",
                "point": (-17.7528, -63.1828),
                "admin": {
                    "name": "Nadia Lozada",
                    "phone": "70030011",
                    "email": "cristo.admin@rutasur.bo",
                    "password": "AdminRutaCr2026!",
                },
                "techs": [
                    {"name": "Patricio Paz", "phone": "70030021", "email": "p.paz@rutasur.bo", "password": "TecRutaCr12026!"},
                    {"name": "Erwin Torrico", "phone": "70030022", "email": "e.torrico@rutasur.bo", "password": "TecRutaCr22026!"},
                ],
            },
            {
                "key": "villa_1ro_mayo",
                "name": "Villa 1ro de Mayo",
                "phone": "3-330-6303",
                "email": "villa1ro@rutasur.bo",
                "address": "Av. Cumavi, Villa 1ro de Mayo, Santa Cruz de la Sierra",
                "point": (-17.7726, -63.1082),
                "admin": {
                    "name": "Javier Rios",
                    "phone": "70030012",
                    "email": "villa1ro.admin@rutasur.bo",
                    "password": "AdminRutaVm2026!",
                },
                "techs": [
                    {"name": "Oscar Hurtado", "phone": "70030023", "email": "o.hurtado@rutasur.bo", "password": "TecRutaVm12026!"},
                    {"name": "Brayan Ruiz", "phone": "70030024", "email": "b.ruiz@rutasur.bo", "password": "TecRutaVm22026!"},
                ],
            },
        ],
    },
]

GLOBAL_USERS = {
    "superadmins": [
        {
            "name": "Admin Central",
            "phone": "70090001",
            "email": "superadmin@autoassist.global",
            "password": "SuperAdmin2026!",
        }
    ],
    "clients": [
        {
            "key": "pedro",
            "name": "Pedro Suarez",
            "phone": "70100001",
            "email": "pedro.suarez@gmail.com",
            "password": "ClientePedro2026!",
            "vehicle": {"plate": "SCZ-2401", "brand": "Toyota", "model": "Corolla", "year": 2019, "color": "Blanco"},
        },
        {
            "key": "maria",
            "name": "Maria Gutierrez",
            "phone": "70100002",
            "email": "maria.gutierrez@gmail.com",
            "password": "ClienteMaria2026!",
            "vehicle": {"plate": "SCZ-2402", "brand": "Suzuki", "model": "Swift", "year": 2020, "color": "Rojo"},
        },
        {
            "key": "jose",
            "name": "Jose Lopez",
            "phone": "70100003",
            "email": "jose.lopez@gmail.com",
            "password": "ClienteJose2026!",
            "vehicle": {"plate": "SCZ-2403", "brand": "Nissan", "model": "Versa", "year": 2018, "color": "Plata"},
        },
        {
            "key": "carla",
            "name": "Carla Rojas",
            "phone": "70100004",
            "email": "carla.rojas@gmail.com",
            "password": "ClienteCarla2026!",
            "vehicle": {"plate": "SCZ-2404", "brand": "Hyundai", "model": "Accent", "year": 2021, "color": "Gris"},
        },
        {
            "key": "bruno",
            "name": "Bruno Perez",
            "phone": "70100005",
            "email": "bruno.perez@gmail.com",
            "password": "ClienteBruno2026!",
            "vehicle": {"plate": "SCZ-2405", "brand": "Kia", "model": "Rio", "year": 2017, "color": "Azul"},
        },
        {
            "key": "lucia",
            "name": "Lucia Vargas",
            "phone": "70100006",
            "email": "lucia.vargas@gmail.com",
            "password": "ClienteLucia2026!",
            "vehicle": {"plate": "SCZ-2406", "brand": "Chevrolet", "model": "Onix", "year": 2022, "color": "Negro"},
        },
        {
            "key": "andres",
            "name": "Andres Molina",
            "phone": "70100007",
            "email": "andres.molina@gmail.com",
            "password": "ClienteAndres2026!",
            "vehicle": {"plate": "SCZ-2407", "brand": "Mazda", "model": "CX-5", "year": 2020, "color": "Gris"},
        },
        {
            "key": "sofia",
            "name": "Sofia Cuiza",
            "phone": "70100008",
            "email": "sofia.cuiza@gmail.com",
            "password": "ClienteSofia2026!",
            "vehicle": {"plate": "SCZ-2408", "brand": "Volkswagen", "model": "Gol", "year": 2016, "color": "Blanco"},
        },
    ],
}


def geo_point(lat: float, lng: float) -> WKTElement:
    return WKTElement(f"POINT({lng} {lat})", srid=4326)


def hours_ago(value: int) -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=value)


def days_ago(value: int) -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(days=value)


def write_credentials(entries: list[AccountRow]) -> None:
    markdown_lines = [
        "# Credenciales demo multi-tenant",
        "",
        "Fecha: 2026-06-09",
        "",
        "## Usuarios",
        "",
        "| Nombre | Correo | Rol | Contexto | Taller | Sucursal | Password |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    for entry in entries:
        markdown_lines.append(
            f"| {entry.nombre} | {entry.correo} | {entry.rol} | {entry.contexto} | {entry.taller} | {entry.sucursal} | `{entry.password}` |"
        )

    MARKDOWN_CREDENTIALS.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")

    with CSV_CREDENTIALS.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["nombre", "correo", "rol", "contexto", "taller", "sucursal", "password"])
        for entry in entries:
            writer.writerow(
                [entry.nombre, entry.correo, entry.rol, entry.contexto, entry.taller, entry.sucursal, entry.password]
            )


async def truncate_demo_data(session) -> None:
    table_names = [table.name for table in Base.metadata.sorted_tables]
    quoted = ", ".join(f'"{table_name}"' for table_name in table_names)
    await session.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
    await session.commit()


async def get_role_map(session) -> dict[str, Rol]:
    roles = {
        "superadmin": "Administrador global de la plataforma",
        "admin_taller": "Owner de cadena o administrador de sucursal",
        "tecnico": "Tecnico operativo de una sucursal",
        "cliente": "Cliente global de la plataforma",
    }
    role_map: dict[str, Rol] = {}
    for name, description in roles.items():
        role = Rol(nombre=name, descripcion=description, estado=True)
        session.add(role)
        role_map[name] = role
    await session.flush()
    return role_map


async def create_user(session, role_map: dict[str, Rol], *, name: str, phone: str, email: str, password: str, role: str) -> Usuario:
    user = Usuario(
        id_rol=role_map[role].id_rol,
        nombre=name,
        telefono=phone,
        correo=email,
        contrasena=get_password_hash(password),
        estado=True,
    )
    session.add(user)
    await session.flush()
    return user


async def add_week_schedule(session, technician: Tecnico) -> None:
    for day in ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO"]:
        session.add(
            DisponibilidadTecnico(
                id_tecnico=technician.id_tecnico,
                dia=day,
                hora_ini=datetime.strptime("08:00", "%H:%M").time(),
                hora_fin=datetime.strptime("18:00", "%H:%M").time(),
                disponibilidad=True,
            )
        )


async def seed() -> None:
    credentials: list[AccountRow] = []

    async with AsyncSessionLocal() as session:
        await truncate_demo_data(session)
        role_map = await get_role_map(session)

        category_names = ["Mecanica General", "Electricidad Automotriz", "Grua y Auxilio"]
        categories: list[CategoriaServicio] = []
        for category_name in category_names:
            category = CategoriaServicio(nombre=category_name)
            session.add(category)
            categories.append(category)
        await session.flush()

        workshop_entities: dict[str, Taller] = {}
        branch_entities: dict[str, SucursalTaller] = {}
        technician_entities: dict[str, Tecnico] = {}
        client_users: dict[str, Usuario] = {}
        client_vehicles: dict[str, Vehiculo] = {}

        for superadmin in GLOBAL_USERS["superadmins"]:
            user = await create_user(
                session,
                role_map,
                name=superadmin["name"],
                phone=superadmin["phone"],
                email=superadmin["email"],
                password=superadmin["password"],
                role="superadmin",
            )
            credentials.append(
                AccountRow(user.nombre, user.correo, "superadmin", "global", "", "", superadmin["password"])
            )

        for client in GLOBAL_USERS["clients"]:
            user = await create_user(
                session,
                role_map,
                name=client["name"],
                phone=client["phone"],
                email=client["email"],
                password=client["password"],
                role="cliente",
            )
            vehicle = Vehiculo(
                id_usuario=user.id_usuario,
                matricula=client["vehicle"]["plate"],
                marca=client["vehicle"]["brand"],
                modelo=client["vehicle"]["model"],
                ano=client["vehicle"]["year"],
                color=client["vehicle"]["color"],
            )
            session.add(vehicle)
            await session.flush()
            client_users[client["key"]] = user
            client_vehicles[client["key"]] = vehicle
            credentials.append(
                AccountRow(user.nombre, user.correo, "cliente", "global", "", "", client["password"])
            )

        for workshop_seed in WORKSHOP_SEED:
            workshop = Taller(
                nombre=workshop_seed["name"],
                nit=workshop_seed["nit"],
                telefono=workshop_seed["phone"],
                email=workshop_seed["email"],
                direccion=workshop_seed["address"],
                ubicacion=geo_point(*workshop_seed["point"]),
                is_active=True,
            )
            session.add(workshop)
            await session.flush()
            workshop_entities[workshop_seed["key"]] = workshop

            for category in categories:
                session.add(TallerCategoriaServicio(id_taller=workshop.id_taller, id_categoria=category.id_categoria))

            owner_seed = workshop_seed["owner"]
            owner_user = await create_user(
                session,
                role_map,
                name=owner_seed["name"],
                phone=owner_seed["phone"],
                email=owner_seed["email"],
                password=owner_seed["password"],
                role="admin_taller",
            )
            session.add(AdministradorTaller(id_usuario=owner_user.id_usuario, id_taller=workshop.id_taller))
            credentials.append(
                AccountRow(owner_user.nombre, owner_user.correo, "admin_taller", "owner", workshop.nombre, "", owner_seed["password"])
            )

            for branch_seed in workshop_seed["branches"]:
                branch = SucursalTaller(
                    id_taller=workshop.id_taller,
                    nombre=branch_seed["name"],
                    telefono=branch_seed["phone"],
                    email=branch_seed["email"],
                    direccion=branch_seed["address"],
                    ubicacion=geo_point(*branch_seed["point"]),
                    is_active=True,
                )
                session.add(branch)
                await session.flush()
                branch_entities[f"{workshop_seed['key']}:{branch_seed['key']}"] = branch

                admin_seed = branch_seed["admin"]
                branch_admin = await create_user(
                    session,
                    role_map,
                    name=admin_seed["name"],
                    phone=admin_seed["phone"],
                    email=admin_seed["email"],
                    password=admin_seed["password"],
                    role="admin_taller",
                )
                session.add(
                    UsuarioTaller(
                        id_usuario=branch_admin.id_usuario,
                        id_taller=workshop.id_taller,
                        id_sucursal=branch.id_sucursal,
                        rol_contexto="admin_sucursal",
                        estado=True,
                    )
                )
                credentials.append(
                    AccountRow(
                        branch_admin.nombre,
                        branch_admin.correo,
                        "admin_taller",
                        "admin_sucursal",
                        workshop.nombre,
                        branch.nombre,
                        admin_seed["password"],
                    )
                )

                for tech_index, tech_seed in enumerate(branch_seed["techs"], start=1):
                    tech_user = await create_user(
                        session,
                        role_map,
                        name=tech_seed["name"],
                        phone=tech_seed["phone"],
                        email=tech_seed["email"],
                        password=tech_seed["password"],
                        role="tecnico",
                    )
                    technician = Tecnico(
                        id_usuario=tech_user.id_usuario,
                        id_taller=workshop.id_taller,
                        id_sucursal=branch.id_sucursal,
                        nombre=tech_seed["name"],
                        telefono=tech_seed["phone"],
                        estado=True,
                        estado_operativo="DISPONIBLE",
                    )
                    session.add(technician)
                    await session.flush()
                    await add_week_schedule(session, technician)
                    technician_entities[f"{workshop_seed['key']}:{branch_seed['key']}:{tech_index}"] = technician
                    credentials.append(
                        AccountRow(
                            tech_user.nombre,
                            tech_user.correo,
                            "tecnico",
                            "tecnico",
                            workshop.nombre,
                            branch.nombre,
                            tech_seed["password"],
                        )
                    )

        incidents_seed = [
            {
                "client": "pedro",
                "workshop": "torque",
                "branch": "equipetrol",
                "tech": 1,
                "status": "EN_ATENCION",
                "priority": "ALTA",
                "description": "Pinchazo de llanta trasera en avenida San Martin.",
                "origin": "APP_MOVIL",
                "location": (-17.7744, -63.1948),
                "reported_at": hours_ago(7),
                "history": [
                    ("PENDIENTE", 7, "Pedro Suarez"),
                    ("ASIGNADO", 6, "SISTEMA"),
                    ("EN_CAMINO", 5, "Carlos Aguilar"),
                    ("TECNICO_EN_SITIO", 4, "Carlos Aguilar"),
                    ("EN_ATENCION", 3, "Pedro Suarez"),
                ],
                "verification": {"code": "482913", "status": "VERIFICADO", "result": "EXITOSO", "verified_hours_ago": 3},
            },
            {
                "client": "maria",
                "workshop": "torque",
                "branch": "urubo",
                "tech": 1,
                "status": "EN_CAMINO",
                "priority": "MEDIA",
                "description": "Bateria descargada cerca del puente del Urubo.",
                "origin": "APP_MOVIL",
                "location": (-17.7508, -63.2189),
                "reported_at": hours_ago(5),
                "history": [
                    ("PENDIENTE", 5, "Maria Gutierrez"),
                    ("ASIGNADO", 4, "SISTEMA"),
                    ("EN_CAMINO", 3, "Sebastian Smit"),
                ],
            },
            {
                "client": "jose",
                "workshop": "andina",
                "branch": "santos_dumont",
                "tech": 1,
                "status": "FINALIZADO",
                "priority": "CRITICA",
                "description": "Motor recalentado y fuga de agua en Santos Dumont.",
                "origin": "APP_MOVIL",
                "location": (-17.8209, -63.1697),
                "reported_at": days_ago(2),
                "history": [
                    ("PENDIENTE", 50, "Jose Lopez"),
                    ("ASIGNADO", 49, "SISTEMA"),
                    ("EN_CAMINO", 48, "Yohan Mamani"),
                    ("TECNICO_EN_SITIO", 47, "Yohan Mamani"),
                    ("EN_ATENCION", 46, "Jose Lopez"),
                    ("FINALIZADO", 43, "Yohan Mamani"),
                ],
                "payment": {"amount": "420.00", "labor": "220.00", "parts": "160.00", "commission": "42.00", "status": "PAGADO"},
            },
            {
                "client": "carla",
                "workshop": "andina",
                "branch": "plan_3000",
                "tech": 2,
                "status": "COMPLETADO",
                "priority": "ALTA",
                "description": "Falla electrica y luces sin respuesta en Plan 3000.",
                "origin": "APP_MOVIL",
                "location": (-17.8452, -63.1428),
                "reported_at": days_ago(1),
                "history": [
                    ("PENDIENTE", 28, "Carla Rojas"),
                    ("ASIGNADO", 27, "SISTEMA"),
                    ("EN_CAMINO", 26, "Hector Suazo"),
                    ("TECNICO_EN_SITIO", 25, "Hector Suazo"),
                    ("EN_ATENCION", 24, "Carla Rojas"),
                    ("COMPLETADO", 21, "Hector Suazo"),
                ],
                "payment": {"amount": "310.00", "labor": "180.00", "parts": "95.00", "commission": "31.00", "status": "PAGADO"},
            },
            {
                "client": "bruno",
                "workshop": "rutasur",
                "branch": "cristo_redentor",
                "tech": 1,
                "status": "TALLER_ASIGNADO",
                "priority": "MEDIA",
                "description": "Solicitud de grua por falla de caja en Cristo Redentor.",
                "origin": "APP_MOVIL",
                "location": (-17.7535, -63.1844),
                "reported_at": hours_ago(4),
                "history": [
                    ("PENDIENTE", 4, "Bruno Perez"),
                    ("TALLER_ASIGNADO", 3, "SISTEMA"),
                ],
            },
            {
                "client": "lucia",
                "workshop": "rutasur",
                "branch": "villa_1ro_mayo",
                "tech": 1,
                "status": "TECNICO_EN_SITIO",
                "priority": "ALTA",
                "description": "Accidente leve y solicitud de verificacion del tecnico.",
                "origin": "APP_MOVIL",
                "location": (-17.7716, -63.1103),
                "reported_at": hours_ago(6),
                "history": [
                    ("PENDIENTE", 6, "Lucia Vargas"),
                    ("ASIGNADO", 5, "SISTEMA"),
                    ("EN_CAMINO", 4, "Oscar Hurtado"),
                    ("TECNICO_EN_SITIO", 2, "Oscar Hurtado"),
                ],
                "verification": {"code": "731225", "status": "PENDIENTE", "result": "PENDIENTE"},
            },
            {
                "client": "andres",
                "workshop": None,
                "branch": None,
                "tech": None,
                "status": "PENDIENTE",
                "priority": "BAJA",
                "description": "Sin combustible en avenida Banzer, esperando asignacion.",
                "origin": "APP_MOVIL",
                "location": (-17.7393, -63.1701),
                "reported_at": hours_ago(2),
                "history": [("PENDIENTE", 2, "Andres Molina")],
            },
            {
                "client": "sofia",
                "workshop": "torque",
                "branch": "equipetrol",
                "tech": 2,
                "status": "CANCELADO",
                "priority": "MEDIA",
                "description": "Ruido en frenos, cliente cancelo antes de la llegada.",
                "origin": "APP_MOVIL",
                "location": (-17.7734, -63.1976),
                "reported_at": hours_ago(9),
                "history": [
                    ("PENDIENTE", 9, "Sofia Cuiza"),
                    ("ASIGNADO", 8, "SISTEMA"),
                    ("EN_CAMINO", 7, "Joaquin Almos"),
                    ("CANCELADO", 6, "Sofia Cuiza"),
                ],
            },
        ]

        created_incidents: list[Incidente] = []
        for item in incidents_seed:
            workshop = workshop_entities.get(item["workshop"]) if item["workshop"] else None
            branch = branch_entities.get(f"{item['workshop']}:{item['branch']}") if item["workshop"] and item["branch"] else None
            technician = technician_entities.get(f"{item['workshop']}:{item['branch']}:{item['tech']}") if item["workshop"] and item["branch"] and item["tech"] else None
            client_user = client_users[item["client"]]
            vehicle = client_vehicles[item["client"]]

            incident = Incidente(
                id_vehiculo=vehicle.id_vehiculo,
                id_taller=workshop.id_taller if workshop else None,
                id_sucursal=branch.id_sucursal if branch else None,
                id_usuario_cliente=client_user.id_usuario,
                id_tecnico=technician.id_tecnico if technician else None,
                telefono=client_user.telefono,
                descripcion=item["description"],
                estado_incidente=item["status"],
                prioridad_incidente=item["priority"],
                origen=item["origin"],
                origen_registro="ONLINE",
                resumen_ia=item["description"],
                analisis_consolidado=f"Clasificacion automatica para caso: {item['description']}",
                ubicacion_emergencia=geo_point(*item["location"]),
                fecha_reporte=item["reported_at"],
            )
            session.add(incident)
            await session.flush()

            for state, offset_hours, actor in item["history"]:
                session.add(
                    HistorialIncidente(
                        id_incidente=incident.id_incidente,
                        id_taller=workshop.id_taller if workshop else None,
                        id_sucursal=branch.id_sucursal if branch else None,
                        incidente_estado_nuevo=state,
                        historial_actor=actor,
                        fecha=hours_ago(offset_hours),
                    )
                )

            if workshop and technician:
                session.add(
                    AsignacionIncidente(
                        id_incidente=incident.id_incidente,
                        id_taller=workshop.id_taller,
                        id_tecnico=technician.id_tecnico,
                        estado_asignacion="ASIGNADO" if item["status"] != "CANCELADO" else "CANCELADO",
                        score_asignacion=Decimal("92.50"),
                        distancia_km=Decimal("4.80"),
                        fecha_asignacion=item["reported_at"] + timedelta(minutes=35),
                    )
                )

            if item.get("verification") and technician:
                verification = item["verification"]
                session.add(
                    VerificacionTecnico(
                        id_incidente=incident.id_incidente,
                        id_tecnico=technician.id_tecnico,
                        metodo_verificacion="PIN",
                        codigo_verificacion=verification["code"],
                        estado_verificacion=verification["status"],
                        resultado=verification["result"],
                        fecha_verificacion=hours_ago(verification.get("verified_hours_ago", 0))
                        if verification["status"] == "VERIFICADO"
                        else None,
                        intentos=1 if verification["status"] == "VERIFICADO" else 0,
                        usuario_validador=client_user.nombre if verification["status"] == "VERIFICADO" else None,
                    )
                )

            if item.get("payment") and workshop:
                payment = item["payment"]
                session.add(
                    Pago(
                        id_incidente=incident.id_incidente,
                        id_taller=workshop.id_taller,
                        monto=Decimal(payment["amount"]),
                        monto_comision=Decimal(payment["commission"]),
                        estado_pago=payment["status"],
                        fecha_pago=item["reported_at"] + timedelta(hours=8),
                        mano_de_obra=Decimal(payment["labor"]),
                        repuestos=Decimal(payment["parts"]),
                        observaciones="Pago de demo multi-tenant",
                    )
                )

            created_incidents.append(incident)

        follow_up_appointments = [
            {
                "incident_index": 2,
                "client": "jose",
                "workshop": "andina",
                "branch": "santos_dumont",
                "tech": 1,
                "date": datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1, hours=3),
                "reason": "Control de temperatura y nivel de refrigerante.",
            },
            {
                "incident_index": 3,
                "client": "carla",
                "workshop": "andina",
                "branch": "plan_3000",
                "tech": 2,
                "date": datetime.now(UTC).replace(tzinfo=None) + timedelta(days=2, hours=2),
                "reason": "Revision del sistema electrico posterior al auxilio.",
            },
        ]

        for appointment in follow_up_appointments:
            incident = created_incidents[appointment["incident_index"]]
            client = client_users[appointment["client"]]
            vehicle = client_vehicles[appointment["client"]]
            workshop = workshop_entities[appointment["workshop"]]
            branch = branch_entities[f"{appointment['workshop']}:{appointment['branch']}"]
            technician = technician_entities[f"{appointment['workshop']}:{appointment['branch']}:{appointment['tech']}"]
            session.add(
                Cita(
                    id_incidente_origen=incident.id_incidente,
                    id_cliente=client.id_usuario,
                    id_vehiculo=vehicle.id_vehiculo,
                    id_taller=workshop.id_taller,
                    id_sucursal=branch.id_sucursal,
                    id_tecnico=technician.id_tecnico,
                    fecha_hora=appointment["date"],
                    duracion_minutos=60,
                    estado="CONFIRMADA",
                    tipo="POST_AUXILIO",
                    motivo=appointment["reason"],
                    observaciones="Cita generada para demo multi-tenant.",
                    prioridad="MEDIA",
                    creado_por=technician.id_usuario,
                    rol_creador="TECNICO",
                )
            )

        await session.commit()

    write_credentials(credentials)

    print("Demo multi-tenant regenerada correctamente.")
    print(f"Credenciales Markdown: {MARKDOWN_CREDENTIALS}")
    print(f"Credenciales CSV: {CSV_CREDENTIALS}")
    print("Resumen esperado:")
    print("- 3 cadenas de talleres")
    print("- 6 sucursales en Santa Cruz de la Sierra")
    print("- 3 owners de cadena")
    print("- 6 administradores de sucursal")
    print("- 12 tecnicos propios")
    print("- 8 clientes globales")
    print("- 8 incidentes demo y 2 citas de seguimiento")


if __name__ == "__main__":
    asyncio.run(seed())
