import { collectUserFacingSources } from "./i18n-static-sources.mjs";

process.stdout.write(
  `${JSON.stringify([...collectUserFacingSources().keys()].sort())}\n`,
);
