import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const outputDir = path.join(repoRoot, "frontend", "assets", "error-tracking");

await fs.rm(outputDir, { recursive: true, force: true });
await fs.mkdir(outputDir, { recursive: true });
await build({
  entryPoints: [path.join(repoRoot, "frontend", "error-tracking-entry.js")],
  outfile: path.join(outputDir, "index.js"),
  bundle: true,
  format: "iife",
  platform: "browser",
  target: ["es2022"],
  minify: true,
  sourcemap: "external",
  sourcesContent: true,
  legalComments: "none",
  charset: "utf8",
});

const mapPath = path.join(outputDir, "index.js.map");
const sourceMap = JSON.parse(await fs.readFile(mapPath, "utf8"));
if (
  !Array.isArray(sourceMap.sourcesContent) ||
  sourceMap.sourcesContent.length === 0
) {
  throw new Error("error tracking source map must contain sourcesContent");
}
console.log(
  `browser error tracking bundle: ${path.relative(repoRoot, outputDir)}`,
);
