import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const REPO_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const FRONTEND_DIR = path.join(REPO_DIR, "frontend");
const BACKEND_APP_DIR = path.join(REPO_DIR, "backend", "app");
const CYRILLIC_RE = /[А-Яа-яЁё]/;
const ATTRIBUTE_RE =
  /(?:placeholder|title|aria-label|alt)\s*=\s*["']([^"']+)["']/g;
const HTML_TOKEN_RE =
  /<!--[\s\S]*?-->|<![^>]*>|<\s*(\/?)\s*([A-Za-z][\w:-]*)\b[^>]*>/g;
const RAW_TEXT_TAGS = new Set(["script", "style"]);

function normalizeSource(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}

function addSource(target, value, file) {
  const source = normalizeSource(value);
  if (!source || !CYRILLIC_RE.test(source)) return;
  if (!target.has(source)) target.set(source, new Set());
  target.get(source).add(file);
}

function collectHtmlTextAndAttributeSources(target, raw, file) {
  const rawTextStack = [];
  let cursor = 0;
  for (const match of raw.matchAll(HTML_TOKEN_RE)) {
    if (rawTextStack.length === 0) {
      addSource(target, raw.slice(cursor, match.index), file);
    }
    const closing = match[1] === "/";
    const tagName = String(match[2] || "").toLowerCase();
    if (rawTextStack.length > 0) {
      if (closing && tagName === rawTextStack.at(-1)) rawTextStack.pop();
    } else if (RAW_TEXT_TAGS.has(tagName)) {
      if (!closing && !/\/\s*>$/.test(match[0])) rawTextStack.push(tagName);
    } else if (!closing) {
      for (const attribute of match[0].matchAll(ATTRIBUTE_RE)) {
        addSource(target, attribute[1], file);
      }
    }
    cursor = match.index + match[0].length;
  }
  if (rawTextStack.length === 0) addSource(target, raw.slice(cursor), file);
}

export function collectStaticHtmlSources() {
  const sources = new Map();
  const files = fs
    .readdirSync(FRONTEND_DIR)
    .filter((file) => file.endsWith(".html"))
    .sort();
  for (const file of files) {
    const raw = fs.readFileSync(path.join(FRONTEND_DIR, file), "utf8");
    collectHtmlTextAndAttributeSources(sources, raw, file);
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

function collectInlineScriptSources(target, raw, file) {
  let scriptStart = null;
  for (const match of raw.matchAll(HTML_TOKEN_RE)) {
    const closing = match[1] === "/";
    const tagName = String(match[2] || "").toLowerCase();
    if (scriptStart === null) {
      if (tagName === "script" && !closing && !/\/\s*>$/.test(match[0])) {
        scriptStart = match.index + match[0].length;
      }
      continue;
    }
    if (tagName === "script" && closing) {
      addCodeLiteralSources(target, raw.slice(scriptStart, match.index), file);
      scriptStart = null;
    }
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
      addCodeLiteralSources(
        sources,
        fs.readFileSync(filePath, "utf8"),
        relative,
      );
      continue;
    }
    if (!filePath.endsWith(".html")) continue;
    const html = fs.readFileSync(filePath, "utf8");
    collectInlineScriptSources(sources, html, relative);
  }
  return sources;
}

export function collectUserFacingSources() {
  const sources = collectFrontendSources();
  for (const filePath of walk(BACKEND_APP_DIR)
    .filter((file) => file.endsWith(".py"))
    .sort()) {
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
