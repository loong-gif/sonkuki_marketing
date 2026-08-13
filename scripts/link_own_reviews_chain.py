#!/usr/bin/env python3
"""Link own reviews into the HDV1 chain + sync orphan data (audit items 1-3).

Phase A: add 8 missing homedepot_product rows (from archived own reviews)
Phase B: own listings chain:
  - HDV1_Brands += BRAND:SONKUKI
  - HDV1_Products += PRODUCT:SONKUKI:* (distinct product_key)
  - HDV1_Product_Variants += VARIANT:SONKUKI:<itemId>
  - HDV1_Channel_Listings += HOME_DEPOT:<itemId>
  - HDV1_Review_Listing_Links += own reviews (review_key -> listing_key)
Phase C: sync 9 HDV1 competitors missing from competitor_product
Phase D: delete junk competitor_product row (no itemId/name)
"""

import json
import re
import socket
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

API = "http://72.52.161.65:8080"
ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "outputs" / "sonkuki_reviews_raw_archived_20260813_095913.jsonl"
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))

T = {
    "reviews": "mnz1y5x5kydob4f",
    "links": "m040fohool0kx56",
    "listings": "m7xynlp62mphmlv",
    "variants": "m1br71dforlpotk",
    "products": "m2w1cuciam30ltz",
    "brands": "m7ue920zwzocr6t",
    "snapshots": "mq2abnm4fqtz1f5",
    "hd_product": "mnttfzrhu6gp6s0",
    "competitor": "m0vk08vypm4jrl7",
}


def request(method, path, payload=None, timeout=90, retries=8):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"xc-token": TOKEN, "accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(retries):
        try:
            r = OPENER.open(Request(API + path, data=body, headers=headers, method=method), timeout=timeout)
            raw = r.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (HTTPError, URLError, TimeoutError, ConnectionError, ConnectionResetError, socket.timeout, OSError) as exc:
            last = exc
            time.sleep(min(20, 2 ** attempt))
    raise RuntimeError(f"request failed {method} {path}: {last}")


def records(table_id, fields):
    rows, offset = [], 0
    while True:
        p = urlencode({"limit": 1000, "offset": offset, "fields": ",".join(fields)})
        batch = request("GET", f"/api/v2/tables/{table_id}/records?{p}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def insert(table_id, rows, batch=20, label=""):
    for start in range(0, len(rows), batch):
        request("POST", f"/api/v2/tables/{table_id}/records", rows[start:start + batch])
    print(f"  inserted {len(rows)} {label}", flush=True)


def item_id(url):
    m = re.search(r"/(\d{6,})/?$", str(url or "").rstrip("/"))
    return m.group(1) if m else None


def main():
    # ---------- Phase A: 8 orphan products ----------
    arch = [json.loads(l) for l in open(ARCHIVE, encoding="utf-8")]
    hp = records(T["hd_product"], ["Id", "mpn", "url", "name", "reviewCount", "product_key"])
    hp_ids = {item_id(r.get("url")) for r in hp if item_id(r.get("url"))}
    by_item = {}
    for r in arch:
        iid = str(r.get("itemId") or "")
        if iid and iid not in by_item:
            by_item[iid] = r
    orphans = sorted(set(by_item) - hp_ids)
    print(f"Phase A: orphan itemIds = {len(orphans)}", flush=True)
    new_hp = []
    for iid in orphans:
        r = by_item[iid]
        mpn = str(r.get("mpn") or "").strip()
        url = str(r.get("productUrl") or "")
        name = str(r.get("productName") or "") or f"Sonkuki product {iid}"
        try:
            rc = int(float(str(r.get("totalResults") or 0)))
        except (TypeError, ValueError):
            rc = None
        pk = f"PRODUCT:SONKUKI:{mpn or iid}"
        new_hp.append({"mpn": mpn, "name": name, "url": url,
                       "reviewCount": rc, "product_key": pk, "item_id_tmp": iid})
    # strip tmp marker and insert
    insert_rows = [{k: v for k, v in r.items() if k != "item_id_tmp"} for r in new_hp]
    if insert_rows:
        insert(T["hd_product"], insert_rows, label="homedepot_product rows (orphans)")
    else:
        print("  no orphan products to add", flush=True)

    # ---------- Phase B: own chain ----------
    print("Phase B: own listings chain", flush=True)
    hp2 = records(T["hd_product"], ["Id", "mpn", "url", "name", "product_key"])
    own = []
    seen_lk = set()
    for r in hp2:
        iid = item_id(r.get("url"))
        if not iid or iid in seen_lk:
            continue
        seen_lk.add(iid)
        own.append({
            "iid": iid,
            "mpn": str(r.get("mpn") or "").strip(),
            "name": str(r.get("name") or "").strip() or f"Sonkuki {iid}",
            "url": str(r.get("url") or "").strip(),
            "product_key": str(r.get("product_key") or f"PRODUCT:SONKUKI:{iid}"),
        })
    print(f"  own listings to create: {len(own)}", flush=True)

    # brand
    brands = records(T["brands"], ["brand_key"])
    if "BRAND:SONKUKI" not in {r["brand_key"] for r in brands}:
        insert(T["brands"], [{"brand_key": "BRAND:SONKUKI", "brand_name": "Sonkuki"}], label="brand rows")

    # products (distinct product_key)
    existing_pk = {r["product_key"] for r in records(T["products"], ["product_key"])}
    new_products = []
    seen_pk = set()
    for o in own:
        if o["product_key"] in existing_pk or o["product_key"] in seen_pk:
            continue
        seen_pk.add(o["product_key"])
        new_products.append({"product_key": o["product_key"], "brand_key": "BRAND:SONKUKI",
                             "product_name": o["name"]})
    if new_products:
        insert(T["products"], new_products, label="product rows")

    # variants + listings (per itemId)
    existing_vk = {r["variant_key"] for r in records(T["variants"], ["variant_key"])}
    existing_lk = {r["listing_key"] for r in records(T["listings"], ["listing_key"])}
    new_variants, new_listings = [], []
    for o in own:
        vk = f"VARIANT:SONKUKI:{o['iid']}"
        lk = f"HOME_DEPOT:{o['iid']}"
        if vk not in existing_vk:
            new_variants.append({"variant_key": vk, "product_key": o["product_key"], "mpn": o["mpn"]})
        if lk not in existing_lk:
            new_listings.append({"listing_key": lk, "external_listing_id": o["iid"],
                                 "variant_key": vk, "listing_title": o["name"],
                                 "listing_url": o["url"]})
    if new_variants:
        insert(T["variants"], new_variants, label="variant rows")
    if new_listings:
        insert(T["listings"], new_listings, label="listing rows")

    # links: own reviews -> listing
    reviews = records(T["reviews"], ["review_key", "is_own", "item_id"])
    own_revs = [r for r in reviews if str(r.get("is_own")) == "1" and r.get("item_id")]
    existing_links = {r["link_key"] for r in records(T["links"], ["link_key"])}
    new_links = []
    for r in own_revs:
        if str(r["item_id"]) not in seen_lk:
            continue
        lk = f"HOME_DEPOT:{r['item_id']}"
        lk_key = f"{r['review_key']}:{lk}"
        if lk_key in existing_links:
            continue
        new_links.append({"link_key": lk_key, "review_key": r["review_key"], "listing_key": lk})
    insert(T["links"], new_links, batch=20, label="review-listing links")

    # ---------- Phase C: 9 competitors ----------
    print("Phase C: sync 9 competitors", flush=True)
    cp = records(T["competitor"], ["Id", "itemId"])
    cp_ids = {str(r.get("itemId")) for r in cp if r.get("itemId")}
    listings_all = records(T["listings"], ["listing_key", "external_listing_id", "variant_key", "listing_title", "listing_url"])
    variants_all = records(T["variants"], ["variant_key", "product_key", "mpn"])
    products_all = records(T["products"], ["product_key", "brand_key", "product_name"])
    snapshots_all = records(T["snapshots"], ["listing_key", "regular_price", "sale_price", "effective_price", "review_count", "avg_rating"])
    brands_all = records(T["brands"], ["brand_key", "brand_name"])

    vk_map = {v["variant_key"]: v for v in variants_all}
    pk_map = {p["product_key"]: p for p in products_all}
    bk_map = {b["brand_key"]: b.get("brand_name") or b["brand_key"].split(":")[-1] for b in brands_all}
    snap_latest = {}
    for s in snapshots_all:
        if s.get("listing_key") and (s["listing_key"] not in snap_latest or True):
            snap_latest.setdefault(s["listing_key"], s)

    new_cp = []
    for l in listings_all:
        iid = l.get("external_listing_id") or (l["listing_key"].split(":")[-1] if l.get("listing_key", "").startswith("HOME_DEPOT:") else "")
        if not iid or iid in cp_ids or iid in [c.get("itemId") for c in new_cp]:
            continue
        # skip own listings
        vk = l.get("variant_key") or ""
        pk = vk_map.get(vk, {}).get("product_key") if vk else None
        prod = pk_map.get(pk, {}) if pk else {}
        brand_key = prod.get("brand_key", "")
        if brand_key == "BRAND:SONKUKI":
            continue
        snap = snap_latest.get(l["listing_key"], {})
        new_cp.append({
            "itemId": iid,
            "name": prod.get("product_name") or l.get("listing_title") or "",
            "brand|slogan": bk_map.get(brand_key) or "Unknown",
            "url": l.get("listing_url") or "",
            "salePrice": snap.get("effective_price") or snap.get("sale_price"),
            "originalPrice": snap.get("regular_price"),
            "rating": snap.get("avg_rating"),
            "reviewCount": snap.get("review_count"),
        })
    print(f"  competitors to add: {len(new_cp)}", flush=True)
    for c in new_cp:
        print(f"    {c['itemId']} {c.get('brand|slogan')} {str(c.get('name'))[:50]}", flush=True)
    if new_cp:
        insert(T["competitor"], new_cp, label="competitor rows")

    # ---------- Phase D: junk row ----------
    junk = [r for r in records(T["competitor"], ["Id", "itemId", "name", "url"]) if not r.get("itemId") and not r.get("name") and not r.get("url")]
    if junk:
        request("DELETE", f"/api/v2/tables/{T['competitor']}/records", [{"Id": r["Id"]} for r in junk])
        print(f"Phase D: deleted junk rows: {len(junk)}", flush=True)
    else:
        print("Phase D: no junk rows", flush=True)

    print("DONE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
