**Objetivo**
Clonar la base actual a una base nueva en tu cuenta de Neon, manteniendo la misma estructura y los mismos datos.

**Qué hace el script**
- Aplica las migraciones de Alembic sobre la base destino
- Crea la estructura completa, incluyendo `postgis`
- Vacía las tablas destino
- Copia los datos tabla por tabla desde la base origen
- Sincroniza secuencias

**Antes de ejecutar**
1. Crea una base nueva en tu cuenta de Neon.
2. Copia su connection string.
3. Verifica que la base destino permita `postgis`.

**Variables necesarias**
En `smart_mechanic-backend/.env`:

```env
SOURCE_DATABASE_URL="postgresql+asyncpg://...base_actual..."
TARGET_DATABASE_URL="postgresql+asyncpg://...tu_neon_nueva...?ssl=require"
```

Si no defines `SOURCE_DATABASE_URL`, el script usa `DATABASE_URL` como origen.

**Ejecutar**
```powershell
cd smart_mechanic-backend
.venv\Scripts\Activate.ps1
python scratch\clone_postgres_db.py
```

**Después**
Cuando confirmes que la clonación salió bien, cambia:

```env
DATABASE_URL="postgresql+asyncpg://...tu_neon_nueva...?ssl=require"
```

y deja esa como base principal del proyecto.

**Notas**
- El backend usa PostGIS.
- El script no toca tus archivos de código, solo las bases.
- No subas tus URLs de Neon a GitHub.
