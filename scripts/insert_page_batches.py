#!/usr/bin/env python3
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

TABLE_ID = "mk6mn7cbxl1eu1f"
API = "http://72.52.161.65:8080"
token = next(line.split(":", 1)[1].strip() for line in open("credentials.txt", encoding="utf-8") if line.startswith("NocoDB PAT:"))
opener = build_opener(ProxyHandler({}))
rows = json.load(open("/private/tmp/page_payload.json", encoding="utf-8"))

def send(batch):
    body = json.dumps(batch, ensure_ascii=False).encode("utf-8")
    for attempt in range(5):
        try:
            req = Request(f"{API}/api/v2/tables/{TABLE_ID}/records", data=body, method="POST", headers={"xc-token": token, "Content-Type": "application/json", "accept": "application/json"})
            with opener.open(req, timeout=90) as response:
                response.read()
            return
        except (HTTPError, URLError, TimeoutError, ConnectionError) as exc:
            if attempt == 4:
                raise
            print(f"retry batch after {type(exc).__name__}", flush=True)
            time.sleep(2 ** attempt)

for start in range(0, len(rows), 10):
    send(rows[start:start + 10])
    print(f"inserted {min(start + 10, len(rows))}/{len(rows)}", flush=True)
