"""extend_bitacora_and_add_indexes

Revision ID: 6f00fc9d2680
Revises: 029711f1beca
Create Date: 2026-06-03 17:23:15.784880

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = '6f00fc9d2680'
down_revision: Union[str, Sequence[str], None] = '029711f1beca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Renombrar id_usuario a id_usuario_actor en bitacora
    op.alter_column('bitacora', 'id_usuario', new_column_name='id_usuario_actor')

    # 2. Agregar nuevas columnas de auditoría avanzada a bitacora
    op.add_column('bitacora', sa.Column('rol_usuario', sa.String(length=50), nullable=True))
    op.add_column('bitacora', sa.Column('id_taller', sa.UUID(), nullable=True))
    op.add_column('bitacora', sa.Column('id_sucursal_contexto', sa.UUID(), nullable=True))
    op.add_column('bitacora', sa.Column('id_sucursal_afectada', sa.UUID(), nullable=True))
    op.add_column('bitacora', sa.Column('tipo_entidad', sa.String(length=100), nullable=True))
    op.add_column('bitacora', sa.Column('id_entidad', sa.UUID(), nullable=True))
    op.add_column('bitacora', sa.Column('datos_antes', JSONB(), nullable=True))
    op.add_column('bitacora', sa.Column('datos_despues', JSONB(), nullable=True))

    # 3. Crear claves foráneas para bitacora (solo hacia taller para control de tenant, sin restricción hacia sucursales para preservar historial)
    op.create_foreign_key('fk_bitacora_taller', 'bitacora', 'taller', ['id_taller'], ['id_taller'], ondelete='SET NULL')

    # 4. Crear Índices de Rendimiento para Consultas de Scoping y Auditoría
    # Índices en 'incidente'
    op.create_index('ix_incidente_id_taller', 'incidente', ['id_taller'], unique=False)
    op.create_index('ix_incidente_id_sucursal', 'incidente', ['id_sucursal'], unique=False)
    op.create_index('ix_incidente_id_usuario_cliente', 'incidente', ['id_usuario_cliente'], unique=False)
    op.create_index('ix_incidente_id_tecnico', 'incidente', ['id_tecnico'], unique=False)

    # Índices en 'tecnico'
    op.create_index('ix_tecnico_id_taller', 'tecnico', ['id_taller'], unique=False)
    op.create_index('ix_tecnico_id_sucursal', 'tecnico', ['id_sucursal'], unique=False)
    op.create_index('ix_tecnico_id_usuario', 'tecnico', ['id_usuario'], unique=False)

    # Índices en 'bitacora'
    op.create_index('ix_bitacora_id_usuario_actor', 'bitacora', ['id_usuario_actor'], unique=False)
    op.create_index('ix_bitacora_id_taller', 'bitacora', ['id_taller'], unique=False)
    op.create_index('ix_bitacora_id_sucursal_contexto', 'bitacora', ['id_sucursal_contexto'], unique=False)
    op.create_index('ix_bitacora_id_sucursal_afectada', 'bitacora', ['id_sucursal_afectada'], unique=False)


def downgrade() -> None:
    # 1. Eliminar índices
    op.drop_index('ix_bitacora_id_sucursal_afectada', table_name='bitacora')
    op.drop_index('ix_bitacora_id_sucursal_contexto', table_name='bitacora')
    op.drop_index('ix_bitacora_id_taller', table_name='bitacora')
    op.drop_index('ix_bitacora_id_usuario_actor', table_name='bitacora')

    op.drop_index('ix_tecnico_id_usuario', table_name='tecnico')
    op.drop_index('ix_tecnico_id_sucursal', table_name='tecnico')
    op.drop_index('ix_tecnico_id_taller', table_name='tecnico')

    op.drop_index('ix_incidente_id_tecnico', table_name='incidente')
    op.drop_index('ix_incidente_id_usuario_cliente', table_name='incidente')
    op.drop_index('ix_incidente_id_sucursal', table_name='incidente')
    op.drop_index('ix_incidente_id_taller', table_name='incidente')

    # 2. Eliminar llaves foráneas de bitacora
    op.drop_constraint('fk_bitacora_taller', 'bitacora', type_='foreignkey')

    # 3. Eliminar columnas
    op.drop_column('bitacora', 'datos_despues')
    op.drop_column('bitacora', 'datos_antes')
    op.drop_column('bitacora', 'id_entidad')
    op.drop_column('bitacora', 'tipo_entidad')
    op.drop_column('bitacora', 'id_sucursal_afectada')
    op.drop_column('bitacora', 'id_sucursal_contexto')
    op.drop_column('bitacora', 'id_taller')
    op.drop_column('bitacora', 'rol_usuario')

    # 4. Revertir nombre de id_usuario_actor
    op.alter_column('bitacora', 'id_usuario_actor', new_column_name='id_usuario')
