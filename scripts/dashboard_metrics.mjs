export const canonicalUrl = (value) => {
  const raw = String(value ?? "").trim();
  if (!raw) return "";
  try {
    const url = new URL(raw);
    url.search = "";
    url.hash = "";
    return url.toString().replace(/\/$/, "");
  } catch {
    return raw.split(/[?#]/, 1)[0].replace(/\/$/, "");
  }
};

export const parseMappingIds = (value) => String(value ?? "").split(/[;|]/).map((item) => item.trim()).filter(Boolean);

export const ctrFromTotals = (clicks, impressions) => Number(impressions) > 0 ? Number(clicks) / Number(impressions) : 0;

export const weightedPosition = (rows) => {
  const impressions = rows.reduce((sum, row) => sum + Number(row.impressions || 0), 0);
  return impressions ? rows.reduce((sum, row) => sum + Number(row.position_weight || 0), 0) / impressions : 0;
};

export const dedupeReviews = (rows) => {
  const byUid = new Map();
  for (const row of rows) {
    const uid = String(row.review_uid || row.id || "").trim();
    if (!uid) continue;
    const current = byUid.get(uid);
    if (!current || String(row.itemId || "") < String(current.itemId || "")) byUid.set(uid, { ...row, review_uid: uid });
  }
  return [...byUid.values()];
};

export const potentialClicks = ({ impressions, ctr, benchmarkCtr }) => Math.max(0, Math.round(Number(impressions || 0) * Math.max(0, Number(benchmarkCtr || 0) - Number(ctr || 0))));

export const normalizeEntityLabel = (value) => String(value ?? "").trim().toLowerCase().replace(/\s+/g, " ");

export const parseCompactNumber = (value) => {
  const normalized = String(value ?? "").trim().replace(/[$,\s]/g, "").toLowerCase();
  const match = normalized.match(/^(-?\d+(?:\.\d+)?)([km])?$/);
  if (!match) return 0;
  const factor = match[2] === "k" ? 1000 : match[2] === "m" ? 1000000 : 1;
  return Number(match[1]) * factor;
};

export const dedupeByItemId = (rows) => {
  const byItemId = new Map();
  for (const row of rows) {
    const itemId = String(row.itemId ?? "").trim();
    if (!itemId) continue;
    const current = byItemId.get(itemId);
    if (!current || String(row.updatedAt ?? "") > String(current.updatedAt ?? "")) byItemId.set(itemId, { ...row, itemId });
  }
  return [...byItemId.values()];
};
