#!/usr/bin/env python3
"""Check that NocoDB exposes the created forward and reverse Link fields."""

import json
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener


API = "http://72.52.161.65:8080"
ROOT = Path(__file__).resolve().parents[1]
SCD = "mfbg6s0mv9l74ky"
PAGE = "m0fl1tcxyopz1s3"
QUERY = "muav8zitnoqlauu"
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))


def get(path: str, timeout: int = 30):
    request = Request(API + path, headers={"xc-token": TOKEN, "accept": "application/json"})
    with OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    scd_meta = get(f"/api/v2/meta/tables/{SCD}")
    page_meta = get(f"/api/v2/meta/tables/{PAGE}")
    query_meta = get(f"/api/v2/meta/tables/{QUERY}")
    scd_links = [{"title": c.get("title"), "uidt": c.get("uidt"), "related": c.get("colOptions", {}).get("fk_related_model_id")} for c in scd_meta.get("columns", []) if c.get("uidt") == "LinkToAnotherRecord"]
    page_reverse = [c.get("title") for c in page_meta.get("columns", []) if c.get("uidt") == "Links"]
    query_reverse = [c.get("title") for c in query_meta.get("columns", []) if c.get("uidt") == "Links"]
    sample = {"status": "metadata_passed", "scd_links": scd_links, "page_reverse": page_reverse, "query_reverse": query_reverse}
    try:
        params = {"limit": 1, "offset": 0, "fields": "Id,page,query"}
        sample["scd_link_sample"] = get(f"/api/v2/tables/{SCD}/records?{urlencode(params)}", timeout=20).get("list", [])
    except (HTTPError, URLError, TimeoutError, ConnectionError, RemoteDisconnected) as exc:
        sample["scd_link_sample_error"] = type(exc).__name__
    try:
        params = {"limit": 1, "offset": 0, "fields": "Id,page_url,SCD_Raws"}
        sample["page_reverse_sample"] = get(f"/api/v2/tables/{PAGE}/records?{urlencode(params)}", timeout=20).get("list", [])
    except (HTTPError, URLError, TimeoutError, ConnectionError, RemoteDisconnected) as exc:
        sample["page_reverse_sample_error"] = type(exc).__name__
    print(json.dumps(sample, ensure_ascii=False))


if __name__ == "__main__":
    main()
