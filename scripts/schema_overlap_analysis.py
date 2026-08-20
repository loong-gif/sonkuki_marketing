#!/usr/bin/env python3
# DEPRECATED: References deleted ingest tables (removed 2026-08):
# homedepot_products, competitor_products, competitor_sales, raw_listing_snapshots.
# Do not run — kept for historical reference.
"""Read-only redundancy overlap analysis for sonkuki NocoDB base."""
import json
import socket
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

API = "http://72.52.161.65:8080"
ROOT = Path(__file__).resolve().parents[1]
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


def records(table_id, fields, limit=None):
    rows, offset = [], 0
    while True:
        p = {"limit": 1000, "offset": offset, "fields": ",".join(fields)}
        q = "&".join(f"{k}={v}" for k, v in p.items())
        batch = request("GET", f"/api/v2/tables/{table_id}/records?{q}").get("list", [])
        rows.extend(batch)
        if len(batch) < 1000 or (limit and len(rows) >= limit):
            return rows[:limit] if limit else rows
        offset += len(batch)


def kset(rows, fields):
    out = set()
    for r in rows:
        key = "|".join(str(r.get(f, "")).strip() for f in fields)
        if key.replace("|", ""):
            out.add(key)
    return out


T = {
    "gsc_raw": "mfbg6s0mv9l74ky",
    "gsc_research": "m2go76sjanzvx7s",
    "gsc_month": "m0e006r2m3d1wg5",
    "gsc_improved": "m1eh0kd0ryxeptu",
    "gsc_newly": "mj3l8mejz31n8ry",
    "sonkuki_reviews": "mhejqhev6vgfkhz",
    "competitor_reviews": "m7k6bslqxmbw10a",
    "hdv1_reviews": "mnz1y5x5kydob4f",
    "hdv1_links": "m040fohool0kx56",
    "hdv1_products": "m2w1cuciam30ltz",
    "hdv1_variants": "m1br71dforlpotk",
    "hdv1_listings": "m7xynlp62mphmlv",
    "hdv1_listing_snapshots": "mq2abnm4fqtz1f5",
    "hdv1_raw_snapshots": "mzi7pcyvcg0865m",
    "hdv1_brands": "m7ue920zwzocr6t",
    "page_product": "ma3331finostkis",
    "hd_product": "mnttfzrhu6gp6s0",
    "competitor_product": "m0vk08vypm4jrl7",
    "comp_sale": "munzznlmfzd9d2t",
}


def main():
    # 1. gsc_keyword_research vs gsc_data_raw: same row count, same data?
    raw = records(T["gsc_raw"], ["date", "clicks", "impressions"])
    research = records(T["gsc_research"], ["date", "clicks", "impressions"])
    print(f"GSC: gsc_data_raw={len(raw)} rows, gsc_keyword_research={len(research)} rows")
    raw_k = kset(raw[:3000], ["date", "clicks", "impressions"])
    res_k = kset(research[:3000], ["date", "clicks", "impressions"])
    print(f"  first-3000 key overlap: {len(raw_k & res_k)} / {len(res_k)}")

    # 2. competitor_reviews_raw vs HDV1 competitor reviews: same reviews?
    cr = records(T["competitor_reviews"], ["id1", "itemId", "time", "title"])
    hd = records(T["hdv1_reviews"], ["external_review_id", "review_date_iso_utc", "review_title", "is_own"])
    hd_comp = [r for r in hd if str(r.get("is_own")) != "1"]
    hd_own = [r for r in hd if str(r.get("is_own")) == "1"]
    cr_k = {str(r.get("id1", "")).strip() for r in cr if r.get("id1")}
    hd_k = {str(r.get("external_review_id", "")).strip() for r in hd_comp if r.get("external_review_id")}
    print(f"\nREVIEWS: competitor_reviews_raw={len(cr)} distinct id1={len(cr_k)}; "
          f"HDV1 competitor={len(hd_comp)} distinct ext_id={len(hd_k)}; "
          f"HDV1 own={len(hd_own)}; overlap(ext_id): {len(cr_k & hd_k)}")

    # 3. sonkuki_reviews_raw vs HDV1 own rows (same?)
    sr = records(T["sonkuki_reviews"], ["itemId", "submissionTime", "authorId", "title"])
    sr_k = kset(sr, ["itemId", "submissionTime", "authorId", "title"])
    hd_own_k = kset(hd_own, ["review_date_iso_utc", "review_title"])
    print(f"  sonkuki_reviews_raw={len(sr)}; HDV1 own={len(hd_own)}; "
          f"own-title/date overlap: {len(hd_own_k)} (by construction ~same)")

    # 4. HDV1 product layers
    prods = records(T["hdv1_products"], ["product_key", "brand_key", "product_name"])
    variants = records(T["hdv1_variants"], ["variant_key", "product_key", "mpn"])
    listings = records(T["hdv1_listings"], ["listing_key", "external_listing_id", "variant_key", "listing_title"])
    snaps = records(T["hdv1_listing_snapshots"], ["snapshot_key", "listing_key", "observed_at_iso_utc"])
    raw_snaps = records(T["hdv1_raw_snapshots"], ["raw_key", "source_table_id", "source_record_id"])
    print(f"\nHDV1: products={len(prods)}, variants={len(variants)}, listings={len(listings)}, "
          f"listing_snapshots={len(snaps)}, raw_snapshots={len(raw_snaps)}")
    v_keys = {r["variant_key"] for r in variants if r.get("variant_key")}
    l_keys = {r["variant_key"] for r in listings if r.get("variant_key")}
    print(f"  variants distinct variant_key={len(v_keys)}; listings reference distinct variant_key={len(l_keys)}; "
          f"1:1? {len(v_keys) == len(l_keys) == len(variants)}")
    lk = {r["listing_key"] for r in listings if r.get("listing_key")}
    sk = {r["listing_key"] for r in snaps if r.get("listing_key")}
    print(f"  listings distinct listing_key={len(lk)}; snapshots reference distinct listing_key={len(sk)}; "
          f"snapshots per listing: {len(snaps)}/{len(lk)}")

    # 5. links vs reviews
    links = records(T["hdv1_links"], ["review_key", "listing_key"])
    link_rk = {r["review_key"] for r in links if r.get("review_key")}
    link_lk = {r["listing_key"] for r in links if r.get("listing_key")}
    hd_all_k = {r.get("review_key") for r in hd if r.get("review_key")}
    print(f"\nLINKS: links={len(links)} distinct review_key={len(link_rk)} distinct listing_key={len(link_lk)}; "
          f"HDV1 reviews total={len(hd)}; link review_keys missing from reviews table: {len(link_rk - hd_all_k)}; "
          f"orphan listings (no product?): listings={len(lk)}, linked listings={len(link_lk)}")

    # 6. page_product vs homedepot_product vs competitor_product
    pp = records(T["page_product"], ["title", "mpn", "url"])
    hp = records(T["hd_product"], ["name", "mpn", "url"])
    cp = records(T["competitor_product"], ["name", "itemId", "url"])
    pp_k = {str(r.get("url", "")).rstrip("/") for r in pp if r.get("url")}
    hp_k = {str(r.get("url", "")).rstrip("/") for r in hp if r.get("url")}
    cp_k = {str(r.get("url", "")).rstrip("/") for r in cp if r.get("url")}
    print(f"\nPRODUCTS: page_product={len(pp)}, homedepot_product={len(hp)}, competitor_product={len(cp)}")
    print(f"  page_product ∩ homedepot_product (url): {len(pp_k & hp_k)}; "
          f"page_product ∩ competitor_product: {len(pp_k & cp_k)}; "
          f"homedepot_product ∩ competitor_product: {len(hp_k & cp_k)}")

    # 7. sale table
    sale = records(T["comp_sale"], ["商品名称", "品牌", "估算销量"])
    print(f"\nSALE: competitor_product_sale={len(sale)} rows")

    # 8. brands
    brands = records(T["hdv1_brands"], ["brand_key", "brand_name"])
    print(f"BRANDS: {len(brands)} rows")


if __name__ == "__main__":
    main()
