import asyncio
import uuid
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.packages.workshops.domain.models import Taller, SucursalTaller, UsuarioTaller, Tecnico
from app.packages.emergencies.domain.models import Incidente, HistorialIncidente
from app.packages.identity.domain.models import Usuario

async def seed():
    print("Iniciando seed de Casa Matriz de forma idempotente...")
    async with AsyncSessionLocal() as session:
        # 1. Obtener todos los talleres
        taller_res = await session.execute(select(Taller))
        talleres = taller_res.scalars().all()
        
        for taller in talleres:
            print(f"\nProcesando taller: {taller.nombre} (ID: {taller.id_taller})")
            
            # 2. Buscar si ya existe "Casa Matriz" para este taller
            branch_res = await session.execute(
                select(SucursalTaller).where(
                    SucursalTaller.id_taller == taller.id_taller,
                    SucursalTaller.nombre == "Casa Matriz"
                )
            )
            default_branch = branch_res.scalars().first()
            
            if not default_branch:
                # Crear "Casa Matriz" por defecto si no existe
                default_branch = SucursalTaller(
                    id_sucursal=uuid.uuid4(),
                    id_taller=taller.id_taller,
                    nombre="Casa Matriz",
                    telefono=taller.telefono,
                    email=taller.email,
                    direccion=taller.direccion or "Dirección Principal",
                    ubicacion=taller.ubicacion,
                    is_active=True
                )
                session.add(default_branch)
                print(f"-> Creada sucursal 'Casa Matriz' para taller: {taller.nombre}")
                # Guardamos para tener el ID generado
                await session.flush()
            else:
                print(f"-> Encontrada sucursal existente 'Casa Matriz' (ID: {default_branch.id_sucursal})")

            # 3. Asociar usuarios de taller huérfanos
            ut_res = await session.execute(
                select(UsuarioTaller).where(
                    UsuarioTaller.id_taller == taller.id_taller,
                    UsuarioTaller.id_sucursal.is_(None)
                )
            )
            ut_orphans = ut_res.scalars().all()
            for ut in ut_orphans:
                ut.id_sucursal = default_branch.id_sucursal
                session.add(ut)
            if ut_orphans:
                print(f"   - Vinculados {len(ut_orphans)} usuarios de taller huérfanos.")

            # 4. Asociar técnicos huérfanos
            tec_res = await session.execute(
                select(Tecnico).where(
                    Tecnico.id_taller == taller.id_taller,
                    Tecnico.id_sucursal.is_(None)
                )
            )
            tec_orphans = tec_res.scalars().all()
            for tec in tec_orphans:
                tec.id_sucursal = default_branch.id_sucursal
                session.add(tec)
            if tec_orphans:
                print(f"   - Vinculados {len(tec_orphans)} técnicos huérfanos.")

            # 5. Asociar incidentes activos o cerrados huérfanos (estado != PENDIENTE)
            inc_res = await session.execute(
                select(Incidente).where(
                    Incidente.id_taller == taller.id_taller,
                    Incidente.id_sucursal.is_(None),
                    Incidente.estado_incidente != "PENDIENTE"
                )
            )
            inc_orphans = inc_res.scalars().all()
            for inc in inc_orphans:
                inc.id_sucursal = default_branch.id_sucursal
                session.add(inc)
            if inc_orphans:
                print(f"   - Vinculados {len(inc_orphans)} incidentes no pendientes huérfanos.")

            # 6. Asociar historiales de incidentes huérfanos
            hist_res = await session.execute(
                select(HistorialIncidente).where(
                    HistorialIncidente.id_taller == taller.id_taller,
                    HistorialIncidente.id_sucursal.is_(None)
                )
            )
            hist_orphans = hist_res.scalars().all()
            for hist in hist_orphans:
                hist.id_sucursal = default_branch.id_sucursal
                session.add(hist)
            if hist_orphans:
                print(f"   - Vinculados {len(hist_orphans)} registros de historial huérfanos.")

        await session.commit()
        print("\nSeed de Casa Matriz completado con éxito.")

if __name__ == "__main__":
    asyncio.run(seed())
