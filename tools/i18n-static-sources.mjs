import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const REPO_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const FRONTEND_DIR = path.join(REPO_DIR, "frontend");
const BACKEND_APP_DIR = path.join(REPO_DIR, "backend", "app");
const CYRILLIC_RE = /[А-Яа-яЁё]/;
const ATTRIBUTE_RE = /(?:placeholder|title|aria-label|alt)\s*=\s*["']([^"']+)["']/g;
const TEXT_RE = />([^<>]+)</g;
const SCRIPT_RE = /<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi;

function normalizeSource(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function addSource(target, value, file) {
  const source = normalizeSource(value);
  if (!source || !CYRILLIC_RE.test(source)) return;
  if (!target.has(source)) target.set(source, new Set());
  target.get(source).add(file);
}

export function collectStaticHtmlSources() {
  const sources = new Map();
  const files = fs.readdirSync(FRONTEND_DIR).filter((file) => file.endsWith(".html")).sort();
  for (const file of files) {
    const raw = fs.readFileSync(path.join(FRONTEND_DIR, file), "utf8");
    const html = raw.replace(/<script[\s\S]*?<\/script>/gi, "").replace(/<style[\s\S]*?<\/style>/gi, "");
    for (const match of html.matchAll(TEXT_RE)) addSource(sources, match[1], file);
    for (const match of html.matchAll(ATTRIBUTE_RE)) addSource(sources, match[1], file);
  }
  return sources;
}

function addCodeLiteralSources(target, code, file) {
  for (const chunk of String(code || "").split(/["'`<>{}\n\r;]/)) {
    const firstCyrillic = chunk.search(CYRILLIC_RE);
    if (firstCyrillic < 0) continue;
    const source = chunk
      .slice(firstCyrillic)
      .replace(/\\[nrt]/g, " ")
      .replace(/\$\s*$/, "")
      .replace(/[\s),\]]+$/, "")
      .trim();
    addSource(target, source, file);
  }
}

function addPythonLiteralSources(target, code, file) {
  const literalRe = /(?:^|[^\w])(?:[rubf]{0,3})(["'])([^\n]*?)\1/gim;
  for (const match of String(code || "").matchAll(literalRe)) {
    addCodeLiteralSources(target, match[2], file);
  }
}

function walk(directory) {
  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...walk(target));
    else files.push(target);
  }
  return files;
}

export function collectFrontendSources() {
  const sources = collectStaticHtmlSources();
  const files = walk(FRONTEND_DIR).sort();
  for (const filePath of files) {
    const relative = path.relative(FRONTEND_DIR, filePath);
    if (filePath.endsWith(".js")) {
      if (["i18n.js", "i18n-bootstrap.js"].includes(relative)) continue;
      addCodeLiteralSources(sources, fs.readFileSync(filePath, "utf8"), relative);
      continue;
    }
    if (!filePath.endsWith(".html")) continue;
    const html = fs.readFileSync(filePath, "utf8");
    for (const match of html.matchAll(SCRIPT_RE)) addCodeLiteralSources(sources, match[1], relative);
  }
  return sources;
}

export function collectUserFacingSources() {
  const sources = collectFrontendSources();
  for (const filePath of walk(BACKEND_APP_DIR).filter((file) => file.endsWith(".py")).sort()) {
    addPythonLiteralSources(
      sources,
      fs.readFileSync(filePath, "utf8"),
      path.relative(REPO_DIR, filePath),
    );
  }
  return sources;
}

export function catalogPath(locale = "en") {
  return path.join(FRONTEND_DIR, "locales", `${locale}.json`);
}
