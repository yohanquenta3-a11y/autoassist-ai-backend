import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def main():
    print("Checking and updating pago table schema...")
    async with AsyncSessionLocal() as session:
        try:
            # Check columns in pago
            result = await session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'pago';
            """))
            columns = [row[0] for row in result.fetchall()]
            print("Current columns in pago:", columns)
            
            # Add mano_de_obra if not exists
            if 'mano_de_obra' not in columns:
                print("Adding mano_de_obra column...")
                await session.execute(text("ALTER TABLE pago ADD COLUMN mano_de_obra NUMERIC(10, 2);"))
            
            # Add repuestos if not exists
            if 'repuestos' not in columns:
                print("Adding repuestos column...")
                await session.execute(text("ALTER TABLE pago ADD COLUMN repuestos NUMERIC(10, 2);"))
                
            # Add observaciones if not exists
            if 'observaciones' not in columns:
                print("Adding observaciones column...")
                await session.execute(text("ALTER TABLE pago ADD COLUMN observaciones TEXT;"))
                
            await session.commit()
            print("Database schema update completed successfully.")
        except Exception as e:
            print("Error updating database schema:", e)

if __name__ == "__main__":
    asyncio.run(main())
