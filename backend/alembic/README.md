# Database Migrations

This directory contains Alembic database migrations for the Rain Analysis backend.

## Quick Start

### Apply migrations

```bash
# Upgrade to the latest version
alembic upgrade head

# Check current version
alembic current

# View migration history
alembic history
```

### Create new migration

```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "Description of changes"

# Create empty migration (for data migrations)
alembic revision -m "Description of changes"
```

### Rollback migrations

```bash
# Rollback one migration
alembic downgrade -1

# Rollback to specific version
alembic downgrade <revision_id>

# Rollback all migrations
alembic downgrade base
```

## Important Notes

### Before Creating Migrations

1. **Review auto-generated migrations**: Alembic's autogenerate is smart but not perfect. Always review the generated migration file before applying it.

2. **Test migrations**: Test both `upgrade` and `downgrade` paths:
   ```bash
   alembic upgrade head
   alembic downgrade -1
   alembic upgrade head
   ```

3. **Data migrations**: If you need to migrate data (not just schema), create an empty migration and write the data transformation logic manually.

### Model Changes

When you modify SQLAlchemy models in `app/models/`:

1. Create a new migration:
   ```bash
   alembic revision --autogenerate -m "Add new column to sensors"
   ```

2. Review the generated file in `alembic/versions/`

3. Apply the migration:
   ```bash
   alembic upgrade head
   ```

### Async Support

This project uses async SQLAlchemy. The `env.py` file is configured to handle async database operations automatically.

### Database URL

The database URL is configured in `.env` file via `DATABASE_URL` setting. Alembic reads it from `app.config.settings` in `env.py`.

## Troubleshooting

### "FAILED: Directory alembic already exists"

If you need to reinitialize Alembic (rare), remove the directory first:
```bash
rm -rf alembic alembic.ini
alembic init alembic
```

### Migration conflicts

If multiple developers create migrations in parallel, you may need to merge migration branches. See [Alembic documentation on branching](https://alembic.sqlalchemy.org/en/latest/branches.html).

### Rolling back in production

**Be careful with downgrades in production!** Always:
- Backup the database first
- Test the downgrade path in staging
- Consider data loss implications

## Resources

- [Alembic Tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [Alembic Auto-generate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
- [SQLAlchemy Async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
