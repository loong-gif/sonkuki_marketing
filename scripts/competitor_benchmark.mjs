// Home Depot own-vs-competitor market benchmark (homedepot_competitors_compare.md).
//
// Pure module, no database or DOM dependencies. It implements the optimized
// plan for the Pergola pilot (and any other category by parameter):
//
//   Step 1  buildUnifiedTable         - own + competitor listings, `side` field,
//                                       deduplicated by item ID, snapshot-dated
//   Step 1  aggregateCompetitorUnits  - competitor Product Units (brand x
//                                       Category x Size x Material + core fn)
//   Step 2  buildComparableGroups     - each own SKU matched to the competitor
//                                       unit group it can be benchmarked against
//   Step 3  benchmarkOwnSkus          - price / rating / review count / low-star
//                                       share / themes vs unit-group medians
//   Step 4  aggregateUnits            - variant SKUs merged into one Product
//                                       Unit, one primary action per unit
//   Step 5  buildCoverage / buildVOC  - coverage stats, sample-gated VOC
//
// The dashboard consumes buildBenchmark() which returns the areas the first
// version adds: Benchmark Coverage, Product Benchmark, VOC Comparison.
//
// Comparison basis: core price / rating / review comparisons are computed on
// Product Units for BOTH sides. Listing counts only describe market coverage.
// SONKUKI units = variant SKUs sharing one group; competitor units = one
// (brand, group) pair. Grouping follows the plan's rule (Category x Size x
// Material, with Louvered as the core function).

// Keep in sync with build_dashboard_snapshot.mjs (it re-imports this list).
// Theme rules are deliberately greedy: low-star reviews should almost always
// land on an actionable theme rather than "Other". Empty-text reviews (photo
// reviews / missing text) still fall to "Other" as the honest fallback.
// Broad words (thin/fit/hard/soft/cheap) are only used in problem phrases or
// with word boundaries so neutral usage (e.g. "think", "hardware") is not
// misclassified.
export const THEME_RULES = [
  ["Assembly & parts", /assembl|install|setup|bolt|screw|part|hardware|instruction|manual|wrench|step|piece|guide|tool|fasten|tighten|misaligned|alignment|hard to (assemble|put|build)|difficult to (assemble|put|build)|missing (screw|bolt|part)|extra (screw|bolt|part)|instructions? (were|are) (confusing|unclear|missing|wrong)|(took|takes) (hours|hrs|long) to (assemble|put together|build|install)/i],
  ["Durability & material", /rust|corrosion|durab|material|sturdy|quality|break|bent|tear|oxidiz|pitting|discolor|fading|fade|crack|weld|peel|warp|flimsy|cheap(ly| (made|material|frame|metal))?|snap(ped|ping| off)?|broke|split|chip|dent|hollow|rusty|weaken|too thin|thin (frame|metal|material|wall)|poor quality|low quality/i],
  ["Comfort & cushion", /cushion|comfort|seat|fabric|soft|height|headroom|slope|fit|too tall|too low|too small|ergonom|uncomfortable|backrest|recline|padding|sag|lumpy|thin cushion/i],
  ["Stability & weather", /wind|stable|stability|weather|rain|water|leak|storm|wobble|shake|tilt|sway|flood|snow|ice|mold|mildew|shaky|unsteady|hold up/i],
  ["Shipping & damage", /ship|deliver|box|damage|scratch|missing|order|backorder|arrive|late|delay|promise|never arrive|shipping|package|tracking|arrived|parcel|undeliver|wrong (item|part)|missing (part|piece|screw)|dented|bent in shipping/i],
];

// Recommendation thresholds (deterministic; first matching rule wins).
export const PRICE_PREMIUM_RATIO = 1.1; // own price >= median * 1.1 (>= +10%) -> check premium
export const RATING_TIE = 0.1; // rating gap within +/- 0.1 is treated as tied
export const REVIEW_GAP_RATIO = 0.5; // own reviews < median * 0.5 -> gather reviews
export const LOWSTAR_GAP = 0.05; // own low-star share exceeds group by > 5pp -> VOC action
export const MIN_REVIEWS_FOR_SHARE = 5; // low-star share is only reported on >= 5 reviews
export const MIN_VOC_SAMPLE = 10; // own low-star reviews below this -> no strong VOC conclusion
export const VOC_PP_THRESHOLD = 5; // theme gap in percentage points that counts as a market difference
export const SIZE_TOLERANCE_FT = 1; // same-material fallback: dimensions within +/- 1 ft

const number = (value) => Number(value || 0);
const clean = (value) => String(value ?? "").trim();

export const classifyTheme = (text) => {
  const value = clean(text);
  const rule = THEME_RULES.find(([, regex]) => regex.test(value));
  return rule ? rule[0] : "Other";
};

export const median = (values) => {
  const list = values
    .filter((value) => value !== null && value !== undefined && clean(value) !== "" && Number.isFinite(Number(value)))
    .map(Number)
    .sort((a, b) => a - b);
  if (!list.length) return null;
  const middle = Math.floor(list.length / 2);
  return list.length % 2 ? list[middle] : (list[middle - 1] + list[middle]) / 2;
};

// Parse category / size / material / louvered from a Home Depot listing name.
// Category detection order matters: pergola accessories are split out so they
// never pollute the real pergola benchmark.
export const parseAttributes = (name) => {
  const value = clean(name);
  const lower = value.toLowerCase();

  let category = "Other";
  if (/pergola/i.test(lower)) category = /accessor|privacy screen|pull-down screen/i.test(lower) ? "Pergola Accessory" : "Pergola";
  else if (/gazebo/i.test(lower)) category = "Gazebo";
  else if (/umbrella/i.test(lower)) category = /umbrella base|umbrella stand|umbrella for|umbrella replacement/i.test(lower) ? "Umbrella Accessory" : "Umbrella";
  else if (/parasol/i.test(lower)) category = "Umbrella";
  else if (/canopy/i.test(lower)) category = "Canopy";
  else if (/chair|sofa|table|bench|set|sectional|bistro|lounger|loveseat|furniture|swing|rocker|seat/i.test(lower)) category = "Patio Furniture";

  // Size: both dimensions with "ft" (e.g. "12 ft. x 14 ft.") first, then the
  // looser "10 x 10 ft." form. Dimensions are sorted ascending so 14x12 and
  // 12x14 group together.
  let sizeW = null;
  let sizeD = null;
  const bothFt = value.match(/(\d{1,2}(?:\.\d+)?)\s*ft\.?\s*x\s*\.?\s*(\d{1,2}(?:\.\d+)?)\s*ft/i);
  const secondFt = value.match(/(\d{1,2}(?:\.\d+)?)\s*x\s*(\d{1,2}(?:\.\d+)?)\s*ft\.?/i);
  const match = bothFt || secondFt;
  if (match) {
    const dims = [parseFloat(match[1]), parseFloat(match[2])].filter((value) => value > 0).sort((a, b) => a - b);
    if (dims.length === 2) {
      [sizeW, sizeD] = dims;
    }
  }

  let material = "Other";
  if (/aluminized\s*steel/i.test(lower)) material = "Steel"; // steel core, aluminum coating
  else if (/aluminum/i.test(lower)) material = "Aluminum";
  else if (/steel|metal|iron/i.test(lower)) material = "Steel";
  else if (/cedar|wood|bamboo/i.test(lower)) material = "Wood";
  else if (/vinyl|wpc/i.test(lower)) material = "Vinyl";

  return {
    category,
    sizeW,
    sizeD,
    sizeLabel: sizeW && sizeD ? `${sizeW}×${sizeD} ft` : "",
    material,
    louvered: /louver/i.test(lower),
  };
};

// Machine-friendly group key, e.g. "Louvered Pergola × 12×14 ft × Steel".
export const groupKey = (attrs) =>
  `${attrs.louvered ? "Louvered " : ""}${attrs.category} × ${attrs.sizeLabel || "any size"} × ${attrs.material}`;

// Human-friendly group label, e.g. "Louvered Pergola · 12×14 ft · Steel".
export const groupLabel = (attrs) => groupKey(attrs).replace(/\s×\s/g, " · ");

const medianOf = (rows, key) => median(rows.map((row) => number(row[key])).filter((value) => value > 0));

// Step 1: one unified table of own + competitor listings with a `side` marker.
// `ownLouveredOverrides` is a Set of own item IDs whose titles omit the word
// "Louvered" even though the product is louvered (confirmed by sibling SKUs in
// the same series). Sonkuki-branded rows captured in the competitor sweep are
// own products and are excluded from the competitor side.
export const buildUnifiedTable = ({ hdProducts = [], competitorProducts = [], snapshotDate, ownLouveredOverrides = new Set() }) => {
  const byItemId = new Map();
  hdProducts.forEach((row) => {
    const itemId = clean(row.itemId);
    if (!itemId || byItemId.has(itemId)) return;
    const attrs = parseAttributes(row.name);
    if (ownLouveredOverrides.has(itemId)) attrs.louvered = true;
    byItemId.set(itemId, {
      side: "own", itemId, mpn: clean(row.mpn), name: clean(row.name),
      brand: "SONKUKI", url: clean(row.url), ...attrs,
      price: number(row.salePrice) || number(row.originalPrice), rating: number(row.rating), reviewCount: number(row.reviewCount),
    });
  });
  competitorProducts.forEach((row) => {
    const itemId = clean(row.itemId);
    const brand = clean(row.brand) || "Unknown";
    if (!itemId || byItemId.has(itemId) || /sonkuki/i.test(brand)) return; // own rows win; own brand is not a competitor
    const attrs = parseAttributes(row.name);
    byItemId.set(itemId, {
      side: "competitor", itemId, mpn: "", name: clean(row.name),
      brand, url: "", ...attrs,
      price: number(row.salePrice) || number(row.originalPrice), rating: number(row.rating), reviewCount: number(row.reviewCount),
    });
  });
  return [...byItemId.values()].map((row) => ({ ...row, snapshot_date: snapshotDate || "" }));
};

// Step 1: competitor Product Units. One unit per (brand, group) pair: the same
// brand selling several listings in one comparable group is one product. The
// unit's price is the median of its listings, its rating is review-weighted,
// and its review count is the sum — so a brand with many near-duplicate
// listings is not weighted multiple times in the benchmark.
export const aggregateCompetitorUnits = (competitorRows) => {
  const byKey = new Map();
  for (const row of competitorRows) {
    const key = `${row.brand} | ${groupKey(row)}`;
    const list = byKey.get(key) || [];
    list.push(row);
    byKey.set(key, list);
  }
  return [...byKey.values()].map((rows) => {
    const prices = rows.map((row) => number(row.price) || number(row.salePrice)).filter((value) => value > 0).sort((a, b) => a - b);
    const rated = rows.filter((row) => row.rating > 0 && row.reviewCount > 0);
    const totalReviews = rated.reduce((sum, row) => sum + row.reviewCount, 0);
    const reference = rows[0];
    return {
      ...reference,
      listingCount: rows.length,
      itemIds: rows.map((row) => row.itemId),
      priceMedian: median(prices),
      priceMin: prices.length ? prices[0] : null,
      priceMax: prices.length ? prices.at(-1) : null,
      rating: totalReviews ? rated.reduce((sum, row) => sum + row.rating * row.reviewCount, 0) / totalReviews : null,
      reviewCount: rows.reduce((sum, row) => sum + row.reviewCount, 0),
    };
  });
};

// Step 2: per own SKU, the competitor unit group it is benchmarked against.
// Size is the primary differentiator for a pergola purchase, so exact-size
// competitors rank above same-material ones:
//   exact     same core + same material + exact same size
//   tolerance same core + same material + both dimensions within SIZE_TOLERANCE_FT
//   size      same core + exact same size, any material
//   material  same core + same material, any size
//   none      no competitor unit matches the own SKU's core function
export const buildComparableGroups = ({ ownRows, competitorRows }) => {
  const byCore = new Map();
  for (const row of competitorRows) {
    const key = `${row.louvered ? "Louvered" : "Standard"} ${row.category}`;
    const list = byCore.get(key) || [];
    list.push(row);
    byCore.set(key, list);
  }
  const sizeWithin = (own, comp, tolerance) => {
    if (!own.sizeW || !comp.sizeW) return false;
    return Math.abs(own.sizeW - comp.sizeW) <= tolerance && Math.abs(own.sizeD - comp.sizeD) <= tolerance;
  };
  return ownRows.map((own) => {
    const coreKey = `${own.louvered ? "Louvered" : "Standard"} ${own.category}`;
    const coreRows = byCore.get(coreKey) || [];
    const sameMaterial = coreRows.filter((row) => row.material === own.material);
    const exact = sameMaterial.filter((row) => row.sizeW === own.sizeW && row.sizeD === own.sizeD);
    const tolerance = !exact.length && own.sizeW
      ? sameMaterial.filter((row) => sizeWithin(own, row, SIZE_TOLERANCE_FT))
      : [];
    const size = !exact.length && !tolerance.length && own.sizeW
      ? coreRows.filter((row) => row.sizeW === own.sizeW && row.sizeD === own.sizeD)
      : [];
    const material = !exact.length && !tolerance.length && !size.length ? sameMaterial : [];
    const tier = exact.length ? "exact" : tolerance.length ? "tolerance" : size.length ? "size" : material.length ? "material" : "none";
    const competitors = exact.length ? exact : tolerance.length ? tolerance : size.length ? size : material;
    return {
      itemId: own.itemId, mpn: own.mpn, name: own.name, category: own.category,
      groupKey: groupKey(own), groupLabel: groupLabel(own), tier, wide: tier === "size" || tier === "material",
      competitorCount: competitors.length,
      competitorListingCount: competitors.reduce((sum, row) => sum + (row.listingCount || 1), 0),
      competitorItemIds: competitors.flatMap((row) => row.itemIds || [row.itemId]),
      competitorBrands: [...new Set(competitors.map((row) => row.brand))],
      competitors,
    };
  });
};

export const MATCH_QUALITY = {
  exact: "高置信度",
  tolerance: "中置信度",
  size: "低置信度",
  material: "低置信度",
  none: "无可比",
};

// Step 3: per own SKU comparison against its competitor unit group. Medians
// are computed over competitor units (not listings) so both sides share the
// Product Unit basis.
export const benchmarkOwnSkus = ({ ownRows, competitorRows, ownReviews = [], competitorReviews = [] }) => {
  const groups = buildComparableGroups({ ownRows, competitorRows });
  const ownReviewsByItem = new Map();
  for (const review of ownReviews) {
    const itemId = clean(review.itemId);
    if (!itemId) continue;
    const list = ownReviewsByItem.get(itemId) || [];
    list.push(review);
    ownReviewsByItem.set(itemId, list);
  }
  const competitorReviewsByItem = new Map();
  for (const review of competitorReviews) {
    const itemId = clean(review.itemId);
    if (!itemId) continue;
    const list = competitorReviewsByItem.get(itemId) || [];
    list.push(review);
    competitorReviewsByItem.set(itemId, list);
  }
  const lowStarShare = (reviews) => {
    if (reviews.length < MIN_REVIEWS_FOR_SHARE) return null;
    return reviews.filter((row) => number(row.rating) <= 2).length / reviews.length;
  };
  const topTheme = (reviews) => {
    const negative = reviews.filter((row) => number(row.rating) <= 2);
    const source = negative.length ? negative : reviews;
    const counts = {};
    source.forEach((row) => { const theme = row.theme || classifyTheme(""); counts[theme] = (counts[theme] || 0) + 1; });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([theme]) => theme);
  };
  return groups.map((group) => {
    const own = ownRows.find((row) => row.itemId === group.itemId) || {};
    const compMedianPrice = median(group.competitors.map((row) => row.priceMedian).filter((value) => value > 0));
    const compMedianRating = median(group.competitors.map((row) => row.rating).filter((value) => value > 0));
    const compMedianReviews = median(group.competitors.map((row) => row.reviewCount));
    const ownReviews = ownReviewsByItem.get(group.itemId) || [];
    const groupReviews = group.competitorItemIds.flatMap((itemId) => competitorReviewsByItem.get(itemId) || []);
    const ownLowStar = lowStarShare(ownReviews);
    const compLowStar = lowStarShare(groupReviews);
    const priceDelta = own.price > 0 && compMedianPrice ? own.price - compMedianPrice : null;
    const ratingDelta = own.rating > 0 && compMedianRating ? own.rating - compMedianRating : null;
    const reviewDelta = own.reviewCount != null && compMedianReviews != null ? own.reviewCount - compMedianReviews : null;
    const row = {
      itemId: group.itemId, mpn: group.mpn, name: group.name, url: own.url, brand: own.brand || "SONKUKI",
      category: group.category, groupKey: group.groupKey, groupLabel: group.groupLabel,
      tier: group.tier, wide: group.wide, matchQuality: MATCH_QUALITY[group.tier],
      competitorCount: group.competitorCount, competitorListingCount: group.competitorListingCount, competitorBrands: group.competitorBrands,
      price: own.price, compMedianPrice, priceDelta,
      rating: own.rating, compMedianRating, ratingDelta,
      reviewCount: own.reviewCount, compMedianReviews, reviewDelta,
      ownLowStarShare: ownLowStar, compLowStarShare: compLowStar,
      ownLowStarCount: ownReviews.filter((row) => number(row.rating) <= 2).length,
      compLowStarCount: groupReviews.filter((row) => number(row.rating) <= 2).length,
      ownTopThemes: topTheme(ownReviews), compTopThemes: topTheme(groupReviews),
    };
    return { ...row, action: recommend(row), ...actionDetail(row) };
  });
};

// Step 4: one primary action per SKU/unit (deterministic, first matching rule).
export const recommend = (row) => {
  const pricePct = row.compMedianPrice > 0 && row.price > 0 ? row.price / row.compMedianPrice : null;
  if (row.competitorCount === 0) return "补充产品覆盖";
  if (row.reviewCount === 0 && row.compMedianReviews > 0) return "建立社会证明"; // no social proof at all
  if (pricePct != null && pricePct >= PRICE_PREMIUM_RATIO) return "检查价格溢价"; // own >= median * 1.1
  if (row.ownLowStarShare != null && row.compLowStarShare != null && row.ownLowStarShare > row.compLowStarShare + LOWSTAR_GAP) {
    const top = row.ownTopThemes[0] || "";
    if (top === "Assembly & parts") return "改善安装体验";
    if (top === "Durability & material") return "改善材料或耐用性";
    return "强化产品卖点"; // theme is not an actionable product action (e.g. Other)
  }
  if (row.rating > 0 && row.compMedianRating > 0 && row.rating < row.compMedianRating - RATING_TIE) return "强化产品卖点";
  if (row.rating > 0 && row.compMedianRating > 0 && row.rating >= row.compMedianRating - RATING_TIE && row.compMedianReviews > 0 && row.reviewCount > 0 && row.reviewCount < row.compMedianReviews * REVIEW_GAP_RATIO) return "增加评论积累";
  return "保持价格";
};

// Structured detail for the action: problem, key evidence, one-line suggestion,
// and a low-confidence hint when the match quality is weak.
export const actionDetail = (row) => {
  const pct = (a, b) => (b > 0 ? `${Math.round((a / b) * 100)}%` : "—");
  const ratingTxt = (v) => (v > 0 ? v.toFixed(2) : "—");
  const premiumPct = row.compMedianPrice > 0 && row.price > 0 ? Math.round(((row.price - row.compMedianPrice) / row.compMedianPrice) * 100) : null;
  const lowConfidence = row.tier === "size" || row.tier === "material" ? "（匹配质量较低，建议人工核验）" : "";
  switch (recommend(row)) {
    case "检查价格溢价":
      return {
        problem: `售价 ${ratingTxt(row.price)} 高于竞品中位 ${ratingTxt(row.compMedianPrice)} ${premiumPct != null ? `约 ${premiumPct}%` : ""}`,
        evidence: `自家中位价 $${row.price} vs 竞品单位中位 $${row.compMedianPrice}（+${premiumPct}%）· 评分 ${ratingTxt(row.rating)} vs ${ratingTxt(row.compMedianRating)}`,
        suggestion: `确认溢价是否有差异化支撑；若无，考虑定价或强化卖点。${lowConfidence}`,
      };
    case "建立社会证明":
      return {
        problem: "无评论，缺乏社会证明",
        evidence: `自家评论 0 条 vs 竞品单位中位 ${row.compMedianReviews || 0} 条`,
        suggestion: `优先获取首批评论（测评、促销激励），建立基础信任。${lowConfidence}`,
      };
    case "增加评论积累":
      return {
        problem: `评论量显著低于竞品组`,
        evidence: `自家评论 ${row.reviewCount} 条 vs 竞品单位中位 ${row.compMedianReviews || 0} 条（约 ${row.compMedianReviews ? Math.round((row.reviewCount / row.compMedianReviews) * 100) : 0}%）`,
        suggestion: `评分不落后但缺社会证明，加大评论积累动作。${lowConfidence}`,
      };
    case "改善安装体验":
      return {
        problem: `低星评论占比高于竞品组`,
        evidence: `自家低星占比 ${(row.ownLowStarShare * 100).toFixed(1)}% vs 竞品 ${(row.compLowStarShare * 100).toFixed(1)}% · 主导主题 Assembly & parts`,
        suggestion: `重点优化安装说明、配件完整性与装配流程。${lowConfidence}`,
      };
    case "改善材料或耐用性":
      return {
        problem: `低星评论占比高于竞品组`,
        evidence: `自家低星占比 ${(row.ownLowStarShare * 100).toFixed(1)}% vs 竞品 ${(row.compLowStarShare * 100).toFixed(1)}% · 主导主题 Durability & material`,
        suggestion: `重点排查材料、防锈与耐用性问题。${lowConfidence}`,
      };
    case "强化产品卖点":
      return {
        problem: `评分落后于竞品中位`,
        evidence: `自家评分 ${ratingTxt(row.rating)} vs 竞品单位中位 ${ratingTxt(row.compMedianRating)}`,
        suggestion: `强化卖点、价格外的差异化或改进体验，先补差距再提价。${lowConfidence}`,
      };
    case "补充产品覆盖":
      return {
        problem: "该规格在竞品中无同口径基准",
        evidence: `当前 Category 内未匹配到同类竞品单位`,
        suggestion: `评估补齐主流规格，或验证该细分市场的独特性。${lowConfidence}`,
      };
    default:
      return {
        problem: "价格、评分与评论量处于竞品组合理区间",
        evidence: `价格 ${pct(row.price, row.compMedianPrice)} of median · 评分 ${ratingTxt(row.rating)} vs ${ratingTxt(row.compMedianRating)}`,
        suggestion: "维持当前策略，持续跟踪。",
      };
  }
};

// Step 4: aggregate per-SKU rows into Product Units. Variant SKUs sharing one
// comparable group (e.g. R-PQL-1013BN / R-PQL-LED1013BN / R-PKD-LED1013GY)
// become one unit. Own-side metrics are combined; the competitor benchmark is
// identical for every member because they share one group.
export const aggregateUnits = (skus) => {
  const byGroup = new Map();
  for (const sku of skus) {
    const list = byGroup.get(sku.groupKey) || [];
    list.push(sku);
    byGroup.set(sku.groupKey, list);
  }
  const weightedRating = (rows) => {
    const rated = rows.filter((row) => row.rating > 0 && row.reviewCount > 0);
    const total = rated.reduce((sum, row) => sum + row.reviewCount, 0);
    return total ? rated.reduce((sum, row) => sum + row.rating * row.reviewCount, 0) / total : null;
  };
  return [...byGroup.values()].map((rows) => {
    const prices = rows.map((row) => row.price).filter((value) => value > 0).sort((a, b) => a - b);
    const reference = rows[0]; // competitor benchmark is shared by the whole group
    const unit = {
      groupKey: reference.groupKey, groupLabel: reference.groupLabel, category: reference.category,
      tier: reference.tier, wide: reference.wide, matchQuality: reference.matchQuality,
      competitorCount: reference.competitorCount, competitorListingCount: reference.competitorListingCount, competitorBrands: reference.competitorBrands,
      skuCount: rows.length, mpns: rows.map((row) => row.mpn).filter(Boolean),
      skus: rows,
      priceMin: prices.length ? prices[0] : null,
      priceMax: prices.length ? prices.at(-1) : null,
      priceMedian: median(prices),
      rating: weightedRating(rows),
      reviewCount: rows.reduce((sum, row) => sum + row.reviewCount, 0),
      compMedianPrice: reference.compMedianPrice, compMedianRating: reference.compMedianRating, compMedianReviews: reference.compMedianReviews,
      ownLowStarShare: reference.ownLowStarShare, compLowStarShare: reference.compLowStarShare,
      ownLowStarCount: rows.reduce((sum, row) => sum + (row.ownLowStarCount || 0), 0),
      compLowStarCount: reference.compLowStarCount,
      ownTopThemes: reference.ownTopThemes, compTopThemes: reference.compTopThemes,
    };
  const representative = {
      ...reference,
      price: unit.priceMedian || 0,
      rating: unit.rating || 0,
      reviewCount: unit.reviewCount,
      priceDelta: unit.priceMedian && reference.compMedianPrice ? unit.priceMedian - reference.compMedianPrice : null,
      ratingDelta: unit.rating && reference.compMedianRating ? unit.rating - reference.compMedianRating : null,
      reviewDelta: reference.compMedianReviews != null ? unit.reviewCount - reference.compMedianReviews : null,
    };
    return { ...unit, ...representative, action: recommend(representative), ...actionDetail(representative), confidence: confidenceOf(reference) };
  });
};

// Match quality mapped to a confidence label for the action.
export const confidenceOf = (row) => (row.tier === "exact" ? "高" : row.tier === "tolerance" ? "中" : row.tier === "none" ? "无" : "低");

// Step 5: group-level VOC comparison. Own low-star share is only compared when
// the own sample is large enough (MIN_VOC_SAMPLE); below that no "above/below
// market" conclusion is drawn. Differences are reported in percentage points.
export const buildVOC = ({ ownRows, competitorRows, ownReviews = [], competitorReviews = [], category }) => {
  const ownCategoryIds = new Set(ownRows.filter((row) => row.category === category).map((row) => row.itemId));
  const compCategoryIds = new Set(competitorRows.filter((row) => row.category === category).map((row) => row.itemId));
  const ownCategory = ownReviews.filter((row) => ownCategoryIds.has(clean(row.itemId)));
  const compCategory = competitorReviews.filter((row) => compCategoryIds.has(clean(row.itemId)));
  const share = (reviews) => {
    const negative = reviews.filter((row) => number(row.rating) <= 2);
    const counts = {};
    negative.forEach((row) => { const theme = row.theme || classifyTheme(""); counts[theme] = (counts[theme] || 0) + 1; });
    const total = negative.length || 1;
    return Object.fromEntries(Object.entries(counts).map(([theme, count]) => [theme, count / total]));
  };
  const ownLowStarCount = ownCategory.filter((row) => number(row.rating) <= 2).length;
  const compLowStarCount = compCategory.filter((row) => number(row.rating) <= 2).length;
  const ownShare = share(ownCategory);
  const compShare = share(compCategory);
  const themes = [...new Set([...Object.keys(ownShare), ...Object.keys(compShare)])].sort();
  const rows = themes.map((theme) => ({
    theme, ownShare: ownShare[theme] || 0, compShare: compShare[theme] || 0,
    gapPp: Math.round(((ownShare[theme] || 0) - (compShare[theme] || 0)) * 1000) / 10, // percentage points, 1 decimal
  }));
  const sampleInsufficient = ownLowStarCount < MIN_VOC_SAMPLE;
  const above = sampleInsufficient ? [] : rows.filter((row) => row.gapPp > VOC_PP_THRESHOLD).sort((a, b) => b.gapPp - a.gapPp);
  const below = sampleInsufficient ? [] : rows.filter((row) => row.gapPp < -VOC_PP_THRESHOLD).sort((a, b) => a.gapPp - b.gapPp);
  return {
    category,
    ownLowStarCount, compLowStarCount, sampleInsufficient,
    rows,
    ownAboveMarket: above, ownBetter: below,
  };
};

// Dashboard shape: Benchmark Coverage + Product Benchmark + VOC Comparison.
export const buildBenchmark = (snapshot, category = "Pergola", snapshotDate = "", ownLouveredOverrides = new Set()) => {
  const unified = buildUnifiedTable({
    hdProducts: snapshot.hdProducts || [],
    competitorProducts: snapshot.competitor?.products || [],
    snapshotDate,
    ownLouveredOverrides,
  });
  const ownRows = unified.filter((row) => row.side === "own" && row.category === category);
  const competitorRows = unified.filter((row) => row.side === "competitor");
  const ownAll = unified.filter((row) => row.side === "own");
  const competitorUnits = aggregateCompetitorUnits(competitorRows);
  const skus = benchmarkOwnSkus({
    ownRows,
    competitorRows: competitorUnits,
    ownReviews: snapshot.reviews || [],
    competitorReviews: snapshot.competitor?.reviews || [],
  });
  const units = aggregateUnits(skus);
  const competitorUnitsInCategory = competitorUnits.filter((row) => row.category === category);
  const coverage = buildCoverage({ ownRows, competitorRows, competitorUnits: competitorUnitsInCategory, skus, units });
  const voc = buildVOC({
    ownRows: ownAll, competitorRows,
    ownReviews: snapshot.reviews || [],
    competitorReviews: snapshot.competitor?.reviews || [],
    category,
  });
  const priority = units
    .filter((row) => row.action !== "保持价格")
    .sort((a, b) => priorityScore(b) - priorityScore(a))
    .slice(0, 10);
  return {
    generatedAt: new Date().toISOString(), snapshotDate, category,
    coverage, skus, units, voc, priorityActions: priority,
  };
};

const priorityScore = (row) => {
  let score = 0;
  if (row.priceDelta > 0 && row.compMedianPrice) score += row.priceDelta / row.compMedianPrice;
  if (row.compMedianReviews > 0) score += Math.max(0, (row.compMedianReviews - row.reviewCount) / row.compMedianReviews);
  if (row.ratingDelta != null && row.ratingDelta < 0) score += Math.abs(row.ratingDelta);
  if (row.ownLowStarShare != null && row.compLowStarShare != null) score += Math.max(0, row.ownLowStarShare - row.compLowStarShare);
  return score;
};

// Step 5: Benchmark Coverage. Own and competitor numbers are scoped to the
// current Category; listings describe market coverage, units are the
// comparison basis. Match quality counts how many own units are exact,
// approximate (tolerance/size/material), or without a comparable.
export const buildCoverage = ({ ownRows, competitorRows, competitorUnits, skus, units }) => {
  const category = ownRows[0]?.category || categoryFrom(units) || competitorUnits[0]?.category || "Pergola";
  const own = ownRows.filter((row) => row.price > 0);
  const comp = competitorRows.filter((row) => row.price > 0 && row.category === category);
  const ratingOf = (rows) => {
    const weighted = rows.filter((row) => row.rating > 0 && row.reviewCount > 0);
    const total = weighted.reduce((sum, row) => sum + row.reviewCount, 0);
    return total ? weighted.reduce((sum, row) => sum + row.rating * row.reviewCount, 0) / total : null;
  };
  const exact = units.filter((row) => row.tier === "exact").length;
  const approximate = units.filter((row) => ["tolerance", "size", "material"].includes(row.tier)).length;
  const none = units.filter((row) => row.tier === "none").length;
  return {
    category,
    ownUnits: units.length, ownListings: ownRows.length,
    competitorUnits: competitorUnits.length, competitorListings: comp.length,
    ownMedianPrice: medianOf(own, "price"), competitorMedianPrice: medianOf(comp, "price"),
    ownAvgRating: ratingOf(ownRows), competitorAvgRating: ratingOf(comp),
    ownTotalReviews: ownRows.reduce((sum, row) => sum + row.reviewCount, 0),
    competitorTotalReviews: comp.reduce((sum, row) => sum + row.reviewCount, 0),
    matchExact: exact, matchApproximate: approximate, matchNone: none,
  };
};

const categoryFrom = (units) => units[0]?.category || "";
