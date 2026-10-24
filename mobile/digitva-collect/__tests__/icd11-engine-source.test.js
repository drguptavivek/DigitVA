const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { engineFiles, findSpike, stageEngine } = require("../modules/digitva-icd11/scripts/stage-engine");

const STAGE = path.join(__dirname, "..", "modules", "digitva-icd11", "scripts", "stage-engine.js");
const DATA = ["icd11_2026-01-17_release-icf-mms_en.pbf.gz", "ix_(2026-01-17)_foundation-icf-mms_en_v5.7.pbf.zip"];

/** A small spike-shaped folder: the same layout as private/icd11-offline-spike, with fake bytes. */
function makeSpike(root) {
  const write = (rel, text) => {
    fs.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true });
    fs.writeFileSync(path.join(root, rel), text);
  };
  write("bridge-aot/pub-bionic/digitva_icd11.so", "engine-library");
  write("bundle_min/Data/languageResources.txt", "who-language");
  write("bundle_min/Config/settings.txt", "config");
  for (const file of DATA) write(`data/${file}`, `data-${file}`);
  write("data/DORIS_v2.1_1.2.0/AddCodes.json", "add-codes");
  write("data/DORIS_v2.1_1.2.0/DORIS_v2.1_1.2.0.zip", "not shipped");
  write("data/DORIS_v2.1_1.2.0/log.txt", "not shipped");
  return root;
}

describe("stage-engine source selection", () => {
  let tmp;
  beforeEach(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "icd11-source-test-"));
  });
  afterEach(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  it("lists the shipped files only, sorted, without DORIS's zip or log", () => {
    const spike = makeSpike(path.join(tmp, "spike"));
    expect(engineFiles(spike)).toEqual(
      [
        "bridge-aot/pub-bionic/digitva_icd11.so",
        "bundle_min/Config/settings.txt",
        "bundle_min/Data/languageResources.txt",
        `data/${DATA[0]}`,
        `data/${DATA[1]}`,
        "data/DORIS_v2.1_1.2.0/AddCodes.json",
      ].sort()
    );
  });

  it("takes DIGITVA_ICD11_SPIKE_DIR before the private/ search", () => {
    const spike = makeSpike(path.join(tmp, "spike"));
    expect(findSpike({ DIGITVA_ICD11_SPIKE_DIR: spike }, tmp)).toBe(spike);
  });

  it("stages from the spike folder and records only the WHO files", () => {
    const module = path.join(tmp, "module");
    const spike = makeSpike(path.join(tmp, "spike"));
    stageEngine({ moduleDir: module, env: { DIGITVA_ICD11_SPIKE_DIR: spike } });
    const assets = path.join(module, "android", "src", "main", "assets", "digitva-icd11");
    expect(fs.readFileSync(path.join(module, "android", "src", "main", "jniLibs", "arm64-v8a", "libdigitva_icd11.so"), "utf8")).toBe("engine-library");
    expect(fs.readFileSync(path.join(assets, "bundle", "Config", "settings.txt.bin"), "utf8")).toBe("config");
    const who = JSON.parse(fs.readFileSync(path.join(assets, "who-files.json"), "utf8")).map((item) => item.path);
    expect(who.sort()).toEqual(
      [`bundle/Data/languageResources.txt`, `data/${DATA[0]}`, `data/${DATA[1]}`, "data/DORIS_v2.1_1.2.0/AddCodes.json"].sort()
    );
  });

  it("stages from DIGITVA_ICD11_ENGINE_ARCHIVE to the same files, and beats the spike folder when both are set", () => {
    const spike = makeSpike(path.join(tmp, "spike"));
    const archive = path.join(tmp, "icd11-engine-test.tar.gz");
    // The archive holds only the files the packager lists, as scripts/package-icd11-engine.sh does.
    execFileSync("tar", ["-czf", archive, "-C", spike, ...engineFiles(spike)]);

    const fromSpike = path.join(tmp, "from-spike");
    const fromArchive = path.join(tmp, "from-archive");
    stageEngine({ moduleDir: fromSpike, env: { DIGITVA_ICD11_SPIKE_DIR: spike } });
    // The spike dir is set to a folder that does not exist: the archive must win without touching it.
    stageEngine({ moduleDir: fromArchive, env: { DIGITVA_ICD11_ENGINE_ARCHIVE: archive, DIGITVA_ICD11_SPIKE_DIR: path.join(tmp, "missing") } });

    const sidecar = (dir) => fs.readFileSync(path.join(dir, "android", "src", "main", "assets", "digitva-icd11", "who-files.json"), "utf8");
    expect(sidecar(fromArchive)).toBe(sidecar(fromSpike));
  });

  it("fails plainly when the archive is missing or holds no engine", () => {
    const module = path.join(tmp, "module");
    expect(() => stageEngine({ moduleDir: module, env: { DIGITVA_ICD11_ENGINE_ARCHIVE: path.join(tmp, "nope.tar.gz") } })).toThrow("does not exist");
    const empty = path.join(tmp, "empty");
    fs.mkdirSync(path.join(empty, "bundle_min"), { recursive: true });
    fs.writeFileSync(path.join(empty, "bundle_min", "x.txt"), "x");
    const archive = path.join(tmp, "empty.tar.gz");
    execFileSync("tar", ["-czf", archive, "-C", empty, "bundle_min"]);
    expect(() => stageEngine({ moduleDir: module, env: { DIGITVA_ICD11_ENGINE_ARCHIVE: archive } })).toThrow("does not contain the offline ICD-11 engine");
  });

  it("prints the file list from the --list CLI mode", () => {
    const spike = makeSpike(path.join(tmp, "spike"));
    const out = execFileSync(process.execPath, [STAGE, "--list", spike], { encoding: "utf8" });
    expect(out.trim().split("\n")).toEqual(engineFiles(spike));
  });
});
