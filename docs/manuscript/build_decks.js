// Regenerates DigitVA_Programme_Overview.pptx and DigitVA_Architecture_and_Workflow.pptx.
// Needs node with pptxgenjs, react, react-dom, react-icons and sharp installed:
//   npm install pptxgenjs react react-dom react-icons sharp && node build_decks.js docs/manuscript
// Builds the DigitVA programme deck and the two-slide manuscript figure deck.
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");

const OUT = process.argv[2] || ".";
const C = {
  navy: "17324D", teal: "12989A", orange: "E8912D", green: "2E7D55",
  purple: "5E4FA2", red: "C0463F", grey: "5B6B7B", ink: "1E2A36",
  bg: "F6F8FB", white: "FFFFFF", line: "CBD5E1",
  tealT: "E3F4F3", orangeT: "FDEEDC", greenT: "E4F2EA", purpleT: "ECE9F6",
  blueT: "E3EDF8", greyT: "EEF1F4", redT: "F9E5E3", blue: "3C78B5",
};
const FONT = "Calibri";
const W = 13.333, H = 7.5;

async function icon(name, color, px = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(fa[name], { color: "#" + color, size: px }));
  const buf = await sharp(Buffer.from(svg)).resize(px, px).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

function base(pres, title, subtitle, n) {
  const s = pres.addSlide();
  s.background = { color: C.bg };
  s.addText(title, { x: 0.6, y: 0.35, w: W - 1.2, h: 0.75, fontFace: FONT,
    fontSize: 34, bold: true, color: C.navy, margin: 0, isTextBox: true });
  if (subtitle) s.addText(subtitle, { x: 0.6, y: 1.1, w: W - 1.2, h: 0.45,
    fontFace: FONT, fontSize: 16, color: C.grey, margin: 0, isTextBox: true });
  if (n) s.addText(`DigitVA   ${n}`, { x: W - 2.1, y: H - 0.45, w: 1.6, h: 0.3,
    fontFace: FONT, fontSize: 10, color: C.grey, align: "right", margin: 0, isTextBox: true });
  return s;
}

function card(s, x, y, w, h, title, body, fill, stroke, o = {}) {
  s.addShape("roundRect", { x, y, w, h, rectRadius: 0.08,
    fill: { color: fill }, line: { color: stroke, width: 1.25 } });
  s.addText([
    { text: title, options: { bold: true, fontSize: o.ts || 17, color: C.ink, breakLine: true, paraSpaceAfter: 6 } },
    { text: body, options: { fontSize: o.bs || 12.5, color: C.ink } },
  ], { x: x + 0.12, y: y + 0.08, w: w - 0.24, h: h - 0.16, fontFace: FONT,
    align: o.align || "center", valign: o.valign || "middle", margin: 0, isTextBox: true });
}

function arrow(s, x1, y1, x2, y2, color) {
  s.addShape("line", { x: Math.min(x1, x2), y: Math.min(y1, y2),
    w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001,
    flipH: x2 < x1, flipV: y2 < y1,
    line: { color, width: 2, endArrowType: "triangle" } });
}

function label(s, x, y, w, text) {
  s.addText(text, { x, y, w, h: 0.3, fontFace: FONT, fontSize: 12, bold: true,
    color: C.grey, charSpacing: 3, margin: 0, isTextBox: true });
}

// ---------- Figure 1: architecture ----------
function archSlide(pres, n) {
  const s = base(pres, "DigitVA architecture and concept model",
    "An open, auditable platform joining VA collection, computer-coded evidence and physician-authorised cause assignment", n);
  label(s, 0.6, 1.8, 3, "INPUT CHANNELS");
  label(s, 3.95, 1.8, 3, "DIGITVA CORE");
  label(s, 10.05, 1.8, 3, "OUTPUTS + USERS");
  const inW = 2.85, inH = 1.2, inX = 0.6;
  const ins = [
    ["WHO VA forms", "ODK Central sync\nMultilingual interviews", C.blueT, C.blue, C.teal],
    ["Additional forms", "SmartVA-compatible and\nprogramme-specific profiles", C.purpleT, C.purple, C.purple],
    ["Health-system intake", "Death register and direct\nweb interview in the browser", C.greenT, C.green, C.green],
  ];
  ins.forEach(([t, b, f, st, ac], i) => {
    const y = 2.2 + i * 1.45;
    card(s, inX, y, inW, inH, t, b, f, st, { ts: 16, bs: 12 });
    arrow(s, inX + inW + 0.05, y + inH / 2, 3.9, y + inH / 2, ac);
  });
  // core frame
  s.addShape("roundRect", { x: 3.95, y: 2.15, w: 5.85, h: 4.35, rectRadius: 0.1,
    fill: { color: C.white }, line: { color: C.line, width: 1.5 } });
  const cw = 1.75, ch = 1.35, cx = [4.15, 6.1, 8.05], cy = [2.35, 4.05];
  const core = [
    [0, 0, "Intake + lineage", "Incremental sync\nPayload versions\nAttachment integrity", C.tealT, C.teal],
    [1, 0, "CCVA evidence", "SmartVA today\nMore algorithms planned", C.orangeT, C.orange],
    [2, 0, "Physician coding", "One coder decides\nMasked DORIS\ncertificate first", C.blueT, C.blue],
    [0, 1, "Workflow state", "Allocations\nQueues + events\nIdempotent retries", C.greyT, C.grey],
    [1, 1, "Optional review", "Second physician path\nRecoding episodes\nFinal authority", C.purpleT, C.purple],
    [2, 1, "Mortality intelligence", "Cause groups\nDashboards\nScoped exports", C.greenT, C.green],
  ];
  core.forEach(([i, j, t, b, f, st]) => card(s, cx[i], cy[j], cw, ch, t, b, f, st, { ts: 14, bs: 11 }));
  arrow(s, cx[0] + cw, cy[0] + ch / 2, cx[1], cy[0] + ch / 2, C.teal);
  arrow(s, cx[1] + cw, cy[0] + ch / 2, cx[2], cy[0] + ch / 2, C.teal);
  arrow(s, cx[2] + cw / 2, cy[0] + ch, cx[2] + cw / 2, cy[1], C.teal);
  arrow(s, cx[0] + cw, cy[1] + ch / 2, cx[1], cy[1] + ch / 2, C.purple);
  arrow(s, cx[1] + cw, cy[1] + ch / 2, cx[2], cy[1] + ch / 2, C.green);
  [["Role + scope access", C.blueT, C.navy], ["Audit trail", C.orangeT, C.navy], ["PII-aware security", C.redT, C.red]]
    .forEach(([t, f, col], i) => {
      s.addShape("roundRect", { x: 4.15 + i * 1.95, y: 5.72, w: 1.75, h: 0.45, rectRadius: 0.2,
        fill: { color: f }, line: { color: f } });
      s.addText(t, { x: 4.15 + i * 1.95, y: 5.72, w: 1.75, h: 0.45, fontFace: FONT, fontSize: 11,
        bold: true, color: col, align: "center", valign: "middle", margin: 0, isTextBox: true });
    });
  const outs = [
    ["Authorised cause of death", "ICD-10 in production\nICD-11 with WHO DORIS", C.greenT, C.green, C.green],
    ["Programme operations", "Medical colleges, HDSS sites\nand research networks", C.blueT, C.blue, C.teal],
    ["Health-system action", "District intelligence\nPlanning and surveillance", C.orangeT, C.orange, C.orange],
  ];
  outs.forEach(([t, b, f, st, ac], i) => {
    const y = 2.2 + i * 1.45;
    card(s, 10.05, y, 2.7, inH, t, b, f, st, { ts: 15, bs: 12 });
    arrow(s, 9.85, y + inH / 2, 10.0, y + inH / 2, ac);
  });
  // platform band
  s.addShape("roundRect", { x: 0.6, y: 6.6, w: W - 1.2, h: 0.5, rectRadius: 0.08,
    fill: { color: C.navy }, line: { color: C.navy } });
  const plat = [["OPEN PLATFORM", "9FD8D6"], ["Flask", C.white], ["PostgreSQL", C.white], ["Celery + Redis", C.white],
    ["Docker", C.white], ["Self-hosted WHO ICD-11 API", C.white], ["Open source on GitHub", "7FD6CF"], ["LLM gateway (future)", "F5B95F"]];
  s.addText(plat.map(([t, col], i) => ({ text: t + (i < plat.length - 1 ? "     " : ""),
    options: { color: col, bold: true } })),
    { x: 0.8, y: 6.6, w: W - 1.6, h: 0.5, fontFace: FONT, fontSize: 12, valign: "middle",
      align: "center", margin: 0, isTextBox: true });
  return s;
}

// ---------- Figure 2: workflow ----------
function flowSlide(pres, n) {
  const s = base(pres, "From death to mortality intelligence",
    "Today's workflow, and the planned shift from periodic batches to near-real-time health-system operation", n);
  const top = [
    ["Death identified", "Community death, or an\nentry in the death register", C.greenT, C.green],
    ["VA interview", "WHO 2022 form\nor supported profile", C.blueT, C.blue],
    ["Intake", "ODK Central sync or\ndirect web entry", C.tealT, C.teal],
    ["Validate + version", "Identity, completeness,\nattachments, lineage", C.greyT, C.grey],
    ["CCVA evidence", "SmartVA likelihoods\nwith provenance", C.orangeT, C.orange],
  ];
  const bw = 2.2, bh = 1.3, gap = 0.33, y1 = 2.0, y2 = 4.05;
  top.forEach(([t, b, f, st], i) => {
    const x = 0.6 + i * (bw + gap);
    card(s, x, y1, bw, bh, t, b, f, st, { ts: 16, bs: 12 });
    badge(s, x + 0.12, y1 - 0.2, i + 1, st);
    if (i < 4) arrow(s, x + bw + 0.02, y1 + bh / 2, x + bw + gap - 0.02, y1 + bh / 2, st);
  });
  const lastX = 0.6 + 4 * (bw + gap);
  arrow(s, lastX + bw / 2, y1 + bh + 0.02, lastX + bw / 2, y2 - 0.25, C.orange);
  const bottom = [ // right to left
    ["Physician coding", "Masked: certificate and DORIS\nfirst, then SmartVA shown", C.blueT, C.blue],
    ["Optional review", "A second physician may code;\nnot routine dual coding", C.purpleT, C.purple],
    ["Final cause", "Physician-authorised ICD code,\nevidence and audit kept", C.greenT, C.green],
    ["Use the data", "Cause groups, dashboards,\nexports, feedback", C.orangeT, C.orange],
  ];
  const bw2 = 2.78, gap2 = 0.33;
  bottom.forEach(([t, b, f, st], i) => {
    const x = W - 0.6 - bw2 - i * (bw2 + gap2);
    card(s, x, y2, bw2, bh, t, b, f, st, { ts: 16, bs: 12 });
    badge(s, x + 0.12, y2 - 0.2, i + 6, st);
    if (i < 3) arrow(s, x - 0.02, y2 + bh / 2, x - gap2 + 0.02, y2 + bh / 2, st);
  });
  s.addShape("roundRect", { x: 0.6, y: 5.75, w: 7.6, h: 1.05, rectRadius: 0.08,
    fill: { color: C.redT }, line: { color: "E3A9A4", width: 1 } });
  s.addText([
    { text: "DATA-CHANGE SAFETY LOOP", options: { bold: true, color: C.red, charSpacing: 2, fontSize: 12, breakLine: true } },
    { text: "Changed interview data becomes a new payload version. A data manager reviews it and keeps the current decision or starts protected recoding. Nothing is silently overwritten.",
      options: { color: C.ink, fontSize: 12.5 } },
  ], { x: 0.8, y: 5.8, w: 7.2, h: 0.95, fontFace: FONT, valign: "middle", margin: 0, isTextBox: true });
  s.addShape("roundRect", { x: 8.5, y: 5.75, w: 4.23, h: 1.05, rectRadius: 0.08,
    fill: { color: C.navy }, line: { color: C.navy } });
  s.addText([
    { text: "BATCH → NEAR REAL TIME", options: { bold: true, color: "7FD6CF", charSpacing: 2, fontSize: 12, breakLine: true } },
    { text: "Delta checks, bounded queues, visible exceptions, idempotent retries, direct intake", options: { color: C.white, fontSize: 12.5 } },
  ], { x: 8.7, y: 5.8, w: 3.85, h: 0.95, fontFace: FONT, valign: "middle", margin: 0, isTextBox: true });
  return s;
}

function badge(s, x, y, num, color) {
  s.addShape("ellipse", { x, y, w: 0.42, h: 0.42, fill: { color }, line: { color: C.white, width: 1.5 } });
  s.addText(String(num), { x, y, w: 0.42, h: 0.42, fontFace: FONT, fontSize: 13, bold: true,
    color: C.white, align: "center", valign: "middle", margin: 0, isTextBox: true });
}

function iconRows(s, ic, rows, x, y, w, rowH) {
  rows.forEach(([name, head, body], i) => {
    const yy = y + i * rowH;
    s.addShape("ellipse", { x, y: yy, w: 0.62, h: 0.62, fill: { color: C.tealT }, line: { color: C.tealT } });
    s.addImage({ data: ic[name], x: x + 0.14, y: yy + 0.14, w: 0.34, h: 0.34 });
    s.addText([
      { text: head, options: { bold: true, fontSize: 17, color: C.navy, breakLine: true } },
      { text: body, options: { fontSize: 14, color: C.ink } },
    ], { x: x + 0.85, y: yy - 0.05, w: w - 0.85, h: rowH - 0.1, fontFace: FONT, valign: "top", margin: 0, isTextBox: true });
  });
}

async function buildDeck() {
  const names = ["FaUserMd", "FaPuzzlePiece", "FaClipboardCheck", "FaDatabase", "FaCalculator", "FaStethoscope",
    "FaChartBar", "FaUserShield", "FaHistory", "FaLock", "FaExchangeAlt", "FaServer", "FaCodeBranch", "FaVial",
    "FaGlobeAsia", "FaKey"];
  const ic = {};
  for (const n of names) ic[n] = await icon(n, C.teal);
  const icW = {};
  for (const n of ["FaUserMd", "FaCalculator", "FaStethoscope", "FaChartBar"]) icW[n] = await icon(n, C.white);

  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.title = "DigitVA";
  let n = 0;

  // 1 Title
  {
    const s = pres.addSlide(); n++;
    s.background = { color: C.navy };
    s.addText("DigitVA", { x: 0.8, y: 1.7, w: 11, h: 1.2, fontFace: FONT, fontSize: 66, bold: true, color: C.white, margin: 0, isTextBox: true });
    s.addText("A physician-authorised cause for every verbal autopsy", { x: 0.8, y: 2.95, w: 11.5, h: 0.7,
      fontFace: FONT, fontSize: 28, color: "9FD8D6", margin: 0, isTextBox: true });
    s.addText("An open platform for collecting, coding and using verbal autopsy data in India",
      { x: 0.8, y: 3.7, w: 11.5, h: 0.5, fontFace: FONT, fontSize: 18, color: "D5DEE8", margin: 0, isTextBox: true });
    s.addText("Central Admin Team, AIIMS New Delhi  ·  September 2026", { x: 0.8, y: 6.3, w: 11, h: 0.4,
      fontFace: FONT, fontSize: 14, color: "A9B7C6", margin: 0, isTextBox: true });
    ["FaUserMd", "FaCalculator", "FaStethoscope", "FaChartBar"].forEach((k, i) => {
      s.addShape("ellipse", { x: 0.8 + i * 0.85, y: 4.75, w: 0.62, h: 0.62, fill: { color: C.teal }, line: { color: C.teal } });
      s.addImage({ data: icW[k], x: 0.94 + i * 0.85, y: 4.89, w: 0.34, h: 0.34 });
    });
    s.addNotes("DigitVA brings verbal autopsy collection, computer-coded evidence, physician cause assignment and reporting into one auditable platform.");
  }

  // 2 Problem
  {
    const s = base(pres, "The gap DigitVA closes", "Many deaths in India happen at home or without a medical certificate of cause of death", ++n);
    iconRows(s, ic, [
      ["FaPuzzlePiece", "Fragmented tools", "Programmes run separate tools for interviews, physician review, computer coding, quality checks and reporting."],
      ["FaUserMd", "Physicians give the best cause", "In the Indian evaluation, physician-coded VA scored highest on accuracy and agreement. Algorithms should inform the physician, not replace them."],
      ["FaClipboardCheck", "Evidence must stay traceable", "When interviews change after coding, programmes need to see it and decide, not overwrite silently."],
    ], 0.6, 2.1, 7.2, 1.6);
    s.addShape("roundRect", { x: 8.4, y: 1.9, w: 4.33, h: 3.55, rectRadius: 0.1, fill: { color: C.navy }, line: { color: C.navy } });
    s.addText([
      { text: "Built on MINErVA", options: { bold: true, fontSize: 22, color: "9FD8D6", breakLine: true, paraSpaceAfter: 10 } },
      { text: "The team's earlier platform for the SRS verbal autopsy form, with two physicians per case, was taken up by the Sample Registration System under the Registrar General of India.", options: { fontSize: 15, color: C.white, breakLine: true, paraSpaceAfter: 10 } },
      { text: "DigitVA extends it to WHO 2022 forms, one accountable physician per case, and ICD-11.", options: { fontSize: 15, color: "F5B95F" } },
    ], { x: 8.7, y: 2.1, w: 3.75, h: 3.2, fontFace: FONT, valign: "top", margin: 0, isTextBox: true });
    s.addNotes("Source: DigitVA manuscript draft (Introduction, Discussion; Benara et al.).");
  }

  // 3 What it is
  {
    const s = base(pres, "One platform, four jobs", "From the interview to a cause the health system can act on", ++n);
    const cards = [
      ["FaDatabase", "Collect", "Sync interviews from ODK Central, or enter them directly in the browser. Every change is kept as a version."],
      ["FaCalculator", "Compute", "Run SmartVA on each case and keep its likelihoods and provenance as evidence."],
      ["FaStethoscope", "Code", "One physician assigns the ICD cause, with the WHO DORIS rules engine for ICD-11."],
      ["FaChartBar", "Use", "Cause groups, dashboards, scoped exports and district-level feedback."],
    ];
    const cw = 2.85, gap = 0.3;
    cards.forEach(([k, t, b], i) => {
      const x = 0.6 + i * (cw + gap), y = 2.4;
      s.addShape("roundRect", { x, y, w: cw, h: 3.5, rectRadius: 0.1, fill: { color: C.white },
        line: { color: C.line, width: 1 }, shadow: { type: "outer", color: "000000", opacity: 0.08, blur: 6, offset: 2, angle: 90 } });
      s.addShape("ellipse", { x: x + 0.3, y: y + 0.35, w: 0.8, h: 0.8, fill: { color: C.tealT }, line: { color: C.tealT } });
      s.addImage({ data: ic[k], x: x + 0.5, y: y + 0.55, w: 0.4, h: 0.4 });
      s.addText(t, { x: x + 0.3, y: y + 1.35, w: cw - 0.6, h: 0.55, fontFace: FONT, fontSize: 24, bold: true, color: C.navy, margin: 0, isTextBox: true });
      s.addText(b, { x: x + 0.3, y: y + 1.95, w: cw - 0.6, h: 2.0, fontFace: FONT, fontSize: 15, color: C.ink, valign: "top", margin: 0, isTextBox: true });
    });
  }

  // 4, 5 figures
  archSlide(pres, ++n);
  flowSlide(pres, ++n);

  // 6 ICD-11 + DORIS
  {
    const s = base(pres, "ICD-11 with WHO's DORIS rules engine",
      "Physicians write the death certificate; WHO's mortality rules choose the underlying cause", ++n);
    const steps = [
      ["STEP 1  ·  MASKED", "Certificate first", "The physician writes Part I and Part II from the interview and narrative, runs DORIS and confirms an underlying cause. SmartVA is hidden, so it cannot anchor the decision.", C.blue, C.blueT],
      ["STEP 2  ·  INFORMED", "Then compare", "SmartVA is shown. The physician keeps the Step 1 cause, takes SmartVA's ICD-11 target, or enters their own code. That choice is final.", C.teal, C.tealT],
    ];
    steps.forEach(([k, t, b, col, f], i) => {
      const x = 0.6 + i * 4.2;
      s.addShape("roundRect", { x, y: 1.95, w: 3.9, h: 2.9, rectRadius: 0.1, fill: { color: f }, line: { color: col, width: 1.25 } });
      s.addText([
        { text: k, options: { bold: true, fontSize: 12, color: col, charSpacing: 2, breakLine: true, paraSpaceAfter: 6 } },
        { text: t, options: { bold: true, fontSize: 22, color: C.navy, breakLine: true, paraSpaceAfter: 8 } },
        { text: b, options: { fontSize: 14.5, color: C.ink } },
      ], { x: x + 0.3, y: 2.15, w: 3.3, h: 2.6, fontFace: FONT, valign: "top", margin: 0, isTextBox: true });
    });
    arrow(s, 4.52, 3.4, 4.78, 3.4, C.teal);
    const facts = [
      ["FaServer", "Self-hosted WHO ICD-11 API", "whoicd/icd-api 2.6.0, MMS 2026-01, pinned by digest. No case data leaves the server."],
      ["FaChartBar", "Straight into cause groups", "ICD-11 codes map directly to WHO 2022 VA cause groups (18,505 rows), no ICD-10 crosswalk."],
      ["FaExchangeAlt", "Per-project choice", "ICD-10 projects keep simple entry; ICD-11 projects always use DORIS."],
    ];
    iconRows(s, ic, facts, 9.0, 1.95, 3.8, 1.2);
    s.addText("A public DORIS training service runs without any case data, for teaching certificate writing.", {
      x: 0.6, y: 5.25, w: 8.1, h: 0.5, fontFace: FONT, fontSize: 14, italic: true, color: C.grey, margin: 0, isTextBox: true });
    s.addText("Status: built and running on the development project; production release in progress for October 2026.", {
      x: 0.6, y: 5.75, w: 12, h: 0.4, fontFace: FONT, fontSize: 14, bold: true, color: C.orange, margin: 0, isTextBox: true });
  }

  // 7 Reach
  {
    const s = base(pres, "Where DigitVA runs today", "Operational counts from the DigitVA database, 22 September 2026", ++n);
    const stats = [["11", "sites"], ["7,917", "VA submissions"], ["99.5%", "with a final cause"], ["82", "physician coders"]];
    stats.forEach(([v, l], i) => {
      const x = 0.6 + i * 3.1;
      s.addText(v, { x, y: 1.85, w: 2.9, h: 1.0, fontFace: FONT, fontSize: 56, bold: true, color: C.teal, margin: 0, isTextBox: true });
      s.addText(l, { x, y: 2.85, w: 2.9, h: 0.4, fontFace: FONT, fontSize: 16, color: C.grey, margin: 0, isTextBox: true });
    });
    const hdr = (t) => ({ text: t, options: { bold: true, color: C.white, fill: { color: C.navy } } });
    const rows = [
      [hdr("Project"), hdr("Sites"), hdr("Submissions"), hdr("Final coded"), hdr("Coders")],
      ["UNSW01: Digital solutions for cause-of-death data", "4", "965", "949", "24"],
      ["ICMR01: Physician-ascertained COD at district level", "7", "6,952", "6,928", "58"],
      [{ text: "Total", options: { bold: true } }, { text: "11", options: { bold: true } }, { text: "7,917", options: { bold: true } },
        { text: "7,877", options: { bold: true } }, { text: "82", options: { bold: true } }],
    ];
    s.addTable(rows, { x: 0.6, y: 3.6, w: 7.6, colW: [3.55, 0.7, 1.35, 1.2, 0.8], fontFace: FONT, fontSize: 13,
      color: C.ink, border: { type: "solid", color: C.line, pt: 0.75 }, fill: { color: C.white }, rowH: 0.42, valign: "middle" });
    s.addShape("roundRect", { x: 8.6, y: 3.6, w: 4.13, h: 1.95, rectRadius: 0.1, fill: { color: C.tealT }, line: { color: C.teal, width: 1 } });
    s.addText([
      { text: "Interview languages", options: { bold: true, fontSize: 18, color: C.navy, breakLine: true, paraSpaceAfter: 8 } },
      { text: "English plus Hindi, Odia, Khasi, Tamil, Kannada, Marathi, Malayalam and Bengali across the deployed form workbooks.", options: { fontSize: 14, color: C.ink } },
    ], { x: 8.85, y: 3.75, w: 3.65, h: 1.7, fontFace: FONT, valign: "top", margin: 0, isTextBox: true });
    s.addText("Source: DigitVA manuscript draft, Table 1; languages from the deployed ODK form workbooks.", {
      x: 0.6, y: 6.55, w: 10, h: 0.3, fontFace: FONT, fontSize: 11, color: C.grey, margin: 0, isTextBox: true });
    s.addNotes("Confirm the Table 1 counts against production before presenting: they come from the manuscript draft dated 22 Sep 2026.");
  }

  // 8 Trust
  {
    const s = base(pres, "Built for trust", "Who can see what, what changed, and who decided", ++n);
    const items = [
      ["FaUserShield", "Explicit, scoped access", "Grants at project, site or health-facility level. Admin is the only global role."],
      ["FaLock", "Personal data protected", "Identifying fields are flagged; collaborators without PII access never see them; PII is never logged."],
      ["FaHistory", "Complete audit trail", "Every workflow step is logged, with an admin activity viewer."],
      ["FaExchangeAlt", "No silent overwrite", "Changed interviews become new versions; recoding keeps the current cause until a new one is saved."],
      ["FaKey", "Stronger sign-in", "Breached passwords rejected. Two-step login with a local CAPTCHA and passkeys or TOTP for admins and data managers are being rolled out."],
      ["FaServer", "Data stays in-house", "Self-hosted database, WHO ICD API and CAPTCHA. Backups are verified."],
    ];
    items.forEach(([k, t, b], i) => {
      const col = i % 2, row = Math.floor(i / 2);
      const x = 0.6 + col * 6.2, y = 1.85 + row * 1.6;
      s.addShape("roundRect", { x, y, w: 5.95, h: 1.4, rectRadius: 0.08, fill: { color: C.white }, line: { color: C.line, width: 1 } });
      s.addShape("ellipse", { x: x + 0.25, y: y + 0.39, w: 0.62, h: 0.62, fill: { color: C.tealT }, line: { color: C.tealT } });
      s.addImage({ data: ic[k], x: x + 0.39, y: y + 0.53, w: 0.34, h: 0.34 });
      s.addText([
        { text: t, options: { bold: true, fontSize: 16, color: C.navy, breakLine: true } },
        { text: b, options: { fontSize: 13, color: C.ink } },
      ], { x: x + 1.1, y: y + 0.1, w: 4.7, h: 1.2, fontFace: FONT, valign: "middle", margin: 0, isTextBox: true });
    });
  }

  // 9 Using the data
  {
    const s = base(pres, "From causes to decisions", "Reporting that fits programmes and the health system", ++n);
    iconRows(s, ic, [
      ["FaChartBar", "Versioned cause groups", "WHO 2022 VA, WHO 2022 VA 2026, SRS India and CMEA10 bucket schemes, on a report page and an API."],
      ["FaClipboardCheck", "Data-manager dashboards", "About 15 core and 25 detailed indicators, filtered to each manager's scope."],
      ["FaDatabase", "Coded snapshot exports", "Scoped exports of coded causes of death for analysis."],
      ["FaGlobeAsia", "Health-system tree", "District, taluka, CHC, PHC, sub-centre and village, so results can flow back to where deaths happened."],
    ], 0.6, 1.9, 7.4, 1.2);
    s.addShape("roundRect", { x: 8.5, y: 1.9, w: 4.23, h: 4.5, rectRadius: 0.1, fill: { color: C.navy }, line: { color: C.navy } });
    const tree = ["District", "Taluka", "CHC", "PHC", "Sub-centre", "Village"];
    tree.forEach((t, i) => {
      const x = 8.8 + i * 0.28, y = 2.2 + i * 0.66;
      s.addShape("roundRect", { x, y, w: 2.5, h: 0.48, rectRadius: 0.1, fill: { color: i % 2 ? "24486B" : C.teal }, line: { color: C.navy } });
      s.addText(t, { x, y, w: 2.5, h: 0.48, fontFace: FONT, fontSize: 14, bold: true, color: C.white, align: "center", valign: "middle", margin: 0, isTextBox: true });
    });
  }

  // 10 Open + sustainable
  {
    const s = base(pres, "Open and sustainable", "Plain, well-understood components a state IT team can run", ++n);
    const stats = [["2,354", "automated tests, all passing"], ["0", "outside services to code a case (ICD API and SmartVA run in-house)"], ["1", "Docker Compose stack to deploy"]];
    stats.forEach(([v, l], i) => {
      const y = 1.95 + i * 1.5;
      s.addText(v, { x: 0.6, y, w: 2.6, h: 1.0, fontFace: FONT, fontSize: 54, bold: true, color: C.teal, margin: 0, isTextBox: true });
      s.addText(l, { x: 3.0, y: y + 0.2, w: 4.2, h: 0.7, fontFace: FONT, fontSize: 17, color: C.ink, valign: "middle", margin: 0, isTextBox: true });
    });
    iconRows(s, ic, [
      ["FaCodeBranch", "Source on GitHub", "github.com/drguptavivek/DigitVA"],
      ["FaServer", "Standard stack", "Python and Flask, PostgreSQL, Celery with Redis, nginx, all in Docker."],
      ["FaVial", "Change safely", "Additive database migrations and a test suite run on every change."],
    ], 7.5, 1.95, 5.3, 1.5);
  }

  // 11 Roadmap
  {
    const s = base(pres, "Roadmap", "Where DigitVA goes next", ++n);
    const phases = [
      ["V1", "Before Feb 2026", "WHO 2022 forms, SmartVA, physician coding with ICD-10", C.grey, C.greyT],
      ["V2", "Mar – Sep 2026", "Masked coding, cause-group reporting, data-change safety, multilingual forms", C.blue, C.blueT],
      ["V3", "Oct 2026 →", "ICD-11 with DORIS live, web forms and death register, health-system organisation", C.teal, C.tealT],
    ];
    s.addShape("line", { x: 0.9, y: 2.55, w: 11.5, h: 0, line: { color: C.line, width: 3 } });
    phases.forEach(([v, d, b, col, f], i) => {
      const x = 0.6 + i * 4.1;
      s.addShape("ellipse", { x: x + 0.1, y: 2.25, w: 0.6, h: 0.6, fill: { color: col }, line: { color: C.white, width: 2 } });
      s.addText(v, { x: x + 0.1, y: 2.25, w: 0.6, h: 0.6, fontFace: FONT, fontSize: 14, bold: true, color: C.white, align: "center", valign: "middle", margin: 0, isTextBox: true });
      s.addText(d, { x: x + 0.8, y: 2.33, w: 1.9, h: 0.44, fontFace: FONT, fontSize: 16, bold: true, color: col, valign: "middle", margin: 0.05, fill: { color: C.bg }, isTextBox: true });
      s.addShape("roundRect", { x, y: 3.1, w: 3.85, h: 1.3, rectRadius: 0.08, fill: { color: f }, line: { color: col, width: 1 } });
      s.addText(b, { x: x + 0.2, y: 3.15, w: 3.45, h: 1.2, fontFace: FONT, fontSize: 14, color: C.ink, valign: "middle", margin: 0, isTextBox: true });
    });
    s.addText("NEXT", { x: 0.6, y: 4.75, w: 3, h: 0.35, fontFace: FONT, fontSize: 13, bold: true, color: C.grey, charSpacing: 3, margin: 0, isTextBox: true });
    const next = [
      ["Passkeys and TOTP", "Mandatory second factor for admins and data managers (in progress)"],
      ["Project single sign-on", "Sign in through a project's own identity provider"],
      ["More ML coders", "InterVA, InSilicoVA, EAVA alongside SmartVA"],
      ["Semantic ICD search", "Local search by meaning, no external API (in progress)"],
      ["LLM assistance (future)", "Only with human confirmation and full provenance"],
    ];
    next.forEach(([t, b], i) => {
      const x = 0.6 + i * 2.47;
      s.addShape("roundRect", { x, y: 5.15, w: 2.32, h: 1.5, rectRadius: 0.08, fill: { color: C.white }, line: { color: C.line, width: 1 } });
      s.addText([
        { text: t, options: { bold: true, fontSize: 14, color: C.navy, breakLine: true, paraSpaceAfter: 4 } },
        { text: b, options: { fontSize: 11.5, color: C.ink } },
      ], { x: x + 0.15, y: 5.22, w: 2.02, h: 1.36, fontFace: FONT, valign: "top", margin: 0, isTextBox: true });
    });
  }

  // 12 Close
  {
    const s = pres.addSlide(); n++;
    s.background = { color: C.navy };
    s.addText("Every death counted.\nEvery cause authorised by a physician.", { x: 0.8, y: 1.9, w: 11.5, h: 1.9,
      fontFace: FONT, fontSize: 40, bold: true, color: C.white, margin: 0, isTextBox: true });
    s.addText("DigitVA joins verbal autopsy collection, computer evidence and physician decisions in one open, auditable platform, ready for ICD-11.",
      { x: 0.8, y: 4.0, w: 10.5, h: 0.9, fontFace: FONT, fontSize: 18, color: "D5DEE8", margin: 0, isTextBox: true });
    s.addText([
      { text: "digitva.causeofdeathindia.com", options: { bold: true, color: "9FD8D6", breakLine: true } },
      { text: "Central Admin Team, AIIMS New Delhi", options: { color: "A9B7C6" } },
    ], { x: 0.8, y: 5.6, w: 10, h: 0.9, fontFace: FONT, fontSize: 16, margin: 0, isTextBox: true });
  }

  await pres.writeFile({ fileName: `${OUT}/DigitVA_Programme_Overview.pptx` });

  const fig = new pptxgen();
  fig.layout = "LAYOUT_WIDE";
  fig.title = "DigitVA architecture and workflow";
  archSlide(fig, 1);
  flowSlide(fig, 2);
  await fig.writeFile({ fileName: `${OUT}/DigitVA_Architecture_and_Workflow.pptx` });
}

buildDeck().then(() => console.log("built"));
