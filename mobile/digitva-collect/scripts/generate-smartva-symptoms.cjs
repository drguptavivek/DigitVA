// Generate the only symptom text allowed into the local SmartVA cache.
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../../..");
const data = path.join(root, "vendor/smartva-analyze/rust/src/data");
const output = path.join(__dirname, "../src/smartva/symptom-descriptions.json");
const descriptions = new Set();
const rustString = '"(?:[^"\\\\]|\\\\.)*"';
const entry = new RegExp(`\\(\\s*(${rustString})\\s*,\\s*(${rustString})\\s*\\)\\s*,?`, "gy");

for (const moduleName of ["adult", "child", "neonate"]) {
  const source = fs.readFileSync(path.join(data, `${moduleName}_tariff_data.rs`), "utf8");
  const match = source.match(/pub static SYMPTOM_DESCRIPTIONS: &\[\(&str, &str\)\] = &\[([\s\S]*?)\n\];/);
  if (!match) throw new Error(`Missing symptom descriptions for ${moduleName}`);
  const body = match[1];
  let offset = 0;
  let count = 0;
  while (offset < body.length) {
    while (offset < body.length && /\s/.test(body[offset])) offset++;
    if (offset === body.length) break;
    entry.lastIndex = offset;
    const item = entry.exec(body);
    if (!item) throw new Error(`Unrecognized symptom description at ${moduleName}:${offset}`);
    JSON.parse(item[1]);
    descriptions.add(JSON.parse(item[2]));
    count++;
    offset = entry.lastIndex;
  }
  if (!count) throw new Error(`Empty symptom descriptions for ${moduleName}`);
}

const generated = `${JSON.stringify([...descriptions].sort(), null, 2)}\n`;
if (process.argv.includes("--check")) {
  if (fs.readFileSync(output, "utf8") !== generated) throw new Error("SmartVA symptom descriptions are out of date; run node scripts/generate-smartva-symptoms.cjs");
} else {
  fs.writeFileSync(output, generated);
}
