from alembic import op
import sqlalchemy as sa

revision = 'd3337c4381fd'
down_revision = '2bf1f3cb2f9a'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('sessions') as b:
        try:
            b.add_column(sa.Column('status', sa.String(), nullable=True))
            b.add_column(sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
            b.add_column(sa.Column('refresh_expires_at', sa.DateTime(timezone=True), nullable=True))
            b.add_column(sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
            b.add_column(sa.Column('device_fingerprint', sa.String(), nullable=True))
        except Exception:
            pass

    op.create_table(
        'refresh_tokens',
        sa.Column('jti', sa.String(length=36), primary_key=True),
        sa.Column('session_id', sa.String(length=36), sa.ForeignKey('sessions.id', ondelete='CASCADE'), index=True),
        sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('replaced_by', sa.String(length=36), nullable=True),
    )

    op.create_table(
        'session_events',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('session_id', sa.String(length=36), sa.ForeignKey('sessions.id', ondelete='CASCADE'), index=True),
        sa.Column('event', sa.String(length=32), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('details', sa.Text(), nullable=True),
    )

    try:
        with op.batch_alter_table('access_codes') as b:
            b.add_column(sa.Column('max_concurrent_sessions', sa.Integer(), server_default='1', nullable=False))
            b.add_column(sa.Column('cooldown_seconds', sa.Integer(), server_default='0', nullable=False))
    except Exception:
        pass


def downgrade():
    op.drop_table('session_events')
    op.drop_table('refresh_tokens')

    try:
        with op.batch_alter_table('access_codes') as b:
            b.drop_column('max_concurrent_sessions')
            b.drop_column('cooldown_seconds')
    except Exception:
        pass

    with op.batch_alter_table('sessions') as b:
        for col in ('status', 'expires_at', 'refresh_expires_at', 'last_seen_at', 'device_fingerprint'):
            try:
                b.drop_column(col)
            except Exception:
                pass
