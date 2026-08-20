#!/usr/bin/env python3
"""Read-only orphan/linkage audit for Sonkuki NocoDB (14 live tables).

Audits HDV1 analytic chain, sonkuki_products, and GSC tables only.
Does not query deleted ingest tables (homedepot_products, competitor_products,
competitor_sales, raw_listing_snapshots, ingestion_runs, source_registry).
"""
import json
import socket
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener

API = "http://72.52.161.65:8080"
ROOT = Path(__file__).resolve().parents[1]
TOKEN = next(line.split(":", 1)[1].strip() for line in (ROOT / "credentials.txt").read_text(encoding="utf-8").splitlines() if line.startswith("NocoDB PAT:"))
OPENER = build_opener(ProxyHandler({}))

TABLES = {
    "review_listing_links": "m040fohool0kx56",
    "reviews": "mnz1y5x5kydob4f",
    "product_listings": "m7xynlp62mphmlv",
    "product_variants": "m1br71dforlpotk",
    "products": "m2w1cuciam30ltz",
    "brands": "m7ue920zwzocr6t",
    "listing_snapshots": "mq2abnm4fqtz1f5",
    "sonkuki_products": "ma3331finostkis",
    "gsc_raw": "mfbg6s0mv9l74ky",
    "gsc_page_all_time": "m0fl1tcxyopz1s3",
    "gsc_keyword_all_time": "muav8zitnoqlauu",
}


def request(method, path, retries=8, timeout=90):
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
        p = urlencode({"limit": 1000, "offset": offset, "fields": ",".join(fields)})
        batch = request("GET", f"/api/v2/tables/{table_id}/records?{p}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def main():
    links = records(TABLES["review_listing_links"], ["review_key", "listing_key"])
    reviews = records(TABLES["reviews"], ["review_key", "is_own"])
    listings = records(TABLES["product_listings"], ["listing_key", "variant_key", "external_listing_id"])
    variants = records(TABLES["product_variants"], ["variant_key", "product_key", "mpn"])
    products = records(TABLES["products"], ["product_key", "brand_key", "product_name"])
    brands = records(TABLES["brands"], ["brand_key", "brand_name"])
    snaps = records(TABLES["listing_snapshots"], ["snapshot_key", "listing_key"])

    rk = {r["review_key"] for r in reviews if r.get("review_key")}
    lk = {r["listing_key"] for r in listings if r.get("listing_key")}
    vk = {r["variant_key"] for r in variants if r.get("variant_key")}
    pk = {r["product_key"] for r in products if r.get("product_key")}
    bk = {r["brand_key"] for r in brands if r.get("brand_key")}
    link_rk = {r["review_key"] for r in links if r.get("review_key")}
    link_lk = {r["listing_key"] for r in links if r.get("listing_key")}

    print("== HDV1 分析链 ==")
    print(f"reviews={len(reviews)} | review_listing_links={len(links)}")
    print(f"  link review_keys missing from reviews: {len(link_rk - rk)}")
    print(f"  link listing_keys missing from product_listings: {len(link_lk - lk)}")
    own_keys = {r["review_key"] for r in reviews if str(r.get("is_own")) == "1"}
    comp_keys = rk - own_keys
    print(f"  own reviews without link rows: {len(own_keys - link_rk)} / {len(own_keys)}")
    print(f"  competitor reviews without link rows: {len(comp_keys - link_rk)} / {len(comp_keys)}")
    lst_v = {r["listing_key"] for r in listings if r.get("variant_key") and r["variant_key"] in vk}
    print(f"  listings with valid variant_key: {len(lst_v)} / {len(listings)}")
    v_p = {r["variant_key"] for r in variants if r.get("product_key") and r["product_key"] in pk}
    print(f"  variants with valid product_key: {len(v_p)} / {len(variants)}")
    p_b = {r["product_key"] for r in products if r.get("brand_key") and r["brand_key"] in bk}
    print(f"  products with valid brand_key: {len(p_b)} / {len(products)}")
    snap_l = {r["listing_key"] for r in snaps if r.get("listing_key") and r["listing_key"] in lk}
    print(f"  listing_snapshots referencing valid listings: {len(snap_l)} / {len(snaps)}")

    print("\n== sonkuki_products ==")
    spp = records(TABLES["sonkuki_products"], ["mpn", "product_key", "url"])
    sp_keys = {r["product_key"] for r in spp if r.get("product_key")}
    hd_keys = pk
    print(f"  rows={len(spp)} | with product_key={len(sp_keys)}")
    print(f"  product_key overlap with HDV1 products: {len(sp_keys & hd_keys)} / {len(sp_keys)}")

    print("\n== GSC 域 ==")
    gsc = records(TABLES["gsc_raw"], ["date", "page", "query"])
    gsc_nopage = sum(1 for r in gsc if not r.get("page"))
    gsc_noquery = sum(1 for r in gsc if not r.get("query"))
    print(f"  gsc_raw: {len(gsc)} | rows without page link: {gsc_nopage} | without query link: {gsc_noquery}")
    pages = records(TABLES["gsc_page_all_time"], ["Id", "page_url"])
    queries = records(TABLES["gsc_keyword_all_time"], ["Id", "分组键"])
    page_ids = {r["Id"] for r in pages}
    query_ids = {r["Id"] for r in queries}
    gsc_page_ids = {r["page"].get("Id") for r in gsc if isinstance(r.get("page"), dict)}
    gsc_query_ids = {r["query"].get("Id") for r in gsc if isinstance(r.get("query"), dict)}
    print(f"  gsc page links valid: {len(gsc_page_ids & page_ids)} | query links valid: {len(gsc_query_ids & query_ids)}")
    print(f"  page dim unreferenced by gsc: {len(page_ids - gsc_page_ids)} | query dim unreferenced: {len(query_ids - gsc_query_ids)}")


if __name__ == "__main__":
    main()
