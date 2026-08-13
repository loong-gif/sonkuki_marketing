import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const inputPath = "outputs/homedepot_reviews_final_2026-08-12.json";
const manifestPath = "outputs/homedepot_reviews_apify_manifest_2026-08-12.json";
const outputDir = "outputs";
const csvPath = `${outputDir}/homedepot_reviews_complete_table_2026-08-12.csv`;
const xlsxPath = `${outputDir}/homedepot_reviews_complete_table_2026-08-12.xlsx`;
const previewPath = `${outputDir}/homedepot_reviews_complete_table_preview_2026-08-12.png`;

const headers = [
  "UID",
  "itemId",
  "productId",
  "productUrl",
  "mpn",
  "productName",
  "originalProductName",
  "currentPage",
  "lastPage",
  "totalResults",
  "title",
  "reviewText",
  "rating",
  "submissionTime",
  "userNickname",
  "authorId",
  "totalPositiveFeedbackCount",
  "totalNegativeFeedbackCount",
  "isRecommended",
  "isVerifiedPurchaser",
  "statusCode",
  "statusMessage",
  "sortBy",
  "searchTerm",
  "starRatings",
  "userLocation",
  "photos",
  "badges",
  "badgesOrder",
  "contextDataValues",
  "secondaryRatings",
  "includes",
];

const jsonCell = (value) => {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
};

const csvCell = (value) => {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};

const columnName = (index) => {
  let n = index + 1;
  let result = "";
  while (n > 0) {
    const remainder = (n - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    n = Math.floor((n - 1) / 26);
  }
  return result;
};

const input = JSON.parse(await fs.readFile(inputPath, "utf8"));
const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
const productByItemId = new Map(
  manifest.products.map((product) => [String(product.itemId), product]),
);

const seen = new Set();
const reviews = input
  .filter((record) => record.statusMessage === "FOUND" && record.id)
  .filter((record) => {
    const key = `${record.itemId}::${record.id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  })
  .sort((a, b) => {
    const itemCompare = String(a.itemId).localeCompare(String(b.itemId), undefined, {
      numeric: true,
    });
    if (itemCompare !== 0) return itemCompare;
    const pageCompare = (a.currentPage ?? 0) - (b.currentPage ?? 0);
    if (pageCompare !== 0) return pageCompare;
    return String(a.id).localeCompare(String(b.id), undefined, { numeric: true });
  });

const rows = reviews.map((record) => {
  const product = productByItemId.get(String(record.itemId)) ?? {};
  return [
    String(record.id),
    String(record.itemId ?? ""),
    String(record.productId ?? ""),
    product.url ?? "",
    product.mpn ?? "",
    product.name ?? "",
    record.originalProductName ?? "",
    record.currentPage ?? "",
    record.lastPage ?? "",
    record.totalResults ?? "",
    record.title ?? "",
    record.reviewText ?? "",
    record.rating ?? "",
    record.submissionTime ?? "",
    record.userNickname ?? "",
    record.authorId ?? "",
    record.totalPositiveFeedbackCount ?? "",
    record.totalNegativeFeedbackCount ?? "",
    record.isRecommended ?? "",
    record.isVerifiedPurchaser ?? "",
    record.statusCode ?? "",
    record.statusMessage ?? "",
    record.sortBy ?? "",
    record.searchTerm ?? "",
    record.starRatings ?? "",
    jsonCell(record.userLocation),
    jsonCell(record.photos),
    jsonCell(record.badges),
    jsonCell(record.badgesOrder),
    jsonCell(record.contextDataValues),
    jsonCell(record.secondaryRatings),
    jsonCell(record.includes),
  ];
});

const csvText = [headers, ...rows]
  .map((row) => row.map(csvCell).join(","))
  .join("\n") + "\n";
await fs.writeFile(csvPath, `\ufeff${csvText}`, "utf8");

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Reviews");
const allValues = [headers, ...rows];
const rowCount = allValues.length;
const colCount = headers.length;
const usedRange = sheet.getRangeByIndexes(0, 0, rowCount, colCount);
usedRange.values = allValues;

const lastColumn = columnName(colCount - 1);
const lastRow = rowCount;
const table = sheet.tables.add(`A1:${lastColumn}${lastRow}`, true, "HomeDepotReviewsTable");
table.showFilterButton = true;
table.style = "TableStyleMedium2";

sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);
sheet.freezePanes.freezeColumns(1);
sheet.getRange(`A1:${lastColumn}1`).format = {
  fill: "#1F4E78",
  font: { bold: true, color: "#FFFFFF" },
  wrapText: true,
};
sheet.getRange(`A1:${lastColumn}1`).format.rowHeight = 30;

const setColumnWidth = (column, width) => {
  sheet.getRange(`${column}1:${column}${lastRow}`).format.columnWidth = width;
};
setColumnWidth("A", 16);
setColumnWidth("B", 14);
setColumnWidth("C", 14);
setColumnWidth("D", 48);
setColumnWidth("E", 18);
setColumnWidth("F", 36);
setColumnWidth("G", 36);
setColumnWidth("H", 12);
setColumnWidth("I", 12);
setColumnWidth("J", 14);
setColumnWidth("K", 30);
setColumnWidth("L", 64);
setColumnWidth("M", 10);
setColumnWidth("N", 24);
setColumnWidth("O", 20);
setColumnWidth("P", 28);
setColumnWidth("Q", 16);
setColumnWidth("R", 16);
setColumnWidth("S", 14);
setColumnWidth("T", 18);
setColumnWidth("U", 12);
setColumnWidth("V", 14);
setColumnWidth("W", 16);
setColumnWidth("X", 16);
setColumnWidth("Y", 14);
setColumnWidth("Z", 24);
setColumnWidth("AA", 32);
setColumnWidth("AB", 32);
setColumnWidth("AC", 24);
setColumnWidth("AD", 32);
setColumnWidth("AE", 32);
setColumnWidth("AF", 48);

sheet.getRange(`H2:J${lastRow}`).format.numberFormat = "0";
sheet.getRange(`M2:M${lastRow}`).format.numberFormat = "0.0";
sheet.getRange(`Q2:R${lastRow}`).format.numberFormat = "0";
sheet.getRange(`U2:U${lastRow}`).format.numberFormat = "0";
sheet.getRange(`S2:T${lastRow}`).format.horizontalAlignment = "center";
sheet.getRange(`A2:A${lastRow}`).format.font = { bold: true, color: "#1F4E78" };

const inspect = await workbook.inspect({
  kind: "table",
  sheetId: "Reviews",
  range: "A1:L6",
  include: "values,formulas",
  tableMaxRows: 6,
  tableMaxCols: 12,
  tableMaxCellChars: 100,
});
console.log(inspect.ndjson);

const preview = await workbook.render({
  sheetName: "Reviews",
  range: "A1:L10",
  scale: 1,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(xlsxPath);

console.log(JSON.stringify({
  sourceRecords: input.length,
  exportedReviewRows: reviews.length,
  columns: headers.length,
  csvPath,
  xlsxPath,
  previewPath,
}, null, 2));
