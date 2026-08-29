# AXIS database migrations

Migrations are managed by Alembic and read `DATABASE_URL` from the environment. The URL must use
the `postgresql+asyncpg://` driver in deployed environments. Run migrations through
`scripts/init_database.py` so credentials are never placed in `alembic.ini` or command history.
