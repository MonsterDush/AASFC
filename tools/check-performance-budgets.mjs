import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";


const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const frontendRoot = path.join(repoRoot, "frontend");
const budgets = JSON.parse(fs.readFileSync(path.join(repoRoot, "tools/performance-budgets.json"), "utf8"));
const extensions = new Map([
  [".js", budgets.assets.maxJavaScriptBytes],
  [".mjs", budgets.assets.maxJavaScriptBytes],
  [".css", budgets.assets.maxStylesheetBytes],
  [".html", budgets.assets.maxHtmlBytes],
]);


function walk(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) return walk(candidate);
    return [candidate];
  });
}


const measured = [];
for (const filePath of walk(frontendRoot)) {
  const maximum = extensions.get(path.extname(filePath));
  if (!maximum) continue;
  const bytes = fs.statSync(filePath).size;
  const relative = path.relative(repoRoot, filePath);
  assert.ok(bytes <= maximum, `${relative}: ${bytes} bytes exceeds the ${maximum}-byte source budget`);
  measured.push({ file: relative, bytes, maximum });
}

const largest = measured.sort((left, right) => right.bytes - left.bytes).slice(0, 8);
console.log(JSON.stringify({ ok: true, checked: measured.length, largest }, null, 2));
