const pptxgen = require('pptxgenjs');

const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'DigitVA project';
pptx.subject = 'DigitVA architecture and operational workflow';
pptx.title = 'DigitVA architecture and workflow';
pptx.company = 'DigitVA';
pptx.lang = 'en-US';
pptx.theme = {
  headFontFace: 'Aptos Display',
  bodyFontFace: 'Aptos',
  lang: 'en-US',
};
pptx.defineSlideMaster({
  title: 'DIGITVA',
  background: { color: 'F7F9FC' },
  objects: [
    { rect: { x: 0, y: 0, w: 13.333, h: 0.12, fill: { color: '159A9C' }, line: { color: '159A9C' } } },
    { text: { text: 'DigitVA', options: { x: 11.6, y: 7.12, w: 1.1, h: 0.18, fontFace: 'Aptos', fontSize: 8, color: '667085', align: 'right', margin: 0 } } },
  ],
  slideNumber: { x: 12.75, y: 7.1, color: '667085', fontFace: 'Aptos', fontSize: 8 },
});

const C = {
  navy: '16324F', teal: '159A9C', aqua: 'DFF4F3', blue: 'DCEAF7',
  orange: 'F6A03D', orangeLite: 'FDEBD3', green: '2F855A', greenLite: 'E3F3EA',
  purple: '6B5CA5', purpleLite: 'EAE6F5', gray: '667085', pale: 'EEF2F6',
  white: 'FFFFFF', ink: '172B3A', red: 'B54747', redLite: 'F9E3E3',
};

function title(slide, heading, subheading) {
  slide.addText(heading, { x: 0.55, y: 0.35, w: 12.2, h: 0.45, fontSize: 24, bold: true, color: C.navy, margin: 0 });
  slide.addText(subheading, { x: 0.55, y: 0.88, w: 12.1, h: 0.34, fontSize: 11.5, color: C.gray, margin: 0 });
}

function box(slide, x, y, w, h, heading, body, fill, line = C.white, opts = {}) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.08,
    fill: { color: fill }, line: { color: line, width: opts.lineWidth || 1.1 },
    shadow: opts.shadow === false ? undefined : { type: 'outer', color: 'B8C4D0', opacity: 0.18, blur: 1, angle: 45, distance: 1 },
  });
  slide.addText(heading, { x: x + 0.14, y: y + 0.11, w: w - 0.28, h: 0.25, fontSize: opts.headSize || 12.5, bold: true, color: opts.headColor || C.navy, align: opts.align || 'center', margin: 0, fit: 'shrink' });
  if (body) slide.addText(body, { x: x + 0.14, y: y + 0.43, w: w - 0.28, h: h - 0.52, fontSize: opts.bodySize || 9.2, color: opts.bodyColor || C.ink, align: opts.align || 'center', valign: 'mid', margin: 0.03, breakLine: false, fit: 'shrink' });
}

function arrow(slide, x, y, w, h, color = C.teal, end = 'triangle') {
  slide.addShape(pptx.ShapeType.line, { x, y, w, h, line: { color, width: 2, beginArrowType: 'none', endArrowType: end } });
}

function arrowLeft(slide, x, y, w, color = C.teal) {
  slide.addShape(pptx.ShapeType.line, { x, y, w, h: 0, line: { color, width: 2, beginArrowType: 'triangle', endArrowType: 'none' } });
}

function pill(slide, x, y, w, text, fill, color = C.navy) {
  slide.addShape(pptx.ShapeType.roundRect, { x, y, w, h: 0.34, rectRadius: 0.15, fill: { color: fill }, line: { color: fill } });
  slide.addText(text, { x: x + 0.06, y: y + 0.07, w: w - 0.12, h: 0.17, fontSize: 8.5, bold: true, color, align: 'center', margin: 0, fit: 'shrink' });
}

// Slide 1: architecture / concept diagram
{
  const s = pptx.addSlide('DIGITVA');
  title(s, 'DigitVA architecture and concept model', 'An open, auditable platform joining VA collection, computer-coded evidence and physician-authorised cause assignment');

  s.addText('INPUT CHANNELS', { x: 0.55, y: 1.38, w: 2.15, h: 0.22, fontSize: 9, bold: true, color: C.gray, charSpacing: 1.4, margin: 0 });
  box(s, 0.55, 1.72, 2.05, 0.82, 'WHO VA forms', 'ODK Central\nMultilingual interviews', C.blue);
  box(s, 0.55, 2.73, 2.05, 0.82, 'Additional forms', 'SmartVA-compatible and\nprogramme-specific profiles', C.purpleLite);
  box(s, 0.55, 3.74, 2.05, 0.82, 'Health-system intake', 'Death register and direct\nweb-based notification', C.greenLite);

  s.addText('DIGITVA CORE', { x: 3.15, y: 1.38, w: 6.8, h: 0.22, fontSize: 9, bold: true, color: C.gray, charSpacing: 1.4, margin: 0 });
  s.addShape(pptx.ShapeType.roundRect, { x: 3.05, y: 1.65, w: 6.65, h: 3.75, rectRadius: 0.09, fill: { color: 'FFFFFF', transparency: 5 }, line: { color: 'B8CBD9', width: 1.4 } });
  box(s, 3.3, 1.92, 1.8, 1.05, 'Intake + lineage', 'Incremental sync\nPayload versions\nAttachment integrity', C.aqua, C.teal, { bodySize: 8.6 });
  box(s, 5.43, 1.92, 1.8, 1.05, 'CCVA evidence', 'SmartVA processing\nLikelihoods + provenance', C.orangeLite, C.orange, { bodySize: 8.6 });
  box(s, 7.56, 1.92, 1.8, 1.05, 'Single PCVA', 'WHO-form evidence\nICD search\nPhysician decision', C.blue, '6C9FC8', { bodySize: 8.6 });
  arrow(s, 5.1, 2.44, 0.31, 0);
  arrow(s, 7.23, 2.44, 0.31, 0);

  box(s, 3.3, 3.35, 1.8, 1.05, 'Workflow state', 'Allocations\nQueues + events\nIdempotent retries', C.pale, 'A8B4C2', { bodySize: 8.6 });
  box(s, 5.43, 3.35, 1.8, 1.05, 'Targeted review', 'Quality assurance\nRecoding episodes\nFinal authority', C.purpleLite, C.purple, { bodySize: 8.6 });
  box(s, 7.56, 3.35, 1.8, 1.05, 'Mortality intelligence', 'Cause groups\nDashboards\nScoped exports', C.greenLite, C.green, { bodySize: 8.6 });
  arrow(s, 5.1, 3.87, 0.31, 0, C.purple);
  arrow(s, 7.23, 3.87, 0.31, 0, C.green);
  arrow(s, 8.46, 2.99, 0, 0.33, C.teal);

  pill(s, 3.35, 4.72, 1.75, 'Role + scope access', C.blue);
  pill(s, 5.22, 4.72, 1.55, 'Audit trail', C.orangeLite);
  pill(s, 6.89, 4.72, 2.03, 'PII-aware security', C.redLite, C.red);

  s.addText('OUTPUTS + USERS', { x: 10.25, y: 1.38, w: 2.5, h: 0.22, fontSize: 9, bold: true, color: C.gray, charSpacing: 1.4, margin: 0 });
  box(s, 10.2, 1.72, 2.55, 0.82, 'Authorised cause of death', 'ICD-10 now • ICD-11 transition', C.greenLite, C.green);
  box(s, 10.2, 2.73, 2.55, 0.82, 'Programme operations', 'Medical colleges • HDSS sites\nResearch networks', C.blue, '6C9FC8');
  box(s, 10.2, 3.74, 2.55, 0.82, 'Health-system action', 'District intelligence\nPlanning and surveillance', C.orangeLite, C.orange);

  arrow(s, 2.6, 2.13, 0.43, 0, C.teal);
  arrow(s, 2.6, 3.14, 0.43, -0.25, C.purple);
  arrow(s, 2.6, 4.15, 0.43, -0.7, C.green);
  arrow(s, 9.7, 2.44, 0.48, -0.31, C.green);
  arrow(s, 9.7, 3.16, 0.48, 0, C.teal);
  arrow(s, 9.7, 3.88, 0.48, 0.27, C.orange);

  s.addShape(pptx.ShapeType.roundRect, { x: 0.55, y: 5.85, w: 12.2, h: 0.78, rectRadius: 0.06, fill: { color: C.navy }, line: { color: C.navy } });
  s.addText('OPEN PLATFORM', { x: 0.8, y: 6.05, w: 1.3, h: 0.2, fontSize: 9.5, bold: true, color: C.white, charSpacing: 1.2, margin: 0 });
  s.addText('Flask web application', { x: 2.25, y: 6.03, w: 1.6, h: 0.22, fontSize: 10, bold: true, color: C.white, align: 'center', margin: 0 });
  s.addText('PostgreSQL', { x: 4.05, y: 6.03, w: 1.15, h: 0.22, fontSize: 10, bold: true, color: C.white, align: 'center', margin: 0 });
  s.addText('Celery + Redis', { x: 5.55, y: 6.03, w: 1.4, h: 0.22, fontSize: 10, bold: true, color: C.white, align: 'center', margin: 0 });
  s.addText('Docker deployment', { x: 7.3, y: 6.03, w: 1.6, h: 0.22, fontSize: 10, bold: true, color: C.white, align: 'center', margin: 0 });
  s.addText('MIT licensed • GitHub', { x: 9.3, y: 6.03, w: 1.65, h: 0.22, fontSize: 10, bold: true, color: '7FE1D1', align: 'center', margin: 0 });
  s.addText('LLM gateway (future)', { x: 11.05, y: 6.03, w: 1.45, h: 0.22, fontSize: 10, bold: true, color: 'FFD596', align: 'center', margin: 0, fit: 'shrink' });
}

// Slide 2: operational flowchart
{
  const s = pptx.addSlide('DIGITVA');
  title(s, 'From death notification to mortality intelligence', 'Current workflow plus the planned shift from periodic batches to near-real-time, health-system operation');

  const steps = [
    ['1', 'Death notification', 'Register or match\na community death', C.greenLite, C.green],
    ['2', 'VA interview', 'WHO or supported\nform profile', C.blue, '6C9FC8'],
    ['3', 'Intake', 'ODK sync or\ndirect web entry', C.aqua, C.teal],
    ['4', 'Validate + version', 'Identity, completeness,\nattachments, lineage', C.pale, 'A8B4C2'],
    ['5', 'CCVA processing', 'SmartVA evidence\nwith provenance', C.orangeLite, C.orange],
  ];
  const x0 = 0.5, y1 = 1.7, w = 2.14, h = 1.18, gap = 0.34;
  steps.forEach((st, i) => {
    const x = x0 + i * (w + gap);
    s.addShape(pptx.ShapeType.ellipse, { x: x + 0.12, y: y1 - 0.17, w: 0.42, h: 0.42, fill: { color: st[4] }, line: { color: C.white, width: 1 } });
    s.addText(st[0], { x: x + 0.12, y: y1 - 0.08, w: 0.42, h: 0.16, fontSize: 10, bold: true, color: C.white, align: 'center', margin: 0 });
    box(s, x, y1, w, h, st[1], st[2], st[3], st[4], { bodySize: 9.2 });
    if (i < steps.length - 1) arrow(s, x + w, y1 + 0.59, gap - 0.02, 0, st[4]);
  });

  arrow(s, 11.2, 2.9, 0, 0.52, C.orange);

  const row2 = [
    ['9', 'Use the data', 'Dashboards, exports, cause groups and health-system feedback', C.orangeLite, C.orange],
    ['8', 'Final cause', 'Physician-authorised ICD decision with preserved evidence and audit trail', C.greenLite, C.green],
    ['7', 'Targeted review?', 'Only for QA, escalation or programme rules — not routine dual PCVA', C.purpleLite, C.purple],
    ['6', 'Single physician coding', 'Reviews WHO-form evidence, narrative, medical information and CCVA output', C.blue, '6C9FC8'],
  ];
  const y2 = 3.68, w2 = 2.72, gap2 = 0.35;
  row2.forEach((st, i) => {
    const x = 0.5 + i * (w2 + gap2);
    s.addShape(pptx.ShapeType.ellipse, { x: x + 0.12, y: y2 - 0.17, w: 0.42, h: 0.42, fill: { color: st[4] }, line: { color: C.white, width: 1 } });
    s.addText(st[0], { x: x + 0.12, y: y2 - 0.08, w: 0.42, h: 0.16, fontSize: 10, bold: true, color: C.white, align: 'center', margin: 0 });
    box(s, x, y2, w2, 1.25, st[1], st[2], st[3], st[4], { bodySize: 8.9 });
    if (i < row2.length - 1) arrowLeft(s, x + w2, y2 + 0.62, gap2 - 0.02, row2[i + 1][4]);
  });

  s.addShape(pptx.ShapeType.roundRect, { x: 0.52, y: 5.55, w: 7.75, h: 0.86, rectRadius: 0.06, fill: { color: C.redLite }, line: { color: 'D89B9B', width: 1.2, dash: 'dash' } });
  s.addText('DATA-CHANGE SAFETY LOOP', { x: 0.72, y: 5.72, w: 1.75, h: 0.18, fontSize: 9, bold: true, color: C.red, charSpacing: 1, margin: 0 });
  s.addText('Upstream interview changes create a pending payload version → data manager reviews differences → retain the current decision or initiate protected recoding. No silent overwrite.', { x: 2.45, y: 5.65, w: 5.56, h: 0.42, fontSize: 9.4, color: C.ink, margin: 0, fit: 'shrink' });
  arrow(s, 5.3, 5.53, 0, -0.56, C.red);

  s.addShape(pptx.ShapeType.roundRect, { x: 8.62, y: 5.55, w: 4.2, h: 0.86, rectRadius: 0.06, fill: { color: C.navy }, line: { color: C.navy } });
  s.addText('BATCH → NEAR REAL TIME', { x: 8.83, y: 5.72, w: 1.85, h: 0.18, fontSize: 9, bold: true, color: '7FE1D1', charSpacing: 0.8, margin: 0 });
  s.addText('Delta checks • bounded queues • visible exceptions • idempotent retries • direct intake', { x: 10.7, y: 5.64, w: 1.88, h: 0.44, fontSize: 8.7, color: C.white, margin: 0, fit: 'shrink' });

  s.addText('Future safeguards: human confirmation for any LLM-assisted summary • minimum necessary data • model and prompt provenance • ICD release identifiers', { x: 0.65, y: 6.72, w: 12.0, h: 0.25, fontSize: 9.2, italic: true, color: C.gray, align: 'center', margin: 0 });
}

pptx.writeFile({ fileName: 'docs/manuscript/DigitVA_Architecture_and_Workflow.pptx' });
