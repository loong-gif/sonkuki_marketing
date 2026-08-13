#!/usr/bin/env python3
"""Inspect and export the four keyword-report tables for local XLSX creation."""

import json
import time
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener


API = "http://72.52.161.65:8080"
BASE_ID = "pvixtxsncbx6vv6"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("/private/tmp/sonkuki_keyword_report_tables.json")
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))
TARGETS = ["gsc_keyword_research", "gsc_keyword_month", "gsc_keyword_improved", "gsc_keyword_newly_ranked"]


def request(method, path):
    last = None
    for attempt in range(6):
        try:
            with OPENER.open(Request(API + path, headers={"xc-token": TOKEN, "accept": "application/json"}), timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ConnectionError, RemoteDisconnected) as exc:
            last = exc
            if attempt + 1 < 6:
                time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"NocoDB request failed: {path}: {last}")


def records(table_id, fields):
    rows = []
    offset = 0
    while True:
        params = {"limit": 1000, "offset": offset, "fields": ",".join(fields)}
        batch = request("GET", f"/api/v2/tables/{table_id}/records?{urlencode(params)}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def main():
    tables = request("GET", f"/api/v1/db/meta/projects/{BASE_ID}/tables").get("list", [])
    if not tables:
        tables = request("GET", f"/api/v2/meta/bases/{BASE_ID}/tables").get("list", [])
    by_title = {table.get("title"): table for table in tables}
    missing = [title for title in TARGETS if title not in by_title]
    if missing:
        projects = request("GET", "/api/v1/db/meta/projects").get("list", [])
        base_tables = {}
        for project in projects:
            project_id = project.get("id")
            if project_id:
                base_tables[project_id] = [table.get("title") for table in request("GET", f"/api/v1/db/meta/projects/{project_id}/tables").get("list", [])]
        raise RuntimeError(json.dumps({"missing_tables": missing, "available_in_base": sorted(by_title), "base_tables": [{"id": p.get("id"), "title": p.get("title"), "tables": base_tables.get(p.get("id"), [])} for p in projects]}, ensure_ascii=False))
    output = {"tables": {}, "target_scope": "sonkuki.com"}
    for title in TARGETS:
        table = by_title[title]
        table_id = table["id"]
        meta = request("GET", f"/api/v2/meta/tables/{table_id}")
        columns = [column for column in meta.get("columns", []) if column.get("title")]
        fields = [column["title"] for column in columns]
        rows = records(table_id, fields)
        output["tables"][title] = {"id": table_id, "fields": fields, "columns": columns, "rows": rows}
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "tables": {title: {"rows": len(payload["rows"]), "fields": payload["fields"]} for title, payload in output["tables"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
