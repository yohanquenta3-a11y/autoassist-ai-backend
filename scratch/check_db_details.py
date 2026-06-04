import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.packages.workshops.domain.models import Taller, SucursalTaller, UsuarioTaller, Tecnico
from app.packages.emergencies.domain.models import Incidente
from app.packages.identity.domain.models import Usuario

async def check():
    session = AsyncSessionLocal()
    try:
        # 1. Print all users
        print("--- USERS ---")
        user_res = await session.execute(select(Usuario))
        users = user_res.scalars().all()
        for u in users:
            print(f"User: {u.nombre} | ID: {u.id_usuario} | Rol: {u.rol_nombre}")
            
        # 2. Print all workshops
        print("\n--- WORKSHOPS ---")
        taller_res = await session.execute(select(Taller))
        talleres = taller_res.scalars().all()
        for t in talleres:
            print(f"Workshop: {t.nombre} | ID: {t.id_taller}")
            
        # 3. Print all branches
        print("\n--- BRANCHES ---")
        branch_res = await session.execute(select(SucursalTaller))
        branches = branch_res.scalars().all()
        for b in branches:
            print(f"Branch: '{b.nombre}' | ID: {b.id_sucursal} | Workshop ID: {b.id_taller} | Active: {b.is_active}")

        # 4. Print all UsuarioTaller mappings
        print("\n--- USUARIO TALLER ---")
        ut_res = await session.execute(select(UsuarioTaller))
        uts = ut_res.scalars().all()
        for x in uts:
            u_name = next((u.nombre for u in users if u.id_usuario == x.id_usuario), "Unknown")
            b_name = next((b.nombre for b in branches if b.id_sucursal == x.id_sucursal), "None")
            print(f"UT: {u_name} ({x.rol_contexto}) -> Branch: '{b_name}' ({x.id_sucursal}) | Taller: {x.id_taller}")

        # 5. Print all incidents and their branches
        print("\n--- INCIDENTS ---")
        inc_res = await session.execute(select(Incidente))
        incs = inc_res.scalars().all()
        print(f"Total Incidents in DB: {len(incs)}")
        for i in incs[:10]:
            b_name = next((b.nombre for b in branches if b.id_sucursal == i.id_sucursal), "None")
            print(f"Incident: {i.id_incidente} | Branch: '{b_name}' ({i.id_sucursal}) | Estado: {i.estado_incidente}")
            
    finally:
        await session.close()

if __name__ == "__main__":
    asyncio.run(check())
