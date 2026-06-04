import asyncio
import uuid
from app.packages.identity.domain.models import Usuario
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.packages.workshops.domain.models import Taller, SucursalTaller, UsuarioTaller, Tecnico
from app.packages.emergencies.domain.models import Incidente, HistorialIncidente

async def cleanup():
    print("Iniciando corrección y limpieza de sucursales...")
    async with AsyncSessionLocal() as session:
        # 1. Obtener todos los talleres
        taller_res = await session.execute(select(Taller))
        talleres = taller_res.scalars().all()
        
        for taller in talleres:
            print(f"\nProcesando taller: {taller.nombre} (ID: {taller.id_taller})")
            
            # 2. Buscar si ya tiene una Casa Matriz
            branch_res = await session.execute(
                select(SucursalTaller).where(
                    SucursalTaller.id_taller == taller.id_taller,
                    SucursalTaller.nombre == "Casa Matriz"
                )
            )
            casa_matriz = branch_res.scalars().first()
            
            if not casa_matriz:
                # Crear "Casa Matriz"
                casa_matriz = SucursalTaller(
                    id_sucursal=uuid.uuid4(),
                    id_taller=taller.id_taller,
                    nombre="Casa Matriz",
                    telefono=taller.telefono,
                    email=taller.email,
                    direccion=taller.direccion or "Dirección Principal",
                    ubicacion=taller.ubicacion,
                    is_active=True
                )
                session.add(casa_matriz)
                print(f"-> Creada sucursal 'Casa Matriz' para taller: {taller.nombre}")
                await session.flush()
            else:
                print(f"-> Casa Matriz existente encontrada (ID: {casa_matriz.id_sucursal})")
                
            # 3. Mover todos los incidentes del taller a Casa Matriz
            inc_res = await session.execute(
                select(Incidente).where(Incidente.id_taller == taller.id_taller)
            )
            incidents = inc_res.scalars().all()
            moved_incidents = 0
            for inc in incidents:
                if inc.id_sucursal != casa_matriz.id_sucursal:
                    inc.id_sucursal = casa_matriz.id_sucursal
                    session.add(inc)
                    moved_incidents += 1
            if moved_incidents:
                print(f"   - Se movieron {moved_incidents} incidentes a Casa Matriz.")

            # 4. Mover todos los técnicos del taller a Casa Matriz
            tec_res = await session.execute(
                select(Tecnico).where(Tecnico.id_taller == taller.id_taller)
            )
            technicians = tec_res.scalars().all()
            moved_techs = 0
            for tec in technicians:
                if tec.id_sucursal != casa_matriz.id_sucursal:
                    tec.id_sucursal = casa_matriz.id_sucursal
                    session.add(tec)
                    moved_techs += 1
            if moved_techs:
                print(f"   - Se movieron {moved_techs} técnicos a Casa Matriz.")

            # 5. Mover los registros de historial a Casa Matriz
            hist_res = await session.execute(
                select(HistorialIncidente).where(HistorialIncidente.id_taller == taller.id_taller)
            )
            historiales = hist_res.scalars().all()
            moved_hist = 0
            for hist in historiales:
                if hist.id_sucursal != casa_matriz.id_sucursal:
                    hist.id_sucursal = casa_matriz.id_sucursal
                    session.add(hist)
                    moved_hist += 1
            if moved_hist:
                print(f"   - Se movieron {moved_hist} registros de historial a Casa Matriz.")

        await session.commit()
        print("\nLimpieza y corrección completada con éxito.")

if __name__ == "__main__":
    asyncio.run(cleanup())
