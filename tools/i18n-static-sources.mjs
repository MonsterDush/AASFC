import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const REPO_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const FRONTEND_DIR = path.join(REPO_DIR, "frontend");
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
  const source = String(code || "");

  function decodeLiteral(value) {
    return value
      .replace(/\\\r?\n/g, "")
      .replace(/\\[nrtbfv]/g, " ")
      .replace(/\\([\\'"`$])/g, "$1");
  }

  function addLiteralSource(value) {
    const decoded = decodeLiteral(value);
    const looksLikeMarkup =
      /[<>]/.test(decoded) ||
      /\b(?:alt|aria-label|class|data-[\w-]+|id|name|placeholder|title|type|value)\s*=/.test(
        decoded,
      );
    if (!looksLikeMarkup) {
      addSource(target, decoded, file);
      return;
    }
    for (const attribute of decoded.matchAll(ATTRIBUTE_RE)) {
      addSource(target, attribute[1], file);
    }
    for (const attribute of decoded.matchAll(
      /(?:placeholder|title|aria-label|alt)\s*=\s*["']([^"']*)$/g,
    )) {
      addSource(target, attribute[1], file);
    }
    const textChunks = decoded
      .replace(ATTRIBUTE_RE, " ")
      .replace(HTML_TOKEN_RE, "\n")
      .replace(/<[^>]*$/g, "\n")
      .replace(/^[^<>\n]*>/, "\n")
      .split("\n");
    for (const chunk of textChunks) {
      if (
        /\b(?:alt|aria-label|class|data-[\w-]+|id|name|placeholder|title|type|value)\s*=/.test(
          chunk,
        )
      )
        continue;
      addSource(target, chunk, file);
    }
  }

  function readQuoted(start, quote) {
    let cursor = start + 1;
    let value = "";
    while (cursor < source.length) {
      const character = source[cursor];
      if (character === "\\") {
        value += source.slice(cursor, cursor + 2);
        cursor += 2;
        continue;
      }
      if (character === quote) {
        addLiteralSource(value);
        return cursor + 1;
      }
      value += character;
      cursor += 1;
    }
    return cursor;
  }

  function skipComment(start) {
    if (source[start + 1] === "/") {
      const end = source.indexOf("\n", start + 2);
      return end === -1 ? source.length : end + 1;
    }
    if (source[start + 1] === "*") {
      const end = source.indexOf("*/", start + 2);
      return end === -1 ? source.length : end + 2;
    }
    return start;
  }

  function startsRegularExpression(start) {
    let cursor = start - 1;
    while (cursor >= 0 && /\s/.test(source[cursor])) cursor -= 1;
    if (cursor < 0) return true;
    if (/[([{,:;=!?&|+*%^~<>-]/.test(source[cursor])) return true;
    const prefix = source.slice(0, cursor + 1);
    const keyword = prefix.match(/([A-Za-z_$][\w$]*)$/)?.[1] || "";
    return [
      "await",
      "case",
      "delete",
      "do",
      "else",
      "in",
      "instanceof",
      "new",
      "of",
      "return",
      "throw",
      "typeof",
      "void",
      "yield",
    ].includes(keyword);
  }

  function skipRegularExpression(start) {
    let cursor = start + 1;
    let inCharacterClass = false;
    while (cursor < source.length) {
      const character = source[cursor];
      if (character === "\\") {
        cursor += 2;
        continue;
      }
      if (character === "[") inCharacterClass = true;
      else if (character === "]") inCharacterClass = false;
      else if (character === "/" && !inCharacterClass) {
        cursor += 1;
        while (/[A-Za-z]/.test(source[cursor] || "")) cursor += 1;
        return cursor;
      }
      if (character === "\n" || character === "\r") return start + 1;
      cursor += 1;
    }
    return start + 1;
  }

  function readTemplate(start) {
    let cursor = start + 1;
    let value = "";
    while (cursor < source.length) {
      const character = source[cursor];
      if (character === "\\") {
        value += source.slice(cursor, cursor + 2);
        cursor += 2;
        continue;
      }
      if (character === "`") {
        addLiteralSource(value);
        return cursor + 1;
      }
      if (character === "$" && source[cursor + 1] === "{") {
        addLiteralSource(value);
        value = "";
        cursor = readExpression(cursor + 2);
        continue;
      }
      value += character;
      cursor += 1;
    }
    return cursor;
  }

  function readExpression(start) {
    let cursor = start;
    let depth = 1;
    while (cursor < source.length && depth > 0) {
      const character = source[cursor];
      if (character === "/" && ["/", "*"].includes(source[cursor + 1])) {
        cursor = skipComment(cursor);
        continue;
      }
      if (character === "/" && startsRegularExpression(cursor)) {
        cursor = skipRegularExpression(cursor);
        continue;
      }
      if (character === "'" || character === '"') {
        cursor = readQuoted(cursor, character);
        continue;
      }
      if (character === "`") {
        cursor = readTemplate(cursor);
        continue;
      }
      if (character === "{") depth += 1;
      else if (character === "}") depth -= 1;
      cursor += 1;
    }
    return cursor;
  }

  let cursor = 0;
  while (cursor < source.length) {
    const character = source[cursor];
    if (character === "/" && ["/", "*"].includes(source[cursor + 1])) {
      cursor = skipComment(cursor);
      continue;
    }
    if (character === "/" && startsRegularExpression(cursor)) {
      cursor = skipRegularExpression(cursor);
      continue;
    }
    if (character === "'" || character === '"') {
      cursor = readQuoted(cursor, character);
      continue;
    }
    if (character === "`") {
      cursor = readTemplate(cursor);
      continue;
    }
    cursor += 1;
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
  const result = spawnSync(
    process.env.PYTHON || "python3",
    [path.join(REPO_DIR, "tools", "list_python_i18n_sources.py")],
    { cwd: REPO_DIR, encoding: "utf8", maxBuffer: 16 * 1024 * 1024 },
  );
  if (result.status !== 0) {
    throw new Error(
      result.stderr || "Failed to collect Python localization sources",
    );
  }
  for (const [value, file] of JSON.parse(result.stdout)) {
    addSource(sources, value, file);
  }
  return sources;
}

export function catalogPath(locale = "en") {
  return path.join(FRONTEND_DIR, "locales", `${locale}.json`);
}
