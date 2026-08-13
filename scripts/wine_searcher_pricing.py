"""Build volume-safe Wine-Searcher price exports from browser evidence.

Wine-Searcher product pages aggregate several package sizes.  This module
deliberately treats each merchant offer as an independent record and keeps it
only when its displayed size exactly matches the source product's total volume.
It does not infer a bottle size from an average price or a product-page title.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import quote_plus


SOURCE_FIELDS = [
    "parent_sku",
    "parent_name",
    "parent_price",
    "name",
    "price",
    "volume(ml)",
    "provider",
    "url",
]
COMPLETED_FIELDS = [
    "source_row_id",
    *SOURCE_FIELDS,
    "wine_searcher_match_status",
    "wine_searcher_product_name",
    "wine_searcher_product_url",
    "wine_searcher_match_evidence",
    "wine_searcher_search_location",
    "wine_searcher_checked_at",
    "wine_searcher_average_price",
    "wine_searcher_average_currency",
    "wine_searcher_average_volume_ml",
    "wine_searcher_avg_price_750ml",
    "wine_searcher_avg_price_750ml_currency",
    "wine_searcher_visible_offer_count",
    "wine_searcher_exact_volume_offer_count",
    "wine_searcher_offers",
]
OFFER_FIELDS = [
    "source_row_id",
    "parent_sku",
    "parent_name",
    "source_volume_ml",
    "wine_searcher_product_url",
    "wine_searcher_product_name",
    "merchant_name",
    "merchant_location",
    "offer_price",
    "currency",
    "tax_basis",
    "shipping_text",
    "stock_status",
    "offer_size_text",
    "offer_volume_ml",
    "offer_url",
    "search_location",
    "checked_at",
    "retrieval_method",
]

GENERIC_QUERY_TERMS = {
    "alc",
    "alcohol",
    "baijiu",
    "bottle",
    "bottles",
    "chinese",
    "collection",
    "edition",
    "free",
    "gift",
    "liquor",
    "limited",
    "premium",
    "sake",
    "shipping",
}
GENERIC_IDENTITY_TERMS = GENERIC_QUERY_TERMS | {
    "aged",
    "brewery",
    "daiginjo",
    "ginjo",
    "junmai",
    "nama",
    "rice",
    "tokubetsu",
    "years",
    "year",
}
CRITICAL_VARIANTS = {
    "aquarius",
    "aries",
    "black",
    "blue",
    "cancer",
    "capricorn",
    "dry",
    "golden",
    "nigori",
    "pisces",
    "red",
    "sake",
    "snake",
    "virgo",
    "white",
}


def parse_volume_ml(value: str | None) -> int | None:
    """Parse a displayed package size without guessing missing units."""
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*(ml|l|ltr|litre|liter)\b", value or "", re.I)
    if not match:
        return None
    amount = float(match.group(1))
    return round(amount * 1000) if match.group(2).lower() != "ml" else round(amount)


def source_volume_ml(value: object) -> int | None:
    """Read the cleaned CSV's numeric `volume(ml)` field safely."""
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return round(value) if value > 0 else None
    text = str(value or "").strip()
    if re.fullmatch(r"\d+(?:\.0+)?", text):
        return round(float(text))
    return parse_volume_ml(text)


def _currency(value: str) -> str | None:
    upper = value.upper()
    if "$" in value or "US$" in upper or "USD" in upper:
        return "USD"
    if "S$" in value or "SGD" in upper:
        return "SGD"
    if "€" in value or "EUR" in upper:
        return "EUR"
    if "£" in value or "GBP" in upper:
        return "GBP"
    return None


def _price(value: str) -> float | None:
    match = re.search(r"(?:US\$|USD|S\$|SGD|\$|€|EUR|£|GBP)\s*([\d,]+(?:\.\d{1,2})?)", value, re.I)
    return float(match.group(1).replace(",", "")) if match else None


def _displayed_price(value: object) -> float | None:
    """Normalize a browser-captured price without inventing a currency."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").strip()
    if re.fullmatch(r"\d+(?:\.\d{1,2})?", text):
        return float(text)
    return _price(text)


def parse_product_markdown(markdown: str, product_url: str) -> dict[str, object]:
    """Extract displayed Wine-Searcher product-level average metadata."""
    title = (re.search(r"^#\s+(.+?)\s*$", markdown, re.M) or [None, ""])[1].strip()
    average_match = re.search(
        r"(?:avg\.?\s*price\s*(?:\(ex-tax\))?|average\s*price)[\s\S]{0,100}?"
        r"((?:US\$|USD|S\$|SGD|\$|€|EUR|£|GBP)\s*[\d,]+(?:\.\d{1,2})?)[\s/]*(\d+(?:\.\d+)?\s*(?:ml|l|ltr|litre|liter))",
        markdown,
        re.I,
    )
    price_text = average_match.group(1) if average_match else ""
    volume_text = average_match.group(2) if average_match else ""
    return {
        "product_title": title,
        "product_url": product_url,
        "average_price": _price(price_text),
        "average_currency": _currency(price_text),
        "product_volume_ml": parse_volume_ml(volume_text),
    }


def extract_offers(markdown: str, product_url: str) -> list[dict[str, object]]:
    """Parse simple Markdown offer tables into independently sized offers.

    Browser extraction is preferred for production.  This parser also supports
    Firecrawl's Markdown tables, so the evidence format remains portable.
    """
    offers: list[dict[str, object]] = []
    for line in markdown.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0].lower() == "merchant" or set("".join(cells)) <= {"-", ":"}:
            continue
        price = _price(cells[1])
        if price is None:
            continue
        offers.append(
            {
                "merchant_name": cells[0],
                "offer_price": price,
                "currency": _currency(cells[1]),
                "offer_volume_ml": parse_volume_ml(cells[2]),
                "product_url": product_url,
            }
        )
    return offers


def filter_offers_by_volume(
    offers: Iterable[Mapping[str, object]], expected_volume_ml: int | None
) -> list[dict[str, object]]:
    """Keep only offers whose explicitly shown total size is exactly equal."""
    if expected_volume_ml is None:
        return []
    return [
        dict(offer)
        for offer in offers
        if isinstance(offer.get("offer_volume_ml"), int)
        and offer["offer_volume_ml"] == expected_volume_ml
        and str(offer.get("merchant_name") or "").strip()
    ]


def build_completed_rows(
    source_rows: Iterable[Mapping[str, object]], evidence_by_row: Mapping[str, Mapping[str, object]]
) -> list[dict[str, object]]:
    """Attach auditable pricing evidence and replace the source link with Wine-Searcher."""
    completed: list[dict[str, object]] = []
    for index, source in enumerate(source_rows, start=1):
        row = dict(source)
        row_id = str(row.get("row_id") or index)
        evidence = evidence_by_row.get(row_id, {})
        product = evidence.get("product") if isinstance(evidence.get("product"), Mapping) else {}
        offers = evidence.get("offers") if isinstance(evidence.get("offers"), list) else []
        average_volume = product.get("product_volume_ml") if product else None
        average_price = product.get("average_price") if product else None
        average_currency = product.get("average_currency") if product else None
        row.update(
            {
                "source_row_id": row_id,
                # This export represents Wine-Searcher pricing data.  Do not
                # leave an Uncle Fossil link in the primary source columns;
                # the Wine-Searcher page (or its query URL when no product
                # resolves) is the relevant evidence location.
                "provider": "wine-searcher",
                "url": product.get("product_url") if product else None,
                "wine_searcher_match_status": evidence.get("status", "not_checked"),
                "wine_searcher_product_name": product.get("product_title") if product else None,
                "wine_searcher_product_url": product.get("product_url") if product else None,
                "wine_searcher_match_evidence": evidence.get("reason"),
                "wine_searcher_search_location": evidence.get("search_location"),
                "wine_searcher_checked_at": evidence.get("checked_at"),
                "wine_searcher_average_price": average_price,
                "wine_searcher_average_currency": average_currency,
                "wine_searcher_average_volume_ml": average_volume,
                # Wine-Searcher displays the current product-page market
                # average per 750ml for the captured records.  Keep it in a
                # dedicated column so it cannot be mistaken for a supplier
                # offer at the source row's own bottle size.
                "wine_searcher_avg_price_750ml": average_price if average_volume == 750 else None,
                "wine_searcher_avg_price_750ml_currency": average_currency if average_volume == 750 else None,
                "wine_searcher_visible_offer_count": evidence.get("visible_offer_count", 0),
                "wine_searcher_exact_volume_offer_count": len(offers),
                "wine_searcher_offers": offers,
            }
        )
        completed.append(row)
    return completed


def _ascii_tokens(value: str) -> list[str]:
    text = unicodedata.normalize("NFKD", value or "").lower()
    text = re.sub(r"[^a-z0-9.]+", " ", text)
    return [token for token in text.split() if token]


def _without_size_and_packaging(value: str) -> list[str]:
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:ml|l|ltr|litre|liter)\b", " ", value, flags=re.I)
    text = re.sub(r"\b\d+\s*(?:x|\*)\s*\d+\b", " ", text, flags=re.I)
    return _ascii_tokens(text)


def make_query(parent_name: str, listing_name: str) -> str:
    """Construct a product-discovery URL without leaking source package size."""
    tokens = _without_size_and_packaging(listing_name or parent_name)
    tokens = [token for token in tokens if token not in GENERIC_QUERY_TERMS]
    return "https://www.wine-searcher.com/find/" + quote_plus(" ".join(tokens))


def _critical_tokens(value: str) -> set[str]:
    return {
        token
        for token in _without_size_and_packaging(value)
        if token not in GENERIC_IDENTITY_TERMS and len(token) > 1
    }


def assess_product_identity(source: Mapping[str, str], product_title: str, final_url: str) -> tuple[str, str]:
    """Reject query echo pages and near-matches before copying any price."""
    if not product_title or product_title.lower().startswith("showing results for"):
        return "not_found", "Wine-Searcher did not resolve the query to a product page"
    if "/find/" not in final_url or "/marketplace" in final_url:
        return "not_found", "Wine-Searcher canonical product page was not available"
    expected = _critical_tokens(source.get("name") or source.get("parent_name", ""))
    observed = set(_ascii_tokens(product_title))
    shared = expected & observed
    required_variants = (expected & CRITICAL_VARIANTS) | {token for token in expected if token.isdigit()}
    missing_variants = required_variants - observed
    # A specific product needs a product token beyond the generic product class.
    if not shared or missing_variants:
        detail = ", ".join(sorted(missing_variants)) or "no product token overlap"
        return "review_product_identity", f"product title lacks required identifier(s): {detail}"
    return "matched", f"matched title tokens: {', '.join(sorted(shared))}"


def _coerce_browser_offer(offer: Mapping[str, object]) -> dict[str, object]:
    result = dict(offer)
    result["offer_price"] = _price(str(result.get("price_text") or result.get("offer_price") or ""))
    result["currency"] = _currency(str(result.get("price_text") or result.get("currency") or ""))
    result["offer_volume_ml"] = parse_volume_ml(str(result.get("offer_size_text") or result.get("offer_volume_ml") or ""))
    return result


def _is_access_denied(raw: Mapping[str, object]) -> bool:
    """Return whether an observation contains no usable page data."""
    return (
        "access to this page has been denied" in str(raw.get("browser_title") or "").lower()
        or bool(raw.get("browser_error"))
    )


def prepare_evidence(source_rows: list[dict[str, str]], raw_evidence: list[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    """Convert browser observations into product-level evidence by source row."""
    by_row = {str(item.get("source_row_id")): item for item in raw_evidence if item.get("source_row_id")}
    # A single Wine-Searcher discovery URL can represent multiple source rows.
    # Reuse an already captured response if a duplicate retry was rate-limited;
    # each source row is still independently checked for title identity and size.
    page_cache: dict[str, Mapping[str, object]] = {}
    for item in raw_evidence:
        requested_url = str(item.get("requested_url") or "")
        if requested_url and not _is_access_denied(item):
            page_cache.setdefault(requested_url, item)
    evidence: dict[str, dict[str, object]] = {}
    source_by_id = {str(index): source for index, source in enumerate(source_rows, start=1)}
    for index, source in enumerate(source_rows, start=1):
        row_id = str(index)
        raw = by_row.get(row_id)
        if not raw:
            evidence[row_id] = {"status": "not_checked", "reason": "no browser evidence captured", "offers": []}
            continue
        if _is_access_denied(raw):
            cached = page_cache.get(str(raw.get("requested_url") or ""))
            if cached:
                raw = {
                    **cached,
                    "source_row_id": raw.get("source_row_id"),
                    "requested_url": raw.get("requested_url"),
                    "retrieval_method": "cached_duplicate_url",
                }
        browser_title = str(raw.get("browser_title") or "").lower()
        browser_error = str(raw.get("browser_error") or "")
        if "access to this page has been denied" in browser_title or browser_error:
            evidence[row_id] = {
                "status": "access_denied",
                "reason": browser_error or "Wine-Searcher denied this browser request before product data loaded",
                "product": {
                    "product_title": "",
                    "product_url": str(raw.get("final_url") or raw.get("requested_url") or ""),
                    "average_price": None,
                    "average_currency": None,
                    "product_volume_ml": None,
                },
                "offers": [],
                "visible_offer_count": 0,
                "search_location": raw.get("search_location", "USA"),
                "checked_at": raw.get("checked_at"),
                "retrieval_method": raw.get("retrieval_method", "egolite"),
            }
            continue
        product = {
            "product_title": str(raw.get("product_title") or ""),
            "product_url": str(raw.get("final_url") or raw.get("requested_url") or ""),
            "average_price": _displayed_price(raw.get("average_price")),
            "average_currency": _currency(
                str(raw.get("average_currency") or raw.get("average_price") or "")
            ),
            "product_volume_ml": source_volume_ml(raw.get("average_volume_ml")),
        }
        status, reason = assess_product_identity(source, product["product_title"], product["product_url"])
        all_offers = [_coerce_browser_offer(offer) for offer in raw.get("offers", []) if isinstance(offer, Mapping)]
        exact_offers = filter_offers_by_volume(all_offers, source_volume_ml(source.get("volume(ml)")))
        if status == "matched" and not exact_offers:
            status = "matched_no_exact_volume_offer"
            reason += "; no visible supplier offer has this exact displayed volume"
        if status != "matched" and status != "matched_no_exact_volume_offer":
            exact_offers = []
        evidence[row_id] = {
            "status": status,
            "reason": reason,
            "product": product,
            "offers": exact_offers,
            "visible_offer_count": len(all_offers),
            "search_location": raw.get("search_location", "USA"),
            "checked_at": raw.get("checked_at"),
            "retrieval_method": raw.get("retrieval_method", "egolite"),
        }

    # A Wine-Searcher page occasionally groups two named bottlings that happen
    # to share the same bottle size (for example, "Phoenix" and "Phoenix 18").
    # If the outbound merchant URL explicitly names a sibling-only identifier,
    # remove that offer rather than assigning it to the shorter source name.
    product_groups: dict[str, list[str]] = {}
    for row_id, item in evidence.items():
        if item.get("status") not in {"matched", "matched_no_exact_volume_offer", "review_product_identity"}:
            continue
        product = item.get("product")
        if isinstance(product, Mapping) and product.get("product_url"):
            product_groups.setdefault(str(product["product_url"]), []).append(row_id)
    for product_url, row_ids in product_groups.items():
        if len(row_ids) < 2:
            continue
        tokens_by_row = {
            row_id: _critical_tokens(source_by_id[row_id].get("name") or source_by_id[row_id].get("parent_name", ""))
            for row_id in row_ids
        }
        for row_id in row_ids:
            item = evidence[row_id]
            if item.get("status") not in {"matched", "matched_no_exact_volume_offer"}:
                continue
            own = tokens_by_row[row_id]
            sibling_only = set().union(*(tokens_by_row[other] - own for other in row_ids if other != row_id))
            if not sibling_only:
                continue
            offers = list(item.get("offers", []))
            compatible = [
                offer
                for offer in offers
                if not (sibling_only & set(_ascii_tokens(str(offer.get("offer_url", "")))))
            ]
            item["offers"] = compatible
            if item["status"] == "matched" and not compatible:
                item["status"] = "matched_no_exact_volume_offer"
                item["reason"] = str(item["reason"]) + "; visible same-size offers named a sibling variant"

    # The free product page can also surface a more specific sibling even when
    # that sibling's own query page resolves only to a search screen.  Detect a
    # source product whose identifiers strictly extend the current product and
    # reject a merchant URL that explicitly spells out that extra identifier.
    all_tokens = {
        row_id: _critical_tokens(source.get("name") or source.get("parent_name", ""))
        for row_id, source in source_by_id.items()
    }
    for row_id, item in evidence.items():
        if item.get("status") not in {"matched", "matched_no_exact_volume_offer"}:
            continue
        own = all_tokens[row_id]
        sibling_only = set().union(
            *(
                tokens - own
                for other_id, tokens in all_tokens.items()
                if other_id != row_id and len(own & tokens) >= 2 and own < tokens
            )
        )
        if not sibling_only:
            continue
        compatible = [
            offer
            for offer in item.get("offers", [])
            if not (sibling_only & set(_ascii_tokens(str(offer.get("offer_url", "")))))
        ]
        item["offers"] = compatible
        if item["status"] == "matched" and not compatible:
            item["status"] = "matched_no_exact_volume_offer"
            item["reason"] = str(item["reason"]) + "; visible same-size offers named a more-specific sibling"
    return evidence


def write_outputs(
    source_rows: list[dict[str, str]], evidence: Mapping[str, Mapping[str, object]], output_dir: Path
) -> tuple[Path, Path]:
    completed = build_completed_rows(source_rows, evidence)
    output_dir.mkdir(parents=True, exist_ok=True)
    completed_path = output_dir / "humblewine_unclefossil_wine_searcher_completed.csv"
    offers_path = output_dir / "humblewine_unclefossil_wine_searcher_offers.csv"
    with completed_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COMPLETED_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in completed:
            serialized = dict(row)
            serialized["wine_searcher_offers"] = json.dumps(row["wine_searcher_offers"], ensure_ascii=False)
            writer.writerow(serialized)
    with offers_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OFFER_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for index, source in enumerate(source_rows, start=1):
            row_id = str(index)
            item = evidence.get(row_id, {})
            product = item.get("product") if isinstance(item.get("product"), Mapping) else {}
            for offer in item.get("offers", []):
                writer.writerow(
                    {
                        "source_row_id": row_id,
                        "parent_sku": source.get("parent_sku", ""),
                        "parent_name": source.get("parent_name", ""),
                        "source_volume_ml": source.get("volume(ml)", ""),
                        "wine_searcher_product_url": product.get("product_url", ""),
                        "wine_searcher_product_name": product.get("product_title", ""),
                        **offer,
                        "search_location": item.get("search_location", ""),
                        "checked_at": item.get("checked_at", ""),
                        "retrieval_method": item.get("retrieval_method", ""),
                    }
                )
    return completed_path, offers_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/wine_searcher_pricing"))
    parser.add_argument("--query-manifest", type=Path)
    args = parser.parse_args()
    with args.input.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    if args.query_manifest:
        manifest = [
            {
                "source_row_id": str(index),
                "parent_sku": row.get("parent_sku", ""),
                "parent_name": row.get("parent_name", ""),
                "listing_name": row.get("name", ""),
                "source_volume_ml": source_volume_ml(row.get("volume(ml)")),
                "requested_url": make_query(row.get("parent_name", ""), row.get("name", "")),
            }
            for index, row in enumerate(source_rows, start=1)
        ]
        args.query_manifest.parent.mkdir(parents=True, exist_ok=True)
        args.query_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"query_manifest_rows={len(manifest)}")
        return
    if args.evidence is None:
        raise SystemExit("--evidence is required unless generating --query-manifest")
    with args.evidence.open(encoding="utf-8") as handle:
        raw_evidence = json.load(handle)
    if not isinstance(raw_evidence, list):
        raise SystemExit("browser evidence must be a JSON array")
    evidence = prepare_evidence(source_rows, raw_evidence)
    completed_path, offers_path = write_outputs(source_rows, evidence, args.output_dir)
    counts: dict[str, int] = {}
    for item in evidence.values():
        counts[str(item["status"])] = counts.get(str(item["status"]), 0) + 1
    print(f"completed={completed_path}")
    print(f"offers={offers_path}")
    print("status_counts=" + json.dumps(counts, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
