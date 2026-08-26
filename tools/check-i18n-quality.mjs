import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { collectUserFacingSources } from "./i18n-static-sources.mjs";

const REPO_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const catalog = JSON.parse(
  fs.readFileSync(path.join(REPO_DIR, "frontend/locales/en.json"), "utf8"),
);
const curated = JSON.parse(
  fs.readFileSync(
    path.join(REPO_DIR, "tools/i18n-en-curated-overrides.json"),
    "utf8",
  ),
);
const errors = [];
const activeSources = new Set(collectUserFacingSources().keys());
let activeCuratedCount = 0;

for (const [source, expected] of Object.entries(curated)) {
  if (!activeSources.has(source)) continue;
  activeCuratedCount += 1;
  if (catalog[source] !== expected) {
    errors.push(
      `${JSON.stringify(source)} must be ${JSON.stringify(expected)}, got ${JSON.stringify(catalog[source])}`,
    );
  }
}

const semanticRules = [
  {
    source: /ставк/i,
    target: /\bbet\b/i,
    message: "pay rates must not be translated as bets",
  },
  {
    source: /процент/i,
    target: /\binterest(?: rate)?s?\b/i,
    message: "pay percentages must not be translated as financial interest",
  },
  {
    source: /фикс/i,
    target: /\b(?:shift )?fix\b/i,
    message: "fixed pay must not use the noun 'fix'",
  },
  {
    source: /истори/i,
    target: /\bstory\b/i,
    message: "history must not be translated as story",
  },
  {
    source: /шаблон/i,
    target: /\bpatterns?\b/i,
    message: "product templates must not be translated as patterns",
  },
  {
    source: /должност/i,
    target: /\b(?:posts?|appoint(?:ed|ing|ment)?)\b/i,
    message: "staff roles and role assignment must use product terminology",
  },
  {
    source: /начисл/i,
    target: /\bcharges?\b/i,
    message: "pay accruals must not be translated as charges",
  },
  {
    source: /расход/i,
    target: /^(?!.*\bexpenses?\b).*\bcosts?\b/i,
    message: "expenses must not be translated as generic costs",
  },
  {
    source: /норматив/i,
    target: /\b(?:regulations?|norms?)\b/i,
    message: "business targets must not be translated as regulations",
  },
  {
    source: /экономик\w* дня/i,
    target: /\b(?:the )?economy of the day\b/i,
    message: "the daily performance product area must use its canonical name",
  },
  {
    source: /ФОТ/,
    target: /\b(?:POT|PHOTO|FOT|FOOT)\b/i,
    message: "ФОТ must use the canonical Payroll term",
  },
  {
    source: /мастер/i,
    target: /\bmaster\b/i,
    message: "the setup flow must be called a setup wizard",
  },
  {
    source: /завед/i,
    target: /\bhouses?\b/i,
    message: "venues must not be translated as houses",
  },
  {
    source: /привяз/i,
    target: /\b(?:binding|tie|tied)\b/i,
    message: "account linking must use link/linked terminology",
  },
  {
    source: /сотрудник/i,
    target: /\b(?:staffers?|officers?)\b/i,
    message: "employees must not be described as staffers or officers",
  },
  {
    source: /сохран/i,
    target: /\b(?:preservation|maintain(?:ed|ing)?|retain(?:ed|ing)?)\b/i,
    message: "save actions must use save/saved wording",
  },
  {
    source: /^Не удалось/,
    target:
      /^(?:I |We |It was not possible|Failure to|Unable to|Could not|Couldn't|Couldn’t)/i,
    message: "failure messages must be concise and impersonal",
  },
  {
    source: /^Не удалось загрузить/,
    target: /\b(?:download|upload)\b/i,
    message: "loading application data must not be described as file transfer",
  },
  {
    source: /доступност/i,
    target: /\baccessibil/i,
    message: "shift availability must not be translated as accessibility",
  },
  {
    source: /график/i,
    target: /\bgraphics?\b/i,
    message: "schedules and charts must not be translated as graphics",
  },
  {
    source: /факт/i,
    target: /\bfacts?\b/i,
    message: "actual values must not be translated as facts",
  },
  {
    source: /проводк/i,
    target: /\bwir(?:e|ing)\b/i,
    message: "ledger entries must not be translated as wiring",
  },
  {
    source: /сброс/i,
    target: /\bdrop(?:ped|ping)?\b/i,
    message: "reset actions must not be translated as drop",
  },
  {
    source: /^(?:Загрузка|Загружаем)/,
    target: /\b(?:download|upload)(?:ed|ing)?\b/i,
    message: "loading application state must use loading terminology",
  },
  {
    source: /^(?:Сохран|Сохраня)/i,
    target: /\bpreserv(?:e|ed|es|ing|ation)\b/i,
    message: "save actions must not be described as preservation",
  },
  {
    source: /призна/i,
    target: /\bconfess/i,
    message: "recognized expenses must not be described as confession",
  },
  {
    source: /сработ/i,
    target: /\bworked\b/i,
    message: "applied rules and tiers must not be described as worked",
  },
  {
    source: /остат/i,
    target: /\bresidue\b/i,
    message: "balances and stock must not be described as residue",
  },
  {
    source: /на главную/i,
    target: /\bhead to head\b/i,
    message: "home navigation must use Home",
  },
  {
    source: /выйти/i,
    target: /\bget out\b/i,
    message: "sign-out actions must use sign out",
  },
  {
    source: /архивн\w* завед/i,
    target: /\barchives\b/i,
    message: "archived venues must not be called archives",
  },
  {
    source: /смен/i,
    target: /^(?!.*\bshift).*(?:\bchanges?\b)/i,
    message: "shift copy must retain the shift concept",
  },
  {
    source: /профил\w* начислен/i,
    target: /\baccrual profiles?\b/i,
    message: "employee compensation profiles must use pay profile terminology",
  },
  {
    source: /гарант|минималк/i,
    target: /\bwarrant(?:y|ies)\b/i,
    message: "minimum pay guarantees must not be translated as warranties",
  },
  {
    source: /приход/i,
    target: /\barrival\b/i,
    message: "cash inflows must not be translated as arrivals",
  },
  {
    source: /подсказ/i,
    target: /\bclues?\b/i,
    message: "UI suggestions must not be translated as clues",
  },
  {
    source: /перевод/i,
    target: /\btranslations?\b/i,
    message:
      "payment-method transfers must not be translated as language translations",
  },
  {
    source: /преми/i,
    target: /\bprizes?\b/i,
    message: "employee bonuses must not be translated as prizes",
  },
  {
    source: /кальян/i,
    target: /\b(?:kalyan|hooker)\b/i,
    message: "hookah product terminology must use hookah",
  },
  {
    source: /тариф/i,
    target: /\btariffs?\b/i,
    message: "subscription offerings must use plan terminology",
  },
];

for (const [source, translated] of Object.entries(catalog)) {
  const sourceTrimmed = source.trim();
  const translatedTrimmed = translated.trim();
  for (const marker of ["·", "•", ",", ".", "—", "✓"]) {
    if (
      sourceTrimmed.startsWith(marker) &&
      !translatedTrimmed.startsWith(marker)
    ) {
      errors.push(
        `translation must preserve the leading ${marker}: ${JSON.stringify(source)} -> ${JSON.stringify(translated)}`,
      );
    }
  }
  if (sourceTrimmed.startsWith("»") && !translatedTrimmed.startsWith("”")) {
    errors.push(
      `translation must preserve the leading closing quote: ${JSON.stringify(source)} -> ${JSON.stringify(translated)}`,
    );
  }
  if (sourceTrimmed.endsWith(":") && !translatedTrimmed.endsWith(":")) {
    errors.push(
      `translation must preserve the trailing colon: ${JSON.stringify(source)} -> ${JSON.stringify(translated)}`,
    );
  }
  if (sourceTrimmed.endsWith("…") && !translatedTrimmed.endsWith("…")) {
    errors.push(
      `translation must preserve the loading ellipsis: ${JSON.stringify(source)} -> ${JSON.stringify(translated)}`,
    );
  }
  for (const arrow of ["→", "←"]) {
    if (sourceTrimmed.endsWith(arrow) && !translatedTrimmed.endsWith(arrow)) {
      errors.push(
        `translation must preserve the trailing ${arrow}: ${JSON.stringify(source)} -> ${JSON.stringify(translated)}`,
      );
    }
  }
  if (/\ban venue\b/i.test(translated)) {
    errors.push(
      `translation contains an invalid article: ${JSON.stringify(source)} -> ${JSON.stringify(translated)}`,
    );
  }
  if (/\s+n$/.test(translated)) {
    errors.push(
      `translation contains a machine-generated trailing token: ${JSON.stringify(source)} -> ${JSON.stringify(translated)}`,
    );
  }
  for (const rule of semanticRules) {
    if (rule.source.test(source) && rule.target.test(translated)) {
      errors.push(
        `${rule.message}: ${JSON.stringify(source)} -> ${JSON.stringify(translated)}`,
      );
    }
  }
}

if (errors.length) {
  console.error(`i18n quality: ${errors.length} issue(s)`);
  for (const error of errors.slice(0, 100)) console.error(`- ${error}`);
  if (errors.length > 100) console.error(`... and ${errors.length - 100} more`);
  process.exit(1);
}

console.log(
  `i18n quality: ${activeCuratedCount} active curated translations and semantic rules passed`,
);
