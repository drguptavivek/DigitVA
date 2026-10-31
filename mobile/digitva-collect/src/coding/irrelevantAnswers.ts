/**
 * The answers the server keeps when it takes an interview: app/services/web_form_relevance_service.py
 * strip_irrelevant_answers, on the form engine's own expression evaluator. Offline coding renders these, so the
 * coder sees on the phone what the server will show (docs/policy/doris-cod-workflow.md, "Offline coding workspace").
 */
import {
  createWhoVa2022Instrument,
  evaluateExpression,
  parseExpression,
  type AnswerValue,
  type ExpressionNode,
  type InstrumentDefinition,
} from "@drguptavivek/who-2022-va";

/**
 * `data` without the answers to questions that are not relevant, resolved to a fixed point as the server does
 * (dropping an answer can make another question irrelevant: md_available -> md_count -> md_im1..30). Calculations
 * and relevance are evaluated at `now` (today()). A calculation or relevance that fails to evaluate keeps the
 * answer, as on the server, which only ever strips.
 */
export function stripIrrelevantAnswers(instrument: InstrumentDefinition, data: Record<string, unknown>, now: Date): Record<string, unknown> {
  const asts = new Map<string, ExpressionNode>();
  const ast = (source: string) => {
    let node = asts.get(source);
    if (!node) asts.set(source, node = parseExpression(source));
    return node;
  };
  const sections = new Map(instrument.sections.map((section) => [section.name, section]));
  const options = { now };
  const current: Record<string, unknown> = { ...data };
  for (;;) {
    const calculated = { ...current } as Record<string, AnswerValue | undefined>;
    for (const question of instrument.questions) {
      if (!question.calculation) continue;
      try {
        calculated[question.name] = evaluateExpression(ast(question.calculation.source), calculated, options) as AnswerValue;
      } catch {
        // The server logs and goes on with the next calculation.
      }
    }
    const holds = (source: string | undefined) => !source || !!evaluateExpression(ast(source), calculated, options);
    const sectionHolds = new Map<string, boolean>();
    const removed: string[] = [];
    for (const question of instrument.questions) {
      if (question.control === "system" || !Object.hasOwn(current, question.name)) continue;
      try {
        let relevant = true;
        for (const name of question.sectionPath) {
          let verdict = sectionHolds.get(name);
          if (verdict === undefined) sectionHolds.set(name, verdict = holds(sections.get(name)?.relevant?.source));
          if (!verdict) { relevant = false; break; }
        }
        if (relevant && !holds(question.relevant?.source)) relevant = false;
        if (!relevant) removed.push(question.name);
      } catch {
        // Fail safe, as the server: an evaluation error keeps the answer.
      }
    }
    if (!removed.length) return current;
    for (const name of removed) delete current[name];
  }
}

/**
 * The layers the server strips a submitted draft with: every DigitVA extension, whatever the project enables
 * (vendor/who-va-2022/src/digitva-extension.ts ALL_DIGITVA_EXTENSIONS, which the package does not export).
 * A served form version is judged by its recorded definition, the composed one
 * (tooling/who-va-2022/build-composed-instrument.mjs, WHO overrides on); any other version by the server
 * instrument (build-server-instrument.mjs, WHO overrides off). See web_form_relevance_service._rules_for.
 */
const SERVER_LAYERS = [
  "digitva_core", "social_autopsy", "intake_screen", "geography", "narration_language",
  "death_summary", "medical_records", "abha", "doris_support_whova_2022", "equity",
] as const;
/** web_intake_service._COMPOSED_VERSION_RE: a version the server served (and recorded). */
const COMPOSED_VERSION = /^\d+-[0-9a-f]{10}$/;
const serverInstruments = new Map<boolean, InstrumentDefinition>();

/** The instrument the server would strip a draft filled on `instrumentVersion` with. */
export function serverStripInstrument(instrumentVersion: unknown): InstrumentDefinition {
  const served = typeof instrumentVersion === "string" && COMPOSED_VERSION.test(instrumentVersion.trim());
  let instrument = serverInstruments.get(served);
  if (!instrument) serverInstruments.set(served, instrument = createWhoVa2022Instrument(SERVER_LAYERS, { whoOverrides: served }));
  return instrument;
}

/** The answers the server keeps when this draft is submitted (web_intake_service.build_final_payload). */
export function serverKeptAnswers(draft: { instrumentVersion?: unknown; data?: Record<string, unknown> }, now: Date): Record<string, unknown> {
  return stripIrrelevantAnswers(serverStripInstrument(draft.instrumentVersion), draft.data ?? {}, now);
}
