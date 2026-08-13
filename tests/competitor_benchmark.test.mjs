import test from "node:test";
import assert from "node:assert/strict";
import {
  aggregateCompetitorUnits,
  aggregateUnits,
  buildBenchmark,
  buildComparableGroups,
  buildCoverage,
  buildUnifiedTable,
  buildVOC,
  classifyTheme,
  groupKey,
  median,
  parseAttributes,
  recommend,
} from "../scripts/competitor_benchmark.mjs";
import { SNAPSHOT } from "../outputs/sonkuki_gsc_insights_site/worker/dashboard_snapshot.js";

const own = (overrides = {}) => {
  const row = {
    itemId: "333087256", mpn: "R-PTE-1214BN", name: "Titan Series 12 ft. x 14 ft. Dark Brown Aluminized Steel Louvered Pergola",
    salePrice: 1664, originalPrice: 0, rating: 4.3333, reviewCount: 12, url: "https://www.homedepot.com/p/x/333087256",
    ...overrides,
  };
  return { ...row, ...parseAttributes(row.name) }; // benchmark helpers expect parsed rows
};
const competitor = (overrides = {}) => {
  const row = {
    itemId: "1001", name: "12 ft. x 14 ft. Gray Aluminum Louvered Pergola", brand: "Yardistry",
    salePrice: 1800, originalPrice: 0, rating: 4.8, reviewCount: 50, url: "",
    ...overrides,
  };
  return { ...row, ...parseAttributes(row.name) }; // buildComparableGroups expects parsed rows
};

test("parseAttributes extracts category, size, material, and louvered flag", () => {
  const attrs = parseAttributes("Titan Series 12 ft. x 14 ft. Dark Brown Aluminized Steel Louvered Pergola");
  assert.equal(attrs.category, "Pergola");
  assert.equal(attrs.sizeW, 12);
  assert.equal(attrs.sizeD, 14);
  assert.equal(attrs.sizeLabel, "12×14 ft");
  assert.equal(attrs.material, "Steel"); // aluminized steel -> Steel
  assert.equal(attrs.louvered, true);
});

test("parseAttributes handles loose size formats and accessory split", () => {
  assert.deepEqual(parseAttributes("10 x 10 ft. Aluminum Louvered Pergola with Adjustable Roof").sizeLabel, "10×10 ft");
  assert.deepEqual(parseAttributes("Sonkuki 9ft x 14 ft Gray Metal Louvered Patio Pergola").sizeLabel, "9×14 ft");
  assert.equal(parseAttributes("12 ft. Pull-Down Privacy Screen for Pergola Accessories").category, "Pergola Accessory");
  assert.equal(parseAttributes("Outdoor Offset HDPE Plastic Umbrella Base for Patio Umbrella").category, "Umbrella Accessory");
  assert.equal(parseAttributes("Aluminum Pergola with Retractable Canopy").louvered, false);
});

test("groupKey renders the plan's group label", () => {
  assert.equal(groupKey(parseAttributes("12 ft. x 14 ft. Aluminum Louvered Pergola")), "Louvered Pergola × 12×14 ft × Aluminum");
  assert.equal(groupKey(parseAttributes("10 x 10 ft. Aluminum Pergola")), "Pergola × 10×10 ft × Aluminum");
});

test("median ignores non-numeric and empty values", () => {
  assert.equal(median([4, 1, 3]), 3);
  assert.equal(median([10, 20, 30, 40]), 25);
  assert.equal(median([0, 5, "x", ""]), 2.5); // 0 is numeric; strings excluded
  assert.equal(median([]), null);
});

test("classifyTheme maps review text to the shared theme set", () => {
  assert.equal(classifyTheme("Assembly instructions were confusing, bolts missing"), "Assembly & parts");
  assert.equal(classifyTheme("rust on the frame within a month"), "Durability & material");
  assert.equal(classifyTheme("great product"), "Other");
});

test("classifyTheme covers oxidation, fit, and delivery complaints (no over-broad matches)", () => {
  assert.equal(classifyTheme("aluminum has oxidized and looks terrible"), "Durability & material");
  assert.equal(classifyTheme("the main stud cracked after 8 months"), "Durability & material");
  assert.equal(classifyTheme("rails hit me in the forehead, height too low"), "Comfort & cushion");
  assert.equal(classifyTheme("it is still quite shaky at the top, worried about wind and snow"), "Stability & weather");
  assert.equal(classifyTheme("never arrived, back order, kept promising delivery"), "Shipping & damage");
  // broad words must not fire on neutral usage
  assert.notEqual(classifyTheme("I think this is a great pergola"), "Durability & material");
  assert.notEqual(classifyTheme("hardware was easy to install"), "Comfort & cushion");
});

test("buildUnifiedTable marks sides, dedupes by itemId, and excludes own-brand competitors", () => {
  const table = buildUnifiedTable({
    hdProducts: [own()],
    competitorProducts: [
      competitor({ itemId: "2000", name: "10 ft. x 10 ft. Aluminum Pergola" }),
      competitor({ itemId: "3000", brand: "Sonkuki", name: "10 ft. x 10 ft. Aluminum Pergola" }), // own product captured as competitor
    ],
    snapshotDate: "2026-08-13",
  });
  assert.equal(table.length, 2);
  const ownRow = table.find((row) => row.itemId === "333087256");
  assert.equal(ownRow.side, "own");
  assert.equal(ownRow.brand, "SONKUKI");
  const compRow = table.find((row) => row.itemId === "2000");
  assert.equal(compRow.side, "competitor");
  assert.equal(table.some((row) => row.itemId === "3000"), false);
  assert.equal(table.every((row) => row.snapshot_date === "2026-08-13"), true);
});

test("comparable groups prefer exact size+material, then size, then material", () => {
  const groups = buildComparableGroups({
    ownRows: [own()],
    competitorRows: [
      competitor({ itemId: "1", name: "12 ft. x 14 ft. Gray Aluminum Louvered Pergola" }), // exact size, same core, any material
      competitor({ itemId: "2", name: "12 ft. x 14 ft. Gray Steel Louvered Pergola" }), // exact size + material
      competitor({ itemId: "3", name: "10 ft. x 20 ft. Gray Steel Louvered Pergola" }), // material only
    ],
  });
  const [group] = groups;
  assert.equal(group.tier, "exact");
  assert.deepEqual(group.competitorItemIds, ["2"]);
  assert.equal(group.groupKey, "Louvered Pergola × 12×14 ft × Steel");
});

test("comparable groups fall back to same-size when no material match exists", () => {
  const groups = buildComparableGroups({
    ownRows: [own({ name: "12 ft. x 14 ft. Brown Steel Louvered Pergola" })],
    competitorRows: [
      competitor({ itemId: "1", name: "12 ft. x 14 ft. Gray Aluminum Louvered Pergola" }), // same size, different material
      competitor({ itemId: "2", name: "10 ft. x 10 ft. Gray Aluminum Louvered Pergola" }),
    ],
  });
  const [group] = groups;
  assert.equal(group.tier, "size");
  assert.deepEqual(group.competitorItemIds, ["1"]);
  assert.equal(group.wide, true);
});

test("comparable groups report none when the core function has no competitors", () => {
  const groups = buildComparableGroups({
    ownRows: [own({ name: "12 ft. x 14 ft. Louvered Pergola" })],
    competitorRows: [competitor({ itemId: "1", name: "12 ft. x 14 ft. Pergola with Retractable Canopy" })], // not louvered
  });
  assert.equal(groups[0].tier, "none");
  assert.equal(groups[0].competitorCount, 0);
});

test("recommend flags price premium above the 1.1x threshold", () => {
  assert.equal(recommend({ competitorCount: 3, price: 2000, compMedianPrice: 1500, rating: 4, compMedianRating: 4.5, ownLowStarShare: null, compLowStarShare: null, reviewCount: 20, compMedianReviews: 10 }), "检查价格溢价");
});

test("recommend does not flag a price premium below the 10% threshold", () => {
  assert.equal(recommend({ competitorCount: 3, price: 1560, compMedianPrice: 1500, rating: 4.5, compMedianRating: 4.5, ownLowStarShare: null, compLowStarShare: null, reviewCount: 20, compMedianReviews: 10 }), "保持价格"); // +4% < +10%, rating tied
});

test("recommend prioritizes building social proof when the unit has no reviews", () => {
  assert.equal(recommend({ competitorCount: 3, price: 2000, compMedianPrice: 1500, rating: 0, compMedianRating: 4.5, ownLowStarShare: null, compLowStarShare: null, reviewCount: 0, compMedianReviews: 10 }), "建立社会证明");
});

test("recommend treats a rating gap within 0.1 as tied and gathers reviews", () => {
  assert.equal(recommend({ competitorCount: 3, price: 1400, compMedianPrice: 1500, rating: 4.42, compMedianRating: 4.5, ownLowStarShare: null, compLowStarShare: null, reviewCount: 2, compMedianReviews: 10 }), "增加评论积累"); // gap -0.08 < 0.1 tie
});

test("recommend flags review gap when rating is at/above median and reviews lag", () => {
  assert.equal(recommend({ competitorCount: 3, price: 1200, compMedianPrice: 1500, rating: 4.6, compMedianRating: 4.5, ownLowStarShare: null, compLowStarShare: null, reviewCount: 2, compMedianReviews: 10 }), "增加评论积累");
});

test("recommend flags assembly pain when own low-star share exceeds the group", () => {
  assert.equal(
    recommend({ competitorCount: 3, price: 1200, compMedianPrice: 1500, rating: 4, compMedianRating: 4.5, ownLowStarShare: 0.2, compLowStarShare: 0.05, ownTopThemes: ["Assembly & parts"], reviewCount: 8, compMedianReviews: 10 }),
    "改善安装体验",
  );
});

test("recommend never uses Other as the primary action theme", () => {
  assert.equal(
    recommend({ competitorCount: 3, price: 1200, compMedianPrice: 1500, rating: 4, compMedianRating: 4.5, ownLowStarShare: 0.2, compLowStarShare: 0.05, ownTopThemes: ["Other"], reviewCount: 8, compMedianReviews: 10 }),
    "强化产品卖点", // Other is not an actionable product theme
  );
});

test("recommend returns 保持价格 when within the competitive range", () => {
  assert.equal(recommend({ competitorCount: 3, price: 1400, compMedianPrice: 1500, rating: 4.5, compMedianRating: 4.5, ownLowStarShare: 0.05, compLowStarShare: 0.05, reviewCount: 8, compMedianReviews: 10 }), "保持价格");
});

test("buildBenchmark returns the three dashboard areas with only aggregated data", () => {
  const benchmark = buildBenchmark(
    {
      hdProducts: [own({ rating: 4.8, reviewCount: 40 })],
      competitor: { products: [competitor({ rating: 4.8, reviewCount: 50 })], reviews: [] },
      reviews: [],
    },
    "Pergola",
    "2026-08-13",
  );
  assert.ok(benchmark.coverage.ownListings >= 1);
  assert.ok(benchmark.coverage.competitorListings >= 1);
  assert.equal(benchmark.skus.length, 1);
  assert.equal(benchmark.skus[0].action, "保持价格"); // within competitive range
  assert.ok(Array.isArray(benchmark.priorityActions));
  assert.ok(benchmark.voc.rows);
  assert.ok(benchmark.voc.ownAboveMarket);
  assert.ok(benchmark.voc.ownBetter);
  assert.equal(JSON.stringify(benchmark).match(/reviewText|userName|userNickname|authorId|userLocation/), null);
});

test("buildVOC reports low-star sample counts and gates conclusions on sample size", () => {
  const voc = buildVOC({
    ownRows: [own()],
    competitorRows: [competitor({ itemId: "2000", name: "12 ft. x 14 ft. Gray Aluminum Louvered Pergola" })],
    ownReviews: [
      { itemId: "333087256", rating: 1, theme: "Assembly & parts" },
      { itemId: "333087256", rating: 2, theme: "Assembly & parts" },
      { itemId: "333087256", rating: 2, theme: "Assembly & parts" },
      { itemId: "333087256", rating: 1, theme: "Assembly & parts" },
      { itemId: "333087256", rating: 5, theme: "Other" },
    ],
    competitorReviews: [
      { itemId: "2000", rating: 1, theme: "Shipping & damage" },
      { itemId: "2000", rating: 2, theme: "Durability & material" },
      { itemId: "2000", rating: 1, theme: "Assembly & parts" },
      { itemId: "2000", rating: 5, theme: "Other" },
      { itemId: "2000", rating: 5, theme: "Other" },
      { itemId: "2000", rating: 5, theme: "Other" },
    ],
    category: "Pergola",
  });
  assert.equal(voc.ownLowStarCount, 4);
  assert.equal(voc.compLowStarCount, 3);
  assert.equal(voc.sampleInsufficient, true); // 4 < MIN_VOC_SAMPLE(10)
  assert.deepEqual(voc.ownAboveMarket, []);
  assert.deepEqual(voc.ownBetter, []);
  const assembly = voc.rows.find((row) => row.theme === "Assembly & parts");
  assert.equal(assembly.ownShare, 1); // all 4 own low-star reviews are Assembly
  assert.equal(assembly.compShare, 1 / 3); // 1 of 3 competitor low-star reviews
  assert.equal(assembly.gapPp, 66.7); // percentage points, 1 decimal
});

test("buildVOC draws above/below conclusions once the own sample is large enough", () => {
  const ownReviews = Array.from({ length: 12 }, (_, index) => ({
    itemId: "333087256", rating: index % 2 ? 1 : 2, theme: "Assembly & parts",
  }));
  const voc = buildVOC({
    ownRows: [own()],
    competitorRows: [competitor({ itemId: "2000", name: "12 ft. x 14 ft. Gray Aluminum Louvered Pergola" })],
    ownReviews,
    competitorReviews: [
      { itemId: "2000", rating: 1, theme: "Shipping & damage" },
      { itemId: "2000", rating: 2, theme: "Durability & material" },
      { itemId: "2000", rating: 1, theme: "Assembly & parts" },
      { itemId: "2000", rating: 5, theme: "Other" },
      { itemId: "2000", rating: 5, theme: "Other" },
      { itemId: "2000", rating: 5, theme: "Other" },
    ],
    category: "Pergola",
  });
  assert.equal(voc.sampleInsufficient, false);
  assert.ok(voc.ownAboveMarket.some((row) => row.theme === "Assembly & parts"));
});

test("aggregateUnits merges variant SKUs sharing one comparable group into a product unit", () => {
  const skus = [
    { groupKey: "Louvered Pergola × 10×13 ft × Aluminum", tier: "exact", wide: false, competitorCount: 5, mpn: "R-PQL-1013BN", price: 1697, rating: 5, reviewCount: 1, compMedianPrice: 1581.25, compMedianRating: 5, compMedianReviews: 0, ownLowStarShare: null, compLowStarShare: null, ownTopThemes: [], compTopThemes: [] },
    { groupKey: "Louvered Pergola × 10×13 ft × Aluminum", tier: "exact", wide: false, competitorCount: 5, mpn: "R-PQL-LED1013BN", price: 1767, rating: 5, reviewCount: 1, compMedianPrice: 1581.25, compMedianRating: 5, compMedianReviews: 0, ownLowStarShare: null, compLowStarShare: null, ownTopThemes: [], compTopThemes: [] },
    { groupKey: "Louvered Pergola × 10×13 ft × Aluminum", tier: "exact", wide: false, competitorCount: 5, mpn: "R-PKD-LED1013GY", price: 1635, rating: 0, reviewCount: 0, compMedianPrice: 1581.25, compMedianRating: 5, compMedianReviews: 0, ownLowStarShare: null, compLowStarShare: null, ownTopThemes: [], compTopThemes: [] },
    { groupKey: "Louvered Pergola × 12×14 ft × Steel", tier: "size", wide: true, competitorCount: 10, mpn: "R-PTE-1214BN", price: 1664, rating: 4.3333, reviewCount: 12, compMedianPrice: 2798.8, compMedianRating: 4.5, compMedianReviews: 1, ownLowStarShare: 0.1, compLowStarShare: 0.05, ownTopThemes: ["Durability & material"], compTopThemes: ["Assembly & parts"] },
  ];
  const units = aggregateUnits(skus);
  assert.equal(units.length, 2);
  const aluminum = units.find((unit) => unit.groupKey === "Louvered Pergola × 10×13 ft × Aluminum");
  assert.equal(aluminum.skuCount, 3);
  assert.deepEqual(aluminum.mpns, ["R-PQL-1013BN", "R-PQL-LED1013BN", "R-PKD-LED1013GY"]);
  assert.equal(aluminum.priceMin, 1635);
  assert.equal(aluminum.priceMax, 1767);
  assert.equal(aluminum.priceMedian, 1697);
  assert.equal(aluminum.reviewCount, 2); // sums member review counts
  assert.equal(aluminum.rating, 5); // weighted by review counts
  assert.equal(aluminum.compMedianPrice, 1581.25); // benchmark inherited from the group
  assert.equal(aluminum.action, "保持价格");
});

test("aggregateUnits keeps the benchmark and action of a single-SKU unit", () => {
  const skus = [
    { groupKey: "Louvered Pergola × 12×14 ft × Steel", tier: "size", wide: true, competitorCount: 10, mpn: "R-PTE-1214BN", price: 1664, rating: 4.3333, reviewCount: 12, compMedianPrice: 2798.8, compMedianRating: 4.5, compMedianReviews: 1, ownLowStarShare: 0.1, compLowStarShare: 0.05, ownTopThemes: ["Durability & material"], compTopThemes: ["Assembly & parts"] },
  ];
  const [unit] = aggregateUnits(skus);
  assert.equal(unit.skuCount, 1);
  assert.equal(unit.priceMedian, 1664);
  assert.equal(unit.reviewCount, 12);
  assert.equal(unit.rating, 4.3333);
});

test("buildBenchmark exposes aggregated product units and unit-level priority", () => {
  const benchmark = buildBenchmark(
    {
      hdProducts: [
        own({ rating: 4.8, reviewCount: 40 }),
        own({ itemId: "333088512", mpn: "R-PTE-LED1214BN", name: "Titan Series 12 ft. x 14 ft. Brown LED Aluminized Steel Louvered Pergola", salePrice: 1730, rating: 4.7, reviewCount: 7 }),
      ],
      competitor: { products: [competitor({ rating: 4.8, reviewCount: 50 })], reviews: [] },
      reviews: [],
    },
    "Pergola",
    "2026-08-13",
  );
  assert.equal(benchmark.units.length, 1); // two variant SKUs -> one unit
  assert.equal(benchmark.units[0].skuCount, 2);
  assert.equal(benchmark.coverage.ownUnits, 1);
  assert.equal(benchmark.coverage.ownListings, 2);
  assert.equal(benchmark.skus.length, 2);
  assert.ok(Array.isArray(benchmark.priorityActions));
  assert.equal(JSON.stringify(benchmark).match(/reviewText|userName|userNickname|authorId|userLocation/), null);
});

test("aggregateCompetitorUnits merges a brand's listings in one group into a single unit", () => {
  const units = aggregateCompetitorUnits([
    competitor({ itemId: "1", name: "12 ft. x 14 ft. Gray Aluminum Louvered Pergola", salePrice: 1800, reviewCount: 30 }),
    competitor({ itemId: "2", name: "12 ft. x 14 ft. Gray Aluminum Louvered Pergola with LED", salePrice: 2000, reviewCount: 10 }),
    competitor({ itemId: "3", name: "10 ft. x 10 ft. Gray Aluminum Louvered Pergola", salePrice: 1200, reviewCount: 5 }),
  ]);
  assert.equal(units.length, 2); // two (brand, group) pairs
  const twelve = units.find((unit) => unit.sizeW === 12);
  assert.equal(twelve.listingCount, 2);
  assert.equal(twelve.priceMedian, 1900);
  assert.equal(twelve.reviewCount, 40);
  assert.equal(twelve.rating, 4.8); // review-weighted across both listings
});

test("buildCoverage scopes to the current category and reports match quality", () => {
  const coverage = buildCoverage({
    ownRows: [own()],
    competitorRows: [competitor({ itemId: "1", name: "12 ft. x 14 ft. Gray Aluminum Louvered Pergola" })],
    competitorUnits: [aggregateCompetitorUnits([competitor({ itemId: "1", name: "12 ft. x 14 ft. Gray Aluminum Louvered Pergola" })])[0]],
    skus: [],
    units: [{ tier: "exact" }, { tier: "size" }, { tier: "tolerance" }],
  });
  assert.equal(coverage.category, "Pergola");
  assert.equal(coverage.ownListings, 1);
  assert.equal(coverage.matchExact, 1);
  assert.equal(coverage.matchApproximate, 2);
  assert.equal(coverage.matchNone, 0);
});

test("snapshot carries marketBenchmark and remains PII-free", () => {
  assert.ok(SNAPSHOT.marketBenchmark, "marketBenchmark present");
  assert.ok(SNAPSHOT.marketBenchmark.units.length > 0);
  assert.equal(JSON.stringify(SNAPSHOT.marketBenchmark).match(/reviewText|userName|userNickname|authorId|userLocation/), null);
});
