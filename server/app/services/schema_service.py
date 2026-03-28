from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateIndex
from sqlalchemy.schema import CreateTable

from app.db.base import Base


def _sqlite_table_columns(engine: Engine, table_name: str) -> set[str]:
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        rows = list(cursor.execute(f"PRAGMA table_info({table_name})"))
        return {str(row[1]) for row in rows if len(row) >= 2}
    finally:
        connection.close()


def _sqlite_table_references_legacy(engine: Engine, table_name: str) -> bool:
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        rows = list(cursor.execute(f"PRAGMA foreign_key_list({table_name})"))
        return any(
            str(row[2]).endswith("_legacy") or str(row[2]).endswith("_rebuild_old")
            for row in rows
            if len(row) >= 3
        )
    finally:
        connection.close()


def _drop_sqlite_indexes(cursor, table_name: str) -> None:
    rows = list(cursor.execute(f"PRAGMA index_list({table_name})"))
    for row in rows:
        index_name = str(row[1]) if len(row) >= 2 else ""
        if not index_name or index_name.startswith("sqlite_autoindex"):
            continue
        cursor.execute(f"DROP INDEX IF EXISTS {index_name}")


def _rebuild_sqlite_table(engine: Engine, table_name: str) -> None:
    if engine.dialect.name != "sqlite":
        return

    table = Base.metadata.tables.get(table_name)
    if table is None:
        return

    existing_columns = _sqlite_table_columns(engine, table_name)
    if not existing_columns:
        return

    temp_name = f"{table_name}_rebuild_old"
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute(f"ALTER TABLE {table_name} RENAME TO {temp_name}")
        _drop_sqlite_indexes(cursor, temp_name)
        cursor.execute(str(CreateTable(table).compile(dialect=engine.dialect)))

        shared_columns = [column.name for column in table.columns if column.name in existing_columns]
        if shared_columns:
            column_sql = ", ".join(shared_columns)
            cursor.execute(
                f"INSERT INTO {table_name} ({column_sql}) SELECT {column_sql} FROM {temp_name}"
            )

        for index in sorted(table.indexes, key=lambda item: item.name or ""):
            cursor.execute(str(CreateIndex(index).compile(dialect=engine.dialect)))

        cursor.execute(f"DROP TABLE {temp_name}")
        connection.commit()
        cursor.execute("PRAGMA foreign_keys=ON")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _drop_leftover_legacy_tables(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    legacy_tables = [
        table_name
        for table_name in inspector.get_table_names()
        if table_name.endswith("_legacy") or table_name.endswith("_rebuild_old")
    ]
    if not legacy_tables:
        return

    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        for table_name in legacy_tables:
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        connection.commit()
        cursor.execute("PRAGMA foreign_keys=ON")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _ensure_additive_columns(engine: Engine, table_names: set[str]) -> None:
    inspector = inspect(engine)

    if "engine_versions" in table_names:
        columns = {column["name"] for column in inspector.get_columns("engine_versions")}
        if "restrict_to_rating_lists" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE engine_versions ADD COLUMN restrict_to_rating_lists BOOLEAN DEFAULT 0"))
                connection.execute(text("UPDATE engine_versions SET restrict_to_rating_lists = 0 WHERE restrict_to_rating_lists IS NULL"))

    if "clients" in table_names:
        columns = {column["name"] for column in inspector.get_columns("clients")}
        with engine.begin() as connection:
            if "system_name" not in columns:
                connection.execute(text("ALTER TABLE clients ADD COLUMN system_name VARCHAR(50) DEFAULT 'linux'"))
                connection.execute(text("UPDATE clients SET system_name = 'linux' WHERE system_name IS NULL OR system_name = ''"))
            if "machine_fingerprint" not in columns:
                connection.execute(text("ALTER TABLE clients ADD COLUMN machine_fingerprint VARCHAR(120)"))
                connection.execute(text("UPDATE clients SET machine_fingerprint = machine_key WHERE machine_fingerprint IS NULL OR machine_fingerprint = ''"))
            if "cpu_name" not in columns:
                connection.execute(text("ALTER TABLE clients ADD COLUMN cpu_name VARCHAR(200)"))
            if "ram_total_mb" not in columns:
                connection.execute(text("ALTER TABLE clients ADD COLUMN ram_total_mb INTEGER DEFAULT 0"))
                connection.execute(text("UPDATE clients SET ram_total_mb = 0 WHERE ram_total_mb IS NULL"))
            if "ram_speed_mt_s" not in columns:
                connection.execute(text("ALTER TABLE clients ADD COLUMN ram_speed_mt_s INTEGER"))
            if "syzygy_max_pieces" not in columns:
                connection.execute(text("ALTER TABLE clients ADD COLUMN syzygy_max_pieces INTEGER DEFAULT 0"))
                connection.execute(text("UPDATE clients SET syzygy_max_pieces = 0 WHERE syzygy_max_pieces IS NULL"))

    if "rating_lists" in table_names:
        columns = {column["name"] for column in inspector.get_columns("rating_lists")}
        with engine.begin() as connection:
            if "syzygy_probe_limit" not in columns:
                connection.execute(text("ALTER TABLE rating_lists ADD COLUMN syzygy_probe_limit INTEGER DEFAULT 0"))
                connection.execute(text("UPDATE rating_lists SET syzygy_probe_limit = 0 WHERE syzygy_probe_limit IS NULL"))

    if "match_jobs" in table_names:
        columns = {column["name"] for column in inspector.get_columns("match_jobs")}
        alter_statements = [
            ("client_user_id", "ALTER TABLE match_jobs ADD COLUMN client_user_id INTEGER"),
            ("client_user_display_name", "ALTER TABLE match_jobs ADD COLUMN client_user_display_name VARCHAR(120)"),
            ("client_session_key", "ALTER TABLE match_jobs ADD COLUMN client_session_key VARCHAR(120)"),
            ("client_machine_fingerprint", "ALTER TABLE match_jobs ADD COLUMN client_machine_fingerprint VARCHAR(120)"),
            ("client_machine_name", "ALTER TABLE match_jobs ADD COLUMN client_machine_name VARCHAR(120)"),
            ("client_system_name", "ALTER TABLE match_jobs ADD COLUMN client_system_name VARCHAR(50)"),
            ("client_cpu_name", "ALTER TABLE match_jobs ADD COLUMN client_cpu_name VARCHAR(200)"),
            ("client_ram_total_mb", "ALTER TABLE match_jobs ADD COLUMN client_ram_total_mb INTEGER"),
            ("client_ram_speed_mt_s", "ALTER TABLE match_jobs ADD COLUMN client_ram_speed_mt_s INTEGER"),
            ("client_cpu_flags", "ALTER TABLE match_jobs ADD COLUMN client_cpu_flags TEXT"),
        ]
        with engine.begin() as connection:
            for column_name, statement in alter_statements:
                if column_name not in columns:
                    connection.execute(text(statement))
            if "client_machine_key" in columns:
                connection.execute(text("UPDATE match_jobs SET client_machine_fingerprint = client_machine_key WHERE (client_machine_fingerprint IS NULL OR client_machine_fingerprint = '') AND client_machine_key IS NOT NULL AND client_machine_key != ''"))

    if "leaderboard_entries" in table_names:
        columns = {column["name"] for column in inspector.get_columns("leaderboard_entries")}
        alter_statements = [
            ("rating_stderr", "ALTER TABLE leaderboard_entries ADD COLUMN rating_stderr FLOAT"),
            ("rating_lower", "ALTER TABLE leaderboard_entries ADD COLUMN rating_lower FLOAT"),
            ("rating_upper", "ALTER TABLE leaderboard_entries ADD COLUMN rating_upper FLOAT"),
        ]
        with engine.begin() as connection:
            for column_name, statement in alter_statements:
                if column_name not in columns:
                    connection.execute(text(statement))

    if "engine_artifacts" in table_names:
        columns = {column["name"] for column in inspector.get_columns("engine_artifacts")}
        with engine.begin() as connection:
            if "priority" not in columns:
                connection.execute(text("ALTER TABLE engine_artifacts ADD COLUMN priority INTEGER DEFAULT 0"))
                connection.execute(text("UPDATE engine_artifacts SET priority = 0 WHERE priority IS NULL"))
            if "requires_popcnt" not in columns:
                connection.execute(text("ALTER TABLE engine_artifacts ADD COLUMN requires_popcnt BOOLEAN DEFAULT 0"))
                connection.execute(text("UPDATE engine_artifacts SET requires_popcnt = 0 WHERE requires_popcnt IS NULL"))
            if "requires_bmi2" not in columns:
                connection.execute(text("ALTER TABLE engine_artifacts ADD COLUMN requires_bmi2 BOOLEAN DEFAULT 0"))
                if "requires_pext" in columns:
                    connection.execute(text("UPDATE engine_artifacts SET requires_bmi2 = requires_pext WHERE requires_bmi2 IS NULL OR requires_bmi2 = 0"))
                connection.execute(text("UPDATE engine_artifacts SET requires_bmi2 = 0 WHERE requires_bmi2 IS NULL"))
            if "requires_vnni" not in columns:
                connection.execute(text("ALTER TABLE engine_artifacts ADD COLUMN requires_vnni BOOLEAN DEFAULT 0"))
                connection.execute(text("UPDATE engine_artifacts SET requires_vnni = 0 WHERE requires_vnni IS NULL"))


def ensure_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    _ensure_additive_columns(engine, table_names)

    if engine.dialect.name != "sqlite":
        return

    expected_columns = {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.sorted_tables
    }

    for table in Base.metadata.sorted_tables:
        if table.name not in table_names:
            continue
        actual_columns = _sqlite_table_columns(engine, table.name)
        has_extra_columns = bool(actual_columns - expected_columns[table.name])
        has_missing_columns = bool(expected_columns[table.name] - actual_columns)
        if has_extra_columns or has_missing_columns or _sqlite_table_references_legacy(engine, table.name):
            _rebuild_sqlite_table(engine, table.name)

    _drop_leftover_legacy_tables(engine)
