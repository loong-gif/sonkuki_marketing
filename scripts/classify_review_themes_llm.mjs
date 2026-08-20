/** Seed + alias map for LLM review theme classification (keep in sync with normalize_review_themes.py). */

export const CANONICAL_THEMES = [
  "Assembly & parts",
  "Sturdy & durable",
  "Comfort & space",
  "Stability & weather",
  "Shipping & damage",
  "Other",
];

/** Synonyms the LLM may emit → canonical label used in NocoDB reviews.theme */
export const THEME_ALIASES = {
  "Durability & material": "Sturdy & durable",
  "Durable & material": "Sturdy & durable",
  "Weather & stability": "Stability & weather",
  "Comfort & cushion": "Comfort & space",
};

/** Labels dropped entirely (too generic / junk). */
export const DROP_THEMES = new Set([
  "Easy to use",
  "High quality",
  "Good materials",
  "Good design",
  "Good quality",
  "Works well",
  "Great product",
  "Great Features",
  "Great materials",
]);

export const THEME_SEED_PROMPT = `Classify the review into zero or more themes from this fixed list only:
${CANONICAL_THEMES.join(", ")}

Use these alias mappings when the text matches:
${Object.entries(THEME_ALIASES).map(([from, to]) => `- "${from}" → "${to}"`).join("\n")}

Never output these junk labels (omit them): ${[...DROP_THEMES].join(", ")}.`;

export function normalizeLlmThemes(rawThemes) {
  const input = Array.isArray(rawThemes) ? rawThemes : [];
  const out = [];
  const seen = new Set();
  for (const theme of input) {
    const value = String(theme || "").trim();
    if (!value || DROP_THEMES.has(value)) continue;
    const mapped = THEME_ALIASES[value] || value;
    if (!seen.has(mapped)) {
      seen.add(mapped);
      out.push(mapped);
    }
  }
  return out;
}
