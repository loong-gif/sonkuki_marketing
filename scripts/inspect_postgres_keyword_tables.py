#!/usr/bin/env python3
"""Inspect the PostgreSQL keyword-report tables without changing data."""

import json
from pathlib import Path

import psycopg2


ROOT = Path(__file__).resolve().parents[1]


def credentials():
    values = {}
    for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def main():
    c = credentials()
    last = None
    connection = None
    database = None
    for candidate in [c.get("database"), c.get("db"), c.get("user"), "postgres"]:
        if not candidate:
            continue
        try:
            connection = psycopg2.connect(host=c["Host"], port=int(c["Port"]), user=c["user"], password=c["pass"], dbname=candidate, connect_timeout=10)
            database = candidate
            break
        except Exception as exc:
            last = exc
    if connection is None:
        raise RuntimeError(f"PostgreSQL connection failed: {last}")
    with connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_schema()")
            current = cursor.fetchone()
            cursor.execute("SELECT table_schema, table_name, table_type FROM information_schema.tables WHERE (table_name ILIKE %s OR table_name ILIKE %s) ORDER BY table_schema, table_name", ("%gsc%", "%keyword%"))
            tables = cursor.fetchall()
    connection.close()
    with psycopg2.connect(host=c["Host"], port=int(c["Port"]), user=c["user"], password=c["pass"], dbname="postgres", connect_timeout=10) as catalog_connection:
        with catalog_connection.cursor() as cursor:
            cursor.execute("SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY datname")
            databases = [row[0] for row in cursor.fetchall()]
    matches = [{"database": database, "tables": tables}]
    for candidate in databases:
        if candidate == database:
            continue
        try:
            with psycopg2.connect(host=c["Host"], port=int(c["Port"]), user=c["user"], password=c["pass"], dbname=candidate, connect_timeout=10) as candidate_connection:
                with candidate_connection.cursor() as cursor:
                    cursor.execute("SELECT table_schema, table_name, table_type FROM information_schema.tables WHERE table_name ILIKE %s OR table_name ILIKE %s ORDER BY table_schema, table_name", ("%gsc%", "%keyword%"))
                    candidate_tables = cursor.fetchall()
            matches.append({"database": candidate, "tables": candidate_tables})
        except Exception:
            continue
    target_inspection = {}
    target_db = "ga_sc_data_lw"
    with psycopg2.connect(host=c["Host"], port=int(c["Port"]), user=c["user"], password=c["pass"], dbname=target_db, connect_timeout=10) as target_connection:
        with target_connection.cursor() as cursor:
            for table_name in ["gsc_keyword_research", "gsc_keyword_month", "gsc_keyword_improved", "gsc_keyword_newly_ranked"]:
                cursor.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position", (table_name,))
                columns = cursor.fetchall()
                cursor.execute(f'SELECT COUNT(*) FROM public."{table_name}"')
                count = cursor.fetchone()[0]
                cursor.execute(f'SELECT * FROM public."{table_name}" LIMIT 3')
                samples = cursor.fetchall()
                target_inspection[table_name] = {"columns": columns, "count": count, "samples": samples}
    print(json.dumps({"connected_database": database, "current": current, "databases": databases, "matches": matches, "target_database": target_db, "target_inspection": target_inspection}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
