#!/usr/bin/env python3
"""Read-only schema review dump for sonkuki NocoDB base."""
import json
import socket
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

API = "http://72.52.161.65:8080"
BASE_ID = "p447va1t8jqqjty"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "schema_review.json"
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))


def request(method, path, retries=8, timeout=60):
    for attempt in range(retries):
        try:
            r = OPENER.open(Request(API + path, headers={"xc-token": TOKEN, "accept": "application/json"}, method=method), timeout=timeout)
            raw = r.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (HTTPError, URLError, TimeoutError, ConnectionError, ConnectionResetError, socket.timeout, OSError) as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"failed {path}: {exc}") from exc
            time.sleep(min(20, 2 ** attempt))


def records(table_id, fields):
    rows, offset = [], 0
    while True:
        p = {"limit": 1000, "offset": offset, "fields": ",".join(fields)}
        q = "&".join(f"{k}={v}" for k, v in p.items())
        batch = request("GET", f"/api/v2/tables/{table_id}/records?{q}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def main():
    tables = request("GET", f"/api/v1/db/meta/projects/{BASE_ID}/tables")["list"]
    report = {"tables": []}
    for t in sorted(tables, key=lambda x: x["title"]):
        m = request("GET", f"/api/v2/meta/tables/{t['id']}")
        cols = [{"title": c["title"], "uidt": c["uidt"],
                 "not_null": c.get("not_null"), "unique": c.get("unique"),
                 "related": c.get("colOptions", {}).get("fk_related_model_id") if c.get("uidt") in ("LinkToAnotherRecord", "Links") else None}
                for c in m.get("columns", [])]
        report["tables"].append({"title": t["title"], "id": t["id"], "cols": cols})
        print(f"{t['title']}: {len(cols)} cols", flush=True)
        time.sleep(0.3)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved {OUT}", flush=True)


if __name__ == "__main__":
    main()
