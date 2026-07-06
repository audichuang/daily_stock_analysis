"""Alembic environment for the ``market`` schema only.

Reads DATABASE_URL from the environment, targets the market-schema metadata, and
scopes autogenerate to the market schema so it never touches the dashboard's
``app`` schema or ``public``.
"""

from alembic import context
from sqlalchemy import create_engine, pool, schema

import market_data.models  # noqa: F401  (register models on Base.metadata)
from market_data.db import MARKET_SCHEMA, Base, database_url

target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    # only manage the market schema; ignore public / app entirely
    if type_ == "schema":
        return name == MARKET_SCHEMA
    return True


def _configure(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        version_table_schema=MARKET_SCHEMA,
        compare_type=True,
    )


def run_migrations_online():
    engine = create_engine(database_url(), poolclass=pool.NullPool, future=True)
    with engine.connect() as connection:
        # ensure the target schema exists on a fresh database, else the
        # version table (version_table_schema=market) can't be created.
        connection.execute(schema.CreateSchema(MARKET_SCHEMA, if_not_exists=True))
        connection.commit()
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()


def run_migrations_offline():
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        version_table_schema=MARKET_SCHEMA,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
