// Keyword cannibalization identification (keyword_cannibalization.md).
//
// The dashboard previously labeled any query touching multiple URLs as
// "cannibalization" (raw URL count). This module replaces that with a
// share-based risk model over meaningful URLs only:
//
//   Primary URL   - the URL with the most impressions for the query
//   Meaningful    - impression share >= MEANINGFUL_SHARE_MIN OR
//                   impressions >= MEANINGFUL_IMPRESSIONS_MIN
//   Risk          - LOW    one meaningful URL, or primary share >= 80%
//                   MEDIUM  multiple meaningful URLs, primary share 60-79%
//                   HIGH    multiple meaningful URLs, primary share < 60%
//
// The caller is responsible for passing only VALID queries (per the plan,
// IRRELEVANT and UNKNOWN queries are excluded upstream). This module is
// pure and has no database or DOM dependencies.

export const MEANINGFUL_SHARE_MIN = 0.1; // impression share floor for a meaningful URL
export const MEANINGFUL_IMPRESSIONS_MIN = 50; // absolute impression floor for a meaningful URL
export const PRIMARY_SHARE_LOW_BOUND = 0.8; // primary share >= 0.8 -> LOW risk
export const PRIMARY_SHARE_HIGH_BOUND = 0.6; // primary share < 0.6 -> HIGH risk (with >= 2 meaningful URLs)

const number = (value) => Number(value || 0);

// Compute per-query cannibalization risk from GSC rows. Each row must carry
// `query`, `canonical_page`, `impressions`, `clicks`, and optionally
// `position_weight` (impressions * position) for weighted position.
export const cannibalizationRows = (rows) => {
  const byQuery = new Map();
  for (const row of rows) {
    const query = String(row.query ?? "").trim();
    if (!query) continue;
    const bucket = byQuery.get(query) || { query, rows: [] };
    bucket.rows.push(row);
    byQuery.set(query, bucket);
  }
  return [...byQuery.values()].map(({ query, rows: items }) => {
    const impressions = items.reduce((total, row) => total + number(row.impressions), 0);
    const clicks = items.reduce((total, row) => total + number(row.clicks), 0);
    const positionWeight = items.reduce((total, row) => total + number(row.position_weight), 0);
    const byUrl = new Map();
    for (const row of items) {
      const url = String(row.canonical_page ?? "").trim();
      if (!url) continue;
      byUrl.set(url, (byUrl.get(url) || 0) + number(row.impressions));
    }
    const urls = [...byUrl.entries()]
      .map(([url, urlImpressions]) => ({ url, impressions: urlImpressions, share: impressions ? urlImpressions / impressions : 0 }))
      .sort((a, b) => b.impressions - a.impressions || a.url.localeCompare(b.url));
    const primary = urls[0] || null;
    const meaningfulUrls = urls.filter((url) => url.share >= MEANINGFUL_SHARE_MIN || url.impressions >= MEANINGFUL_IMPRESSIONS_MIN);
    const primaryShare = primary ? primary.share : 0;
    const meaningfulCount = meaningfulUrls.length;
    const risk =
      meaningfulCount <= 1 || primaryShare >= PRIMARY_SHARE_LOW_BOUND
        ? "LOW"
        : primaryShare < PRIMARY_SHARE_HIGH_BOUND
          ? "HIGH"
          : "MEDIUM";
    return {
      query,
      impressions,
      clicks,
      ctr: impressions ? clicks / impressions : 0,
      position: impressions ? positionWeight / impressions : 0,
      primaryUrl: primary ? primary.url : "",
      primaryShare,
      meaningfulUrls,
      meaningfulCount,
      risk,
    };
  });
};

export const riskCounts = (rows) =>
  rows.reduce((counts, row) => {
    counts[row.risk] = (counts[row.risk] || 0) + 1;
    return counts;
  }, { LOW: 0, MEDIUM: 0, HIGH: 0 });

// QA predicate: a risk row is well-formed when it has a valid risk level,
// a bounded primary share, a primary URL for any query with impressions,
// and HIGH/MEDIUM implies at least two meaningful URLs.
export const isWellFormedRisk = (row) =>
  ["LOW", "MEDIUM", "HIGH"].includes(row.risk) &&
  row.primaryShare >= 0 &&
  row.primaryShare <= 1 &&
  (row.impressions === 0 || Boolean(row.primaryUrl)) &&
  (row.risk === "LOW" || row.meaningfulCount >= 2);
