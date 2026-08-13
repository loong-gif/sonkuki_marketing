#!/usr/bin/env python3
"""Fetch Sonkuki rows from the four PostgreSQL keyword-report tables."""

import json
from datetime import date, datetime
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("/private/tmp/sonkuki_keyword_exports.json")
TARGET_DB = "ga_sc_data_lw"
TARGETS = {
    "gsc_keyword_research": "site_url",
    "gsc_keyword_month": "domain",
    "gsc_keyword_improved": "domain",
    "gsc_keyword_newly_ranked": "domain",
}


def credentials():
    values = {}
    for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def main():
    c = credentials()
    connection = psycopg2.connect(host=c["Host"], port=int(c["Port"]), user=c["user"], password=c["pass"], dbname=TARGET_DB, connect_timeout=15)
    output = {"database": TARGET_DB, "scope": "sonkuki.com", "tables": {}}
    try:
        with connection.cursor() as cursor:
            for table_name, scope_column in TARGETS.items():
                cursor.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position", (table_name,))
                columns = [(row[0], row[1]) for row in cursor.fetchall()]
                if not columns:
                    raise RuntimeError(f"Missing table: {table_name}")
                cursor.execute(f'SELECT "{scope_column}", COUNT(*) FROM public."{table_name}" WHERE "{scope_column}" ILIKE %s GROUP BY "{scope_column}" ORDER BY "{scope_column}"', ("%sonkuki%",))
                scope_values = [{"value": row[0], "rows": row[1]} for row in cursor.fetchall()]
                exact_values = [item["value"] for item in scope_values]
                if exact_values:
                    cursor.execute(f'SELECT * FROM public."{table_name}" WHERE "{scope_column}" = ANY(%s)', (exact_values,))
                    records = [{key: json_value(value) for key, value in row.items()} for row in cursor.fetchall()]
                else:
                    records = []
                output["tables"][table_name] = {
                    "scope_column": scope_column,
                    "columns": columns,
                    "scope_values": scope_values,
                    "rows": records,
                }
    finally:
        connection.close()
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "tables": {name: {"rows": len(payload["rows"]), "scope_values": payload["scope_values"]} for name, payload in output["tables"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
