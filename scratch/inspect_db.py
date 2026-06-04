import asyncio
import uuid
from app.core.database import AsyncSessionLocal
from sqlalchemy import select
from app.packages.identity.domain.models import Usuario, Rol
from app.packages.workshops.domain.models import Taller, AdministradorTaller, UsuarioTaller, Tecnico

async def inspect():
    async with AsyncSessionLocal() as session:
        print("--- ROLES ---")
        res = await session.execute(select(Rol))
        for r in res.scalars().all():
            print(f"Rol ID: {r.id_rol}, Nombre: {r.nombre}")

        print("\n--- USUARIOS ---")
        res = await session.execute(select(Usuario))
        for u in res.scalars().all():
            print(f"User ID: {u.id_usuario}, Nombre: {u.nombre}, Correo: {u.correo}, Rol ID: {u.id_rol}, Rol Nombre: {u.rol_nombre}")

        print("\n--- TALLERES ---")
        res = await session.execute(select(Taller))
        for t in res.scalars().all():
            print(f"Taller ID: {t.id_taller}, Nombre: {t.nombre}, NIT: {t.nit}")

        print("\n--- ADMINISTRADORES TALLER ---")
        res = await session.execute(select(AdministradorTaller))
        for a in res.scalars().all():
            print(f"Admin Taller ID: {a.id_admin_taller}, User ID: {a.id_usuario}, Taller ID: {a.id_taller}")

        print("\n--- USUARIO TALLER ---")
        res = await session.execute(select(UsuarioTaller))
        for ut in res.scalars().all():
            print(f"Usuario Taller ID: {ut.id_usuario_taller}, User ID: {ut.id_usuario}, Taller ID: {ut.id_taller}, Sucursal: {ut.id_sucursal}, Rol: {ut.rol_contexto}")

        print("\n--- TECNICOS ---")
        res = await session.execute(select(Tecnico))
        for tec in res.scalars().all():
            print(f"Tecnico ID: {tec.id_tecnico}, User ID: {tec.id_usuario}, Taller ID: {tec.id_taller}, Nombre: {tec.nombre}")

if __name__ == "__main__":
    asyncio.run(inspect())
