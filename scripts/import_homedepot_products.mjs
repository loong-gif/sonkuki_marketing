#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const ROOT = resolve(new URL("..", import.meta.url).pathname);
const TABLE_ID = "mnttfzrhu6gp6s0";
const args = process.argv.slice(2);
const apply = args.includes("--apply");
const inputIndex = args.indexOf("--input");
const inputPath = inputIndex >= 0 ? resolve(args[inputIndex + 1] || "") : "";

if (!inputPath) throw new Error("Usage: node scripts/import_homedepot_products.mjs --input <tsv-file> [--apply]");

const credentials = Object.fromEntries(
  (await readFile(resolve(ROOT, "credentials.txt"), "utf8"))
    .split(/\r?\n/)
    .filter((line) => line.includes(":"))
    .map((line) => {
      const index = line.indexOf(":");
      return [line.slice(0, index).trim(), line.slice(index + 1).trim()];
    }),
);
const api = credentials["NocoDB URL"];
const token = credentials["NocoDB PAT"];
if (!api || !token) throw new Error("NocoDB credentials are incomplete");

const clean = (value) => String(value ?? "").trim();
const normalizePrice = (value) => {
  const normalized = clean(value).replace(/[$,]/g, "");
  return /^\d+(?:\.\d+)?$/.test(normalized) ? normalized : "";
};
const extractUrl = (value) => {
  const raw = clean(value);
  const markdown = raw.match(/\]\((https?:\/\/[^)]+)\)/);
  return markdown ? markdown[1] : raw;
};
const titleFromUrl = (url) => {
  const match = clean(url).match(/\/p\/([^/]+)\/\d{6,}(?:[?#]|$)/i);
  return match ? decodeURIComponent(match[1]).replace(/-/g, " ") : "";
};
const parseTsv = (text) => {
  const [header, ...lines] = text.split(/\r?\n/).filter((line) => line.trim());
  const keys = header.split("\t").map(clean);
  return lines.map((line) => {
    const cells = line.split("\t");
    return Object.fromEntries(keys.map((key, index) => [key, clean(cells[index])]));
  }).filter((row) => row.homedepot_sku && row.itemid);
};
const sourceRows = parseTsv(await readFile(inputPath, "utf8"));
const seen = new Set();
for (const row of sourceRows) {
  const mpn = row.homedepot_sku.toLowerCase();
  const url = extractUrl(row.hd_url);
  if (seen.has(mpn)) throw new Error(`Duplicate supplied MPN: ${row.homedepot_sku}`);
  if (!/^\d{6,}$/.test(row.itemid)) throw new Error(`Invalid Item ID for ${row.homedepot_sku}`);
  if (!url.includes(`/${row.itemid}`)) throw new Error(`URL and Item ID disagree for ${row.homedepot_sku}`);
  seen.add(mpn);
}

const headers = { accept: "application/json", "content-type": "application/json", "xc-token": token };
const request = async (method, path, payload) => {
  const response = await fetch(`${api}${path}`, { method, headers, body: payload ? JSON.stringify(payload) : undefined });
  if (!response.ok) throw new Error(`NocoDB ${method} ${path}: ${response.status}`);
  return response.json().catch(() => ({}));
};
const existing = (await request("GET", `/api/v2/tables/${TABLE_ID}/records?limit=1000&fields=Id,mpn,name,offers%2Fprice,originalPrice,url`)).list || [];
const existingByMpn = new Map(existing.map((row) => [clean(row.mpn).toLowerCase(), row]).filter(([mpn]) => mpn));
const toPayload = (row) => ({
  mpn: row.homedepot_sku,
  name: row.hd_title || titleFromUrl(extractUrl(row.hd_url)),
  "offers/price": normalizePrice(row.homedepot_price_discount),
  originalPrice: normalizePrice(row.homedepot_price_original),
  url: extractUrl(row.hd_url),
});
const creates = sourceRows.filter((row) => !existingByMpn.has(row.homedepot_sku.toLowerCase())).map(toPayload);
const updates = sourceRows.filter((row) => existingByMpn.has(row.homedepot_sku.toLowerCase())).map((row) => ({ Id: existingByMpn.get(row.homedepot_sku.toLowerCase()).Id, ...toPayload(row) }));

console.log(JSON.stringify({ mode: apply ? "apply" : "dry-run", supplied: sourceRows.length, create: creates.length, update: updates.length, createMpns: creates.map((row) => row.mpn), updateMpns: updates.map((row) => row.mpn) }, null, 2));
if (!apply) process.exit(0);

if (creates.length) await request("POST", `/api/v2/tables/${TABLE_ID}/records`, creates);
if (updates.length) await request("PATCH", `/api/v2/tables/${TABLE_ID}/records`, updates);

const refreshed = (await request("GET", `/api/v2/tables/${TABLE_ID}/records?limit=1000&fields=Id,mpn,url`)).list || [];
const refreshedByMpn = new Map(refreshed.map((row) => [clean(row.mpn).toLowerCase(), row]));
const mismatches = sourceRows.filter((row) => {
  const current = refreshedByMpn.get(row.homedepot_sku.toLowerCase());
  return !current || !clean(current.url).includes(`/${row.itemid}`);
});
if (mismatches.length) throw new Error(`Post-write validation failed for: ${mismatches.map((row) => row.homedepot_sku).join(", ")}`);
console.log(JSON.stringify({ status: "applied", validated: sourceRows.length }, null, 2));
