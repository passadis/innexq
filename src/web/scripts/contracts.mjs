import { readFile, writeFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { compile } from "json-schema-to-typescript";

const root = resolve(import.meta.dirname, "..");
for (const [file, name] of [["run-record", "RunRecord"], ["run-event", "RunEvent"], ["case-command", "CaseCommand"], ["case-review", "CaseReview"]]) {
  const schema = JSON.parse(await readFile(resolve(root, "../contracts/schemas/v1", `${file}.schema.json`), "utf8"));
  const output = await compile(schema, name, { bannerComment: "/* Generated from the v1 Pydantic JSON schema. Do not edit. */", additionalProperties: false });
  const target = resolve(root, "src/generated", `${file}.ts`);
  if (process.argv.includes("--check")) {
    if (await readFile(target, "utf8") !== output) throw new Error(`Stale web contract: ${file}`);
  } else {
    await mkdir(resolve(root, "src/generated"), { recursive: true });
    await writeFile(target, output);
  }
}
