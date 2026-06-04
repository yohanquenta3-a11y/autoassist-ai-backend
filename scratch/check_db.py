import asyncio
import uuid
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.packages.workshops.domain.models import UsuarioTaller, SucursalTaller
from app.packages.identity.domain.models import Usuario
from app.packages.emergencies.domain.models import Incidente

async def check():
    session = AsyncSessionLocal()
    try:
        # Check user
        user_res = await session.execute(select(Usuario).where(Usuario.correo.like('%alejandro%')))
        user = user_res.scalars().first()
        if not user:
            print("User alejandro not found!")
            return
        print(f"User: {user.nombre} | ID: {user.id_usuario} | Rol: {user.rol_nombre}")
        
        # Check UsuarioTaller
        ut_res = await session.execute(select(UsuarioTaller).where(UsuarioTaller.id_usuario == user.id_usuario))
        ut_links = ut_res.scalars().all()
        for x in ut_links:
            print(f"UT Link: {x.id_usuario_taller} | Taller: {x.id_taller} | Branch: {x.id_sucursal} | Rol Contexto: {x.rol_contexto} | Estado: {x.estado}")
            
            if x.id_sucursal:
                branch_res = await session.execute(select(SucursalTaller).where(SucursalTaller.id_sucursal == x.id_sucursal))
                b = branch_res.scalars().first()
                if b:
                    print(f"  Branch Name: '{b.nombre}' | Is Active: {b.is_active}")
        
        # Check total incidents for this taller and branch
        if ut_links:
            taller_id = ut_links[0].id_taller
            branch_id = ut_links[0].id_sucursal
            
            inc_all_res = await session.execute(select(Incidente).where(Incidente.id_taller == taller_id))
            inc_all = inc_all_res.scalars().all()
            print(f"\nTotal incidents for workshop {taller_id}: {len(inc_all)}")
            
            inc_branch_res = await session.execute(select(Incidente).where(Incidente.id_taller == taller_id, Incidente.id_sucursal == branch_id))
            inc_branch = inc_branch_res.scalars().all()
            print(f"Total incidents for branch {branch_id}: {len(inc_branch)}")
            
            null_branch_res = await session.execute(select(Incidente).where(Incidente.id_taller == taller_id, Incidente.id_sucursal.is_(None)))
            null_branch = null_branch_res.scalars().all()
            print(f"Total incidents with NULL branch: {len(null_branch)}")
            
            # Print a few incidents to see their branch IDs
            for i in inc_all[:5]:
                print(f"Incident: {i.id_incidente} | Branch: {i.id_sucursal} | Estado: {i.estado_incidente}")
                
    finally:
        await session.close()

if __name__ == "__main__":
    asyncio.run(check())
