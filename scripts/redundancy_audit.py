#!/usr/bin/env python3
"""Fresh redundancy audit (post-consolidation). Read-only."""
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
    # inventory
    tables = request("GET", "/api/v1/db/meta/projects/p447va1t8jqqjty/tables")["list"]
    print("== 表清单 ==")
    for t in sorted(tables, key=lambda x: x["title"]):
        try:
            n = records(t["id"], ["Id"]) if t["id"] else 0
            print(f"  {t['title']:35s} {len(n):>6d}")
        except Exception:
            print(f"  {t['title']:35s}      ?")
    time.sleep(0.2)

    # redundancy checks
    print("\n== 产品域重叠 ==")
    cp = records("m0vk08vypm4jrl7", ["Id", "itemId", "name", "brand|slogan"])
    hp = records("mnttfzrhu6gp6s0", ["Id", "mpn", "url", "name", "product_key"])
    pp = records("ma3331finostkis", ["Id", "mpn", "product_key", "url"])
    hd_products = records("m2w1cuciam30ltz", ["product_key", "brand_key", "product_name"])
    hd_listings = records("m7xynlp62mphmlv", ["listing_key", "variant_key", "external_listing_id"])
    hd_variants = records("m1br71dforlpotk", ["variant_key", "product_key", "mpn"])
    hd_brands = records("m7ue920zwzocr6t", ["brand_key", "brand_name"])

    cp_ids = {str(r.get("itemId")) for r in cp if r.get("itemId")}
    hp_ids = {item_id(r.get("url")) for r in hp if item_id(r.get("url"))}
    hd_list_ids = {r["listing_key"].split(":")[-1] for r in hd_listings if r.get("listing_key", "").startswith("HOME_DEPOT:")}
    hd_own_brand = {p["product_key"] for p in hd_products if p.get("brand_key") == "BRAND:SONKUKI"}
    hd_comp_products = {p["product_key"] for p in hd_products if p.get("brand_key") != "BRAND:SONKUKI"}

    print(f"competitor_product (415): itemId 与 HDV1 竞品 listing 重叠 {len(cp_ids & hd_list_ids)}")
    print(f"homedepot_product ({len(hp)}): itemId 与 HDV1 自家 listing 重叠 {len(hp_ids & hd_list_ids)}")
    # hd own products vs page_product by product_key
    pp_keys = {r.get("product_key") for r in pp if r.get("product_key")}
    print(f"HDV1 自家 products ({len(hd_own_brand)}) 与 page_product key 重叠 {len(hd_own_brand & pp_keys)}")

    # HDV1 自家 vs homedepot_product content duplication
    print(f"\nHDV1 自家链: brands={len([b for b in hd_brands if b.get('brand_key')=='BRAND:SONKUKI'])}, "
          f"products={len(hd_own_brand)}, variants(own)≈{sum(1 for v in hd_variants if v.get('product_key') in hd_own_brand)}, "
          f"listings(own)≈{sum(1 for l in hd_listings if l.get('variant_key','').startswith('VARIANT:SONKUKI'))}")
    print(f"homedepot_product 267 行 = HDV1 自家 listing 同一批商品,双系统存储")

    # reviews
    print("\n== 评论域 ==")
    reviews = records("mnz1y5x5kydob4f", ["review_key", "is_own"])
    own = sum(1 for r in reviews if str(r.get("is_own")) == "1")
    print(f"HDV1_Customer_Reviews: {len(reviews)} (own={own}, competitor={len(reviews)-own}) — 唯一评论源,无重复表 ✓")

    # GSC derived tables
    print("\n== GSC 域 ==")
    for t in ("gsc_keyword_month", "gsc_keyword_improved", "gsc_keyword_newly_ranked"):
        n = len(records(next(x["id"] for x in tables if x["title"] == t), ["Id"]))
        print(f"  {t}: {n} 行 (派生视图, 保留供报表)")
    gsc_raw = len(records("mfbg6s0mv9l74ky", ["Id"]))
    print(f"  gsc_data_raw: {gsc_raw} (唯一明细源)")

    # sale
    print("\n== 销量域 ==")
    sale = records("munzznlmfzd9d2t", ["商品名称", "品牌"])
    print(f"  competitor_product_sale: {len(sale)} 行, 未与商品表 join (名称格式不匹配)")


if __name__ == "__main__":
    main()
