#!/usr/bin/env python3
# DEPRECATED: Targets deleted NocoDB table competitor_products (m0vk08vypm4jrl7).
# Table removed 2026-08. Do not run — kept for historical reference.
"""Batch crawl Home Depot reviews for competitor_product items via Apify actor.

Usage:
  python3 scripts/crawl_competitor_reviews.py resume
  python3 scripts/crawl_competitor_reviews.py collect

- resume:  recover already-started runs (itemId -> run_id/dataset from Apify),
           then start runs for remaining products in paced chunks (free plan
           maxConcurrentActorRuns=25), saving the full run map to /tmp.
- collect: poll runs, download dataset items, write outputs/competitor_reviews_batch/.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS = ROOT / "credentials.txt"
OUT_DIR = ROOT / "outputs" / "competitor_reviews_batch"
RUN_MAP = Path("/tmp/hd_reviews_run_map.json")
PRODUCTS = Path("/tmp/hd_reviews_products.json")

NOCODB = "http://72.52.161.65:8080"
TABLE = "m0vk08vypm4jrl7"           # competitor_product
APIFY = "https://api.apify.com/v2"
ACTOR = "axesso_data~homedepot-reviews-scraper"
MAX_PAGES = int(os.environ.get("MAX_PAGES", "10"))  # ~10 reviews/page -> review cap
CHUNK = 15                           # start up to this many runs before pacing
PAUSE_WHEN = 20                      # wait while more than this many runs not terminal
MAX_RUNNING = 25


def done_item_ids():
    """ItemIds already crawled (from a previous run map) to skip when starting."""
    path = os.environ.get("DONE_ITEMS_FILE")
    if not path:
        return set()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return {m["itemId"] for m in data.values()}
    except Exception:
        return set()


def cred(label):
    for line in CREDENTIALS.read_text(encoding="utf-8").splitlines():
        if line.startswith(label + ":"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError(f"Missing credential: {label}")


NC_TOKEN = cred("NocoDB PAT")
APIFY_TOKEN = os.environ.get("APIFY_TOKEN") or cred("Apify Token")
OPENER = build_opener(ProxyHandler({}))


def nc_get(path):
    r = OPENER.open(Request(NOCODB + path, headers={"xc-token": NC_TOKEN, "accept": "application/json"}), timeout=60)
    return json.loads(r.read().decode())


def apify_request(method, path, payload=None, retries=4, timeout=60):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    url = f"{APIFY}{path}{'&' if '?' in path else '?'}token={APIFY_TOKEN}"
    for attempt in range(retries):
        try:
            r = OPENER.open(Request(url, data=body, headers=headers, method=method), timeout=timeout)
            return json.loads(r.read().decode())
        except HTTPError as exc:
            if exc.code == 403:
                try:
                    body = exc.read().decode("utf-8", "replace")
                except Exception:
                    body = ""
                if "usage" in body.lower() or "locked" in body.lower() or "limit" in body.lower():
                    raise RuntimeError(f"Apify usage limit reached: {body[:200]}") from exc
                if attempt < retries - 1:
                    time.sleep(30)  # queue full; wait for capacity
                    continue
            raise
        except (URLError, TimeoutError, ConnectionError, ConnectionResetError) as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"Apify request failed: {method} {path}: {exc}") from exc
            time.sleep(2 ** attempt)


def curl_items(dataset_id):
    url = f"{APIFY}/datasets/{dataset_id}/items?token={APIFY_TOKEN}&format=json"
    proc = subprocess.run(["curl", "-s", "--noproxy", "*", "--max-time", "60", url],
                          capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def fetch_products():
    rows, off = [], 0
    while True:
        p = urlencode({"limit": 1000, "offset": off,
                       "fields": "Id,itemId,name,url,reviewCount,brand|slogan"})
        batch = nc_get(f"/api/v2/tables/{TABLE}/records?{p}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            break
        off += len(batch)
    prods = []
    for r in rows:
        try:
            rc = int(float(str(r.get("reviewCount") or 0)))
        except (TypeError, ValueError):
            rc = 0
        if rc > 0 and r.get("itemId"):
            prods.append({"productId": r["Id"], "itemId": str(r["itemId"]),
                          "name": r.get("name") or "", "url": r.get("url") or "",
                          "reviewCount": rc, "brand": r.get("brand|slogan") or ""})
    return prods


def list_actor_runs():
    runs, offset = [], 0
    while True:
        batch = apify_request("GET", f"/acts/{ACTOR}/runs?limit=100&offset={offset}&desc=1")["data"]["items"]
        runs.extend(batch)
        if len(batch) < 100:
            return runs
        offset += len(batch)


def run_input_item(run):
    """Return itemId from a run's INPUT record in its key-value store."""
    kv = run.get("defaultKeyValueStoreId")
    if not kv:
        return None
    try:
        data = apify_request("GET", f"/key-value-stores/{kv}/records/INPUT", retries=2, timeout=15)
    except Exception:
        return None
    try:
        lst = data.get("input") or []
        return lst[0].get("itemId") if isinstance(lst, list) and lst else None
    except AttributeError:
        return None


def cmd_resume():
    prods = fetch_products()
    PRODUCTS.write_text(json.dumps(prods, ensure_ascii=False), encoding="utf-8")
    by_item = {p["itemId"]: p for p in prods}

    # recover existing runs
    runs = list_actor_runs()
    total_runs = len(runs)
    recovered = {}
    for i, run in enumerate(runs, 1):
        item = run_input_item(run)
        if item and item in by_item:
            recovered[item] = {"run": run["id"], "dataset": run.get("defaultDatasetId", ""),
                               "status": run["status"]}
        if i % 20 == 0:
            print(f"recover {i}/{total_runs} scanned, {len(recovered)} matched", flush=True)
    print(f"recovered existing runs: {len(recovered)}", flush=True)

    run_map = {}
    for item, info in recovered.items():
        run_map[info["run"]] = {"itemId": item, "productId": by_item[item]["productId"],
                                "name": by_item[item]["name"], "url": by_item[item]["url"],
                                "brand": by_item[item]["brand"], "status": info["status"],
                                "dataset": info["dataset"]}
    RUN_MAP.write_text(json.dumps(run_map, ensure_ascii=False), encoding="utf-8")
    print(f"recovered run map saved: {len(run_map)} runs", flush=True)

    if os.environ.get("SKIP_START") == "1":
        print("SKIP_START=1 -> not starting new runs", flush=True)
        return

    remaining = [p for p in prods if p["itemId"] not in recovered and p["itemId"] not in done_item_ids()]
    print(f"remaining to start: {len(remaining)}", flush=True)

    # status cache for pacing
    status_cache = {rid: info["status"] for rid, info in run_map.items()}

    def not_terminal():
        return sum(1 for s in status_cache.values() if s not in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"))

    idx = 0
    while idx < len(remaining):
        if not_terminal() >= PAUSE_WHEN:
            time.sleep(20)
            # refresh statuses of in-flight runs
            for rid in [r for r, s in status_cache.items() if s not in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT")]:
                try:
                    status_cache[rid] = apify_request("GET", f"/actor-runs/{rid}")["data"]["status"]
                except Exception:
                    pass
            continue
        p = remaining[idx]
        try:
            data = apify_request("POST", f"/actors/{ACTOR}/runs",
                                 {"input": [{"itemId": p["itemId"], "startPage": 1, "endPage": MAX_PAGES}]})["data"]
            rid = data["id"]
            run_map[rid] = {"itemId": p["itemId"], "productId": p["productId"],
                            "name": p["name"], "url": p["url"], "brand": p["brand"],
                            "status": data["status"], "dataset": data.get("defaultDatasetId", "")}
            status_cache[rid] = data["status"]
            idx += 1
            if idx % 25 == 0 or idx == len(remaining):
                print(f"started {idx}/{len(remaining)} | in-flight: {not_terminal()}", flush=True)
            time.sleep(0.4)
        except RuntimeError as exc:
            print(f"FAIL start {p['itemId']}: {exc}", flush=True)
            time.sleep(20)

    RUN_MAP.write_text(json.dumps(run_map, ensure_ascii=False), encoding="utf-8")
    total = sum(min(by_item[p["itemId"]]["reviewCount"], MAX_PAGES * 10) for p in prods)
    print(f"run map saved: {len(run_map)} runs -> {RUN_MAP} | projected items ~{total} (~${total * 0.05:.0f})",
          flush=True)


def cmd_collect():
    run_map = json.loads(RUN_MAP.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_f = open(OUT_DIR / "reviews_raw.jsonl", "w", encoding="utf-8")
    items_by_product = {}
    failed = []
    remaining = set(run_map)
    deadline = time.time() + 90 * 60  # 90 min max

    while remaining and time.time() < deadline:
        done_this_pass = []
        for run_id in list(remaining):
            try:
                data = apify_request("GET", f"/actor-runs/{run_id}")["data"]
                status = data["status"]
            except Exception as exc:
                print(f"poll error {run_id}: {exc}", flush=True)
                continue
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                done_this_pass.append(run_id)
                meta = run_map[run_id]
                if status == "SUCCEEDED":
                    try:
                        items = curl_items(data["defaultDatasetId"])
                    except Exception as exc:
                        print(f"download error {run_id}: {exc}", flush=True)
                        items = []
                    keep = [it for it in items if it.get("id")][:MAX_PAGES * 10]
                    for it in keep:
                        it["productId"] = meta["productId"]
                        it["itemId"] = meta["itemId"]
                        it["productName"] = meta["name"]
                        it["productUrl"] = meta["url"]
                        it["brand"] = meta.get("brand", "")
                        raw_f.write(json.dumps(it, ensure_ascii=False) + "\n")
                    items_by_product[meta["itemId"]] = len(keep)
                else:
                    failed.append({"run": run_id, "itemId": meta["itemId"],
                                   "productId": meta["productId"], "status": status})
        for run_id in done_this_pass:
            remaining.discard(run_id)
        if remaining:
            print(f"remaining: {len(remaining)} | done: {len(run_map) - len(remaining)} | "
                  f"reviews so far: {sum(items_by_product.values())}", flush=True)
            time.sleep(20)

    raw_f.close()
    total_items = sum(items_by_product.values())
    print(f"\ncollection finished: {len(items_by_product)} products with reviews, "
          f"{total_items} review items", flush=True)
    (OUT_DIR / "failures.json").write_text(json.dumps(failed, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / "items_per_product.json").write_text(
        json.dumps(items_by_product, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"failures: {len(failed)} -> {OUT_DIR / 'failures.json'}", flush=True)
    print(f"raw -> {OUT_DIR / 'reviews_raw.jsonl'}", flush=True)

    cols = ["productId", "itemId", "productName", "id", "title", "rating",
            "submissionTime", "userNickname", "isVerifiedPurchaser", "reviewText"]
    with open(OUT_DIR / "reviews_raw.jsonl", encoding="utf-8") as f:
        with open(OUT_DIR / "reviews.tsv", "w", encoding="utf-8") as tsv:
            tsv.write("\t".join(cols) + "\n")
            for line in f:
                it = json.loads(line)
                tsv.write("\t".join(str(it.get(c, "")) for c in cols).replace("\n", " ") + "\n")
    print(f"tsv -> {OUT_DIR / 'reviews.tsv'}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("resume", "collect"):
        raise SystemExit("usage: crawl_competitor_reviews.py resume|collect")
    (cmd_resume if sys.argv[1] == "resume" else cmd_collect)()
