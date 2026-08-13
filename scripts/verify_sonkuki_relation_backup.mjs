import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "/Users/wyl/sonkuki/outputs/sonkuki_nocodb_relation_backup/sonkuki_nocodb_relation_backup_v2.xlsx";
const outputDir = path.dirname(inputPath);
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const summary = await workbook.inspect({ kind: "workbook,sheet,table", maxChars: 12000, tableMaxRows: 3, tableMaxCols: 12 });
console.log(summary.ndjson);
const renderRanges = {
  SCD_Raw_Backup: "A1:K20",
  Page_Summary: "A1:H30",
  Query_Summary_Backup: "A1:H30",
  Migration_Notes: "A1:B8",
};
for (const [sheetName, range] of Object.entries(renderRanges)) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(outputDir, `${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
}
console.log("visual verification complete");
