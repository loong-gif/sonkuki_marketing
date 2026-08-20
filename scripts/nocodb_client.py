#!/usr/bin/env python3
"""Shared NocoDB v2 client for sonkuki maintenance scripts."""

from __future__ import annotations

import json
import os
import socket
import time
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API = "http://72.52.161.65:8080"
BASE_ID = "p447va1t8jqqjty"

TABLES = {
    "brands": "m7ue920zwzocr6t",
    "products": "m2w1cuciam30ltz",
    "variants": "m1br71dforlpotk",
    "listings": "m7xynlp62mphmlv",
    "reviews": "mnz1y5x5kydob4f",
    "links": "m040fohool0kx56",
}


def load_token() -> str:
    env = os.environ.get("NOCODB_PAT") or os.environ.get("NOCODB_TOKEN")
    if env:
        return env.strip()
    cred = ROOT / "credentials.txt"
    if not cred.exists():
        raise RuntimeError(
            "Missing credentials: set NOCODB_PAT or create credentials.txt with 'NocoDB PAT: ...'"
        )
    for line in cred.read_text(encoding="utf-8").splitlines():
        if line.startswith("NocoDB PAT:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("credentials.txt missing 'NocoDB PAT:' line")


def load_api() -> str:
    env = os.environ.get("NOCODB_URL")
    if env:
        return env.rstrip("/")
    cred = ROOT / "credentials.txt"
    if cred.exists():
        for line in cred.read_text(encoding="utf-8").splitlines():
            if line.startswith("NocoDB URL:"):
                return line.split(":", 1)[1].strip().rstrip("/")
    return DEFAULT_API


class NocoClient:
    def __init__(self, api: str | None = None, token: str | None = None) -> None:
        self.api = (api or load_api()).rstrip("/")
        self.token = token or load_token()
        self.opener = build_opener(ProxyHandler({}))
        self.headers = {"xc-token": self.token, "accept": "application/json"}

    def request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        *,
        retries: int = 8,
        timeout: int = 120,
    ) -> Any:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = dict(self.headers)
        if body is not None:
            headers["Content-Type"] = "application/json"
        last: Exception | None = None
        for attempt in range(retries):
            try:
                with self.opener.open(
                    Request(self.api + path, data=body, headers=headers, method=method),
                    timeout=timeout,
                ) as response:
                    raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
            except (
                HTTPError,
                URLError,
                TimeoutError,
                ConnectionError,
                ConnectionResetError,
                RemoteDisconnected,
                socket.timeout,
                OSError,
            ) as exc:
                last = exc
                if attempt + 1 == retries:
                    raise RuntimeError(f"NocoDB {method} {path} failed: {exc}") from exc
                time.sleep(min(20, 2 ** attempt))
        raise RuntimeError(f"NocoDB {method} {path} failed: {last}")

    def records(self, table_id: str, fields: list[str] | str, *, limit: int = 1000) -> list[dict[str, Any]]:
        field_str = fields if isinstance(fields, str) else ",".join(fields)
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            params = urlencode({"limit": limit, "offset": offset, "fields": field_str})
            batch = self.request("GET", f"/api/v2/tables/{table_id}/records?{params}").get("list", [])
            rows.extend(batch)
            if len(batch) < limit:
                return rows
            offset += len(batch)

    def patch_records(self, table_id: str, patches: list[dict[str, Any]], *, batch_size: int = 50) -> int:
        applied = 0
        for start in range(0, len(patches), batch_size):
            self.request("PATCH", f"/api/v2/tables/{table_id}/records", patches[start : start + batch_size])
            applied += len(patches[start : start + batch_size])
        return applied

    def delete_records(self, table_id: str, record_ids: list[int], *, batch_size: int = 20) -> int:
        deleted = 0
        for start in range(0, len(record_ids), batch_size):
            payload = [{"Id": rid} for rid in record_ids[start : start + batch_size]]
            self.request("DELETE", f"/api/v2/tables/{table_id}/records", payload)
            deleted += len(payload)
        return deleted

    def table_meta(self, table_id: str) -> dict[str, Any]:
        return self.request("GET", f"/api/v2/meta/tables/{table_id}")

    def column_by_title(self, table_id: str, title: str) -> dict[str, Any] | None:
        for col in self.table_meta(table_id).get("columns", []):
            if col.get("title") == title:
                return col
        return None

    def health(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/health", retries=2, timeout=15)


def duplicate_record_ids(rows: list[dict[str, Any]], key_field: str) -> tuple[dict[str, int], list[int]]:
    """Return kept Id per key and duplicate Ids (keep lowest Id)."""
    kept: dict[str, int] = {}
    duplicates: list[int] = []
    for row in sorted(rows, key=lambda item: int(item["Id"])):
        key = str(row.get(key_field) or "").strip()
        if not key:
            continue
        rid = int(row["Id"])
        if key in kept:
            duplicates.append(rid)
        else:
            kept[key] = rid
    return kept, duplicates


def backup_jsonl(rows: list[dict[str, Any]], stem: str) -> Path:
    from datetime import datetime

    out_dir = ROOT / "outputs"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path
