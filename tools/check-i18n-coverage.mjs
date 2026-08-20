import fs from "node:fs";
import { catalogPath, collectUserFacingSources } from "./i18n-static-sources.mjs";

const sources = collectUserFacingSources();
const file = catalogPath("en");
const catalog = JSON.parse(fs.readFileSync(file, "utf8"));
const missing = [];
const untranslatedTargets = [];

for (const [source, files] of sources) {
  const translated = catalog[source];
  if (typeof translated !== "string" || !translated.trim() || translated === source) {
    missing.push({ source, files: [...files] });
  } else if (/[А-Яа-яЁё]/.test(translated)) {
    untranslatedTargets.push({ source, translated, files: [...files] });
  }
}

if (missing.length) {
  console.error(`i18n coverage: ${missing.length} of ${sources.size} Russian strings are missing`);
  for (const item of missing.slice(0, 80)) {
    console.error(`- ${JSON.stringify(item.source)} (${item.files.join(", ")})`);
  }
  if (missing.length > 80) console.error(`... and ${missing.length - 80} more`);
  process.exit(1);
}

if (untranslatedTargets.length) {
  console.error(`i18n coverage: ${untranslatedTargets.length} English catalog targets still contain Cyrillic`);
  for (const item of untranslatedTargets.slice(0, 80)) {
    console.error(`- ${JSON.stringify(item.source)} -> ${JSON.stringify(item.translated)} (${item.files.join(", ")})`);
  }
  if (untranslatedTargets.length > 80) console.error(`... and ${untranslatedTargets.length - 80} more`);
  process.exit(1);
}

console.log(`i18n coverage: ${sources.size} Russian strings, English catalog complete`);
