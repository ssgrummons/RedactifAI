# Alembic Database Migrations

This directory contains Alembic migrations for the RedactifAI database schema.

## Initial Setup

**Generate the initial migration (one-time):**

```bash
# Make sure your database environment variables are set
export DB_USER=redactifai
export DB_PASSWORD=redactifai_password
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=redactifai

# Generate migration from current models
poetry run alembic revision --autogenerate -m "initial schema"

# Apply the migration
poetry run alembic upgrade head
```

## Common Commands

**Create a new migration after changing models:**
```bash
poetry run alembic revision --autogenerate -m "description of changes"
```

**Apply all pending migrations:**
```bash
poetry run alembic upgrade head
```

**Rollback one migration:**
```bash
poetry run alembic downgrade -1
```

**View current migration status:**
```bash
poetry run alembic current
```

**View migration history:**
```bash
poetry run alembic history --verbose
```

## How It Works

1. **env.py** - Connects to your database and imports your SQLAlchemy models
2. **script.py.mako** - Template for generating new migration files
3. **versions/** - Contains timestamped migration scripts

## Docker Usage

In Docker, migrations run automatically on API startup via:
```dockerfile
CMD ["sh", "-c", "poetry run alembic upgrade head && uvicorn src.api.main:app ..."]
```

No manual intervention needed in production.

## Adding Dependencies

Alembic needs `psycopg2` (not `psycopg2-binary`) for PostgreSQL:

```bash
poetry add psycopg2-binary  # Development
# For production: poetry add psycopg2
```

## Troubleshooting

**"Target database is not up to date"**
- Run `poetry run alembic upgrade head` to apply pending migrations

**"Can't locate revision identified by 'xxxxx'"**
- Migration files out of sync. Check `poetry run alembic_version` table in DB

**Environment variables not found**
- Set DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME before running commands
