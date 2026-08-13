#!/usr/bin/env python3
"""Read-only orphan/linkage audit across sonkuki NocoDB base (20 tables)."""
import json
import re
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


def item_id(url):
    m = re.search(r"/(\d{6,})/?$", str(url or "").rstrip("/"))
    return m.group(1) if m else None


def main():
    # ---- HDV1 domain ----
    links = records("m040fohool0kx56", ["review_key", "listing_key"])
    reviews = records("mnz1y5x5kydob4f", ["review_key", "is_own", "item_id"])
    listings = records("m7xynlp62mphmlv", ["Id", "listing_key", "variant_key", "external_listing_id"])
    variants = records("m1br71dforlpotk", ["variant_key", "product_key", "mpn"])
    products = records("m2w1cuciam30ltz", ["product_key", "brand_key", "product_name"])
    brands = records("m7ue920zwzocr6t", ["brand_key", "brand_name"])
    snaps = records("mq2abnm4fqtz1f5", ["snapshot_key", "listing_key"])
    raw_snaps = records("mzi7pcyvcg0865m", ["raw_key", "source_table_id", "source_record_id", "source_url"])

    rk = {r["review_key"] for r in reviews if r.get("review_key")}
    lk = {r["listing_key"] for r in listings if r.get("listing_key")}
    vk = {r["variant_key"] for r in variants if r.get("variant_key")}
    pk = {r["product_key"] for r in products if r.get("product_key")}
    bk = {r["brand_key"] for r in brands if r.get("brand_key")}
    link_rk = {r["review_key"] for r in links if r.get("review_key")}
    link_lk = {r["listing_key"] for r in links if r.get("listing_key")}

    print("== HDV1 域 ==")
    print(f"links={len(links)} | review_keys missing from HDV1_CR: {len(link_rk - rk)}")
    print(f"listing_keys missing from Channel_Listings: {len(link_lk - lk)}")
    own_keys = {r["review_key"] for r in reviews if str(r.get("is_own")) == "1"}
    comp_keys = rk - own_keys
    print(f"own reviews without link rows: {len(own_keys - link_rk)} / {len(own_keys)} (全部无链接)")
    print(f"competitor reviews without link rows: {len(comp_keys - link_rk)} / {len(comp_keys)}")
    lst_v = {r["listing_key"] for r in listings if r.get("variant_key") and r["variant_key"] in vk}
    print(f"listings with valid variant_key: {len(lst_v)} / {len(listings)}")
    v_p = {r["variant_key"] for r in variants if r.get("product_key") and r["product_key"] in pk}
    print(f"variants with valid product_key: {len(v_p)} / {len(variants)}")
    p_b = {r["product_key"] for r in products if r.get("brand_key") and r["brand_key"] in bk}
    print(f"products with valid brand_key: {len(p_b)} / {len(products)}")
    snap_l = {r["listing_key"] for r in snaps if r.get("listing_key") and r["listing_key"] in lk}
    print(f"snapshots referencing valid listings: {len(snap_l)} / {len(snaps)}")
    # raw snapshots: source_record_id vs listing Ids
    listing_ids = {r["Id"] for r in listings}
    raw_ref = {int(r["source_record_id"]) for r in raw_snaps if r.get("source_record_id")}
    print(f"raw snapshots: {len(raw_snaps)}, source_record_id in listing Ids: {len(raw_ref & listing_ids)} / {len(raw_ref)}")

    # ---- own domain ----
    print("\n== 自家域 ==")
    hp = records("mnttfzrhu6gp6s0", ["Id", "mpn", "url", "product_key"])
    hp_ids = {item_id(r.get("url")) for r in hp if item_id(r.get("url"))}
    own_item_ids = {str(r.get("item_id")) for r in reviews if str(r.get("is_own")) == "1" and r.get("item_id")}
    orphan_rev = own_item_ids - hp_ids
    print(f"own reviews: {len(own_item_ids)} distinct itemIds | itemIds NOT in homedepot_product: {len(orphan_rev)}")
    print(f"  orphan itemIds: {sorted(orphan_rev)[:15]}")
    pp = records("ma3331finostkis", ["Id", "mpn", "product_key", "product_link", "url"])
    plink_vals = [r.get("product_link") for r in pp if r.get("product_link")]
    print(f"page_product rows: {len(pp)} | product_link has values (stale?): {len(plink_vals)}")
    if plink_vals:
        print(f"  sample product_link: {plink_vals[:3]}")

    # ---- competitor domain ----
    print("\n== 竞品域 ==")
    cp = records("m0vk08vypm4jrl7", ["Id", "itemId", "name", "brand|slogan", "url"])
    cp_ids = {str(r.get("itemId")) for r in cp if r.get("itemId")}
    hdv1_listing_ids = {r["listing_key"].split(":")[-1] for r in listings if r.get("listing_key") and r["listing_key"].startswith("HOME_DEPOT:")}
    print(f"competitor_product: {len(cp)} rows | itemId present: {len(cp_ids)} | "
          f"overlap with HDV1 listings: {len(cp_ids & hdv1_listing_ids)} | "
          f"in HDV1 but not competitor_product: {len(hdv1_listing_ids - cp_ids)}")
    no_item = [r for r in cp if not r.get("itemId")]
    print(f"competitor_product without itemId: {len(no_item)}")
    sale = records("munzznlmfzd9d2t", ["商品名称", "品牌", "售价", "估算销量"])
    # name-match sale -> competitor_product
    cp_names = {str(r.get("name") or "").strip().lower() for r in cp if r.get("name")}
    sale_names = {str(r.get("商品名称") or "").strip().lower() for r in sale if r.get("商品名称")}
    print(f"competitor_product_sale: {len(sale)} | name-match to competitor_product: {len(sale_names & cp_names)} / {len(sale_names)}")

    # ---- GSC domain ----
    print("\n== GSC 域 ==")
    gsc = records("mfbg6s0mv9l74ky", ["Id", "date", "page", "query"])
    gsc_nopage = sum(1 for r in gsc if not r.get("page"))
    gsc_noquery = sum(1 for r in gsc if not r.get("query"))
    print(f"gsc_data_raw: {len(gsc)} | rows without page link: {gsc_nopage} | without query link: {gsc_noquery}")
    pages = records("m0fl1tcxyopz1s3", ["Id", "page_url"])
    queries = records("muav8zitnoqlauu", ["Id", "分组键"])
    page_ids = {r["Id"] for r in pages}
    query_ids = {r["Id"] for r in queries}
    gsc_page_ids = {r["page"].get("Id") for r in gsc if isinstance(r.get("page"), dict)}
    gsc_query_ids = {r["query"].get("Id") for r in gsc if isinstance(r.get("query"), dict)}
    print(f"gsc page links valid: {len(gsc_page_ids & page_ids)} | query links valid: {len(gsc_query_ids & query_ids)}")
    print(f"page dimension rows unreferenced by gsc: {len(page_ids - gsc_page_ids)} | query dim rows unreferenced: {len(query_ids - gsc_query_ids)}")


if __name__ == "__main__":
    main()
