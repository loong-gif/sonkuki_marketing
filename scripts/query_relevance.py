"""Query relevance classification for SONKUKI GSC data.

Pure, dependency-free rules that tag every GSC query as VALID / IRRELEVANT /
UNKNOWN.  The module performs no network or database operations so it is safe
to import in tests.

Rule order follows irrelevant_query_clean.md:
  Rule 4 (external domain + customer-service terms) -> IRRELEVANT
  Rule 1 (SONKUKI brand terms)                     -> VALID
  Rule 2 (core product terms)                      -> VALID
  Rule 3 (known competitor / retailer)             -> VALID
  no match                                         -> UNKNOWN
"""

from __future__ import annotations

import re
import unicodedata

# Keep the classification vocabulary close to sonkuki_gsc_analysis.py so both
# layers stay consistent with the same business word lists.
BRAND_RE = re.compile(
    r"(?:sonkuki|son[\s-]?uki|sankuki|sonku\b|zimi\s+america|bonosuki)",
    re.I,
)

# Rule 2 product terms: document core phrases plus the category vocabulary the
# codebase already trusts (classify_theme / classify_intent in
# sonkuki_gsc_analysis.py).  Words are matched as substrings on the
# normalized query.
PRODUCT_TERMS = (
    # Pergola family
    "pergola", "louver", "louvered", "gazebo",
    # Umbrella family
    "umbrella", "parasol", "shade", "canopy",
    # Furniture family
    "furniture", "chair", "sofa", "sectional", "ottoman", "dining", "bistro",
    "table", "bench", "swing", "hammock", "adirondack",
    # Outdoor / patio context
    "patio", "outdoor", "garden", "backyard", "deck", "pool",
    # Accessories
    "accessor", "cover", "screen",
)

# Known competitor brands (brands table, excluding SONKUKI itself).
COMPETITOR_BRANDS = (
    "yardistry", "backyard discovery", "kozyard", "sunjoy", "veikous",
    "paragon outdoor", "sizzim", "joyside", "sojag", "vita",
    "covered outdoor", "canopia", "palram", "aecojoy", "purple leaf",
    "halmuz", "gazebest", "viwat", "joyesery", "phi villa", "meetleisure",
    "stabenton",
)

# Known retailers / sales channels (Rule 3).
RETAILERS = (
    "home depot", "homedepot", "walmart", "target", "lowes", "lowe's",
    "amazon", "costco", "wayfair", "sam's club", "sams club", "menards",
    "overstock", "kohl's", "kohls", "bed bath", "nebraska furniture mart",
    "shopify", "ebay", "etsy", "wish", "temu", "aliexpress",
)

# Customer-service terms (Rule 4).
CS_TERMS = (
    "customer service", "phone number", "support", "contact number",
    "official contact", "helpline", "customer support", "contact",
)

# External domain pattern used to spot "other site" queries (Rule 4).
DOMAIN_RE = re.compile(
    r"\b[a-z0-9][a-z0-9-]*\.(?:com|net|org|io|info|biz|us|ca|uk|co|de|fr|fi|"
    r"no|se|jp|ru|cn|cc|tv|nu|eu)\b",
    re.I,
)

VALID = "VALID"
IRRELEVANT = "IRRELEVANT"
UNKNOWN = "UNKNOWN"

REASON_BRAND = "BRAND"
REASON_BRAND_PRODUCT = "BRAND_PRODUCT"
REASON_PRODUCT = "PRODUCT"
REASON_COMPETITOR = "COMPETITOR_BRAND"
REASON_RETAILER = "RETAILER"
REASON_SUPPORT_QUERY = "UNRELATED_SUPPORT_QUERY"
REASON_NO_RULE = "NO_RULE_MATCH"


def normalize_query(value: str) -> str:
    """Normalize query text without discarding the original query."""
    normalized = unicodedata.normalize("NFKC", value or "").lower().strip()
    return re.sub(r"\s+", " ", normalized)


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _has_own_or_channel(text: str) -> bool:
    """True when the query references SONKUKI, a competitor or a retailer."""
    return bool(BRAND_RE.search(text)) or _has_any(text, COMPETITOR_BRANDS) or _has_any(text, RETAILERS)


def _extract_domains(query: str) -> list[str]:
    return [match.group(0).lower() for match in DOMAIN_RE.finditer(query)]


def classify_relevance(query: str) -> tuple[str, str]:
    """Return (relevance_status, exclusion_reason) for one raw query."""
    q = normalize_query(query)
    if not q:
        return UNKNOWN, REASON_NO_RULE

    # Rule 4 first: it resolves the known support-query anomaly and must
    # outrank product/brand matches on the same text.
    has_cs = _has_any(q, CS_TERMS)
    if has_cs and _extract_domains(q) and not _has_own_or_channel(q):
        return IRRELEVANT, REASON_SUPPORT_QUERY

    # Rule 1: SONKUKI brand terms.
    if BRAND_RE.search(q):
        return VALID, REASON_BRAND_PRODUCT if _has_any(q, PRODUCT_TERMS) else REASON_BRAND

    # Rule 2: core product terms.
    if _has_any(q, PRODUCT_TERMS):
        return VALID, REASON_PRODUCT

    # Rule 3: known competitor brand or retailer.
    if _has_any(q, COMPETITOR_BRANDS):
        return VALID, REASON_COMPETITOR
    if _has_any(q, RETAILERS):
        return VALID, REASON_RETAILER

    return UNKNOWN, REASON_NO_RULE


def classify_row(row: dict) -> dict:
    """Attach normalized_query / relevance_status / exclusion_reason to a row.

    The row must expose the raw query under ``query`` or ``分组键`` (the
    NocoDB column name).  The original row is copied, not mutated.
    """
    raw = str(row.get("query") or row.get("分组键") or "")
    status, reason = classify_relevance(raw)
    copy = dict(row)
    copy["query"] = raw
    copy["normalized_query"] = normalize_query(raw)
    copy["relevance_status"] = status
    copy["exclusion_reason"] = reason
    return copy


def build_clean_dataset(rows: list[dict]) -> list[dict]:
    """Keep only VALID rows: the Clean Query Dataset (Task 5)."""
    return [row for row in rows if row["relevance_status"] == VALID]
