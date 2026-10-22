"""Copy a legacy database into a migrated, empty destination. Never modifies source."""
import argparse
import json
from sqlalchemy import create_engine, inspect, select, text
from .db import Base, engine
from .models import core, hr, work, leave


def import_data(source_url, destination=engine):
    source = create_engine(source_url)
    if source.url == destination.url:
        raise ValueError("Source and destination must differ")
    # Read first, then write in a single destination transaction. Stop the old app
    # and scheduler during cutover to keep all tables at the same logical point.
    skip = {"sessions", "rate_limit_state"}
    try:
        with source.connect() as original, destination.begin() as target:
            source_tables = set(inspect(original).get_table_names())
            target_tables = set(inspect(target).get_table_names())
            required = {value.__tablename__ for value in vars(core).values()
                        if getattr(value, "__module__", None) == core.__name__ and hasattr(value, "__tablename__")}
            if not required.issubset(source_tables):
                raise ValueError("Source does not contain the full legacy schema")
            if not set(Base.metadata.tables).issubset(target_tables):
                raise ValueError("Run alembic upgrade head on the destination first")
            for table in Base.metadata.sorted_tables:
                if target.execute(select(table).limit(1)).first():
                    raise ValueError(f"Destination must be empty: {table.name}")
            counts = {}
            for table in Base.metadata.sorted_tables:
                if table.name in skip or table.name not in source_tables:
                    continue
                source_columns = {c["name"] for c in inspect(original).get_columns(table.name)}
                if not set(table.columns.keys()).issubset(source_columns):
                    raise ValueError(f"Source schema differs for {table.name}; review before importing")
                rows = original.execute(select(table)).mappings().all()
                if rows:
                    target.execute(table.insert(), [dict(row) for row in rows])
                counts[table.name] = len(rows)
                if target.dialect.name == "postgresql":
                    for column in table.primary_key:
                        if column.name == "id":
                            # Identifiers come exclusively from application metadata.
                            target.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {table.name}"))
            if target.dialect.name == "sqlite":
                if target.exec_driver_sql("PRAGMA foreign_key_check").first():
                    raise ValueError("Source contains dangling references; repair before importing")
            return counts
    finally:
        source.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Source SQLAlchemy URL; use a backup, not the live database")
    args = parser.parse_args()
    print(json.dumps(import_data(args.source), indent=2))


if __name__ == "__main__":
    main()
