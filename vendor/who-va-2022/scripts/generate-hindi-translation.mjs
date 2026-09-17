import { readFile, writeFile } from "node:fs/promises";

const sourcePath = new URL("../src/generated/who-va-2022.instrument.json", import.meta.url);
const targetLocale = process.argv[2] ?? "hi";
const languageConfig = {
  hi: {
    name: "Hindi",
    attachment: [
      "चिकित्सा प्रमाणपत्र अपलोड करें (चित्र या PDF)",
      "JPEG या PNG चित्र अथवा PDF दस्तावेज़ चुनें।"
    ],
    ui: {
      sectionProgress: "अनुभाग {current} / {total}",
      back: "वापस",
      saveDraft: "प्रारूप सहेजें",
      saving: "सहेजा जा रहा है…",
      next: "आगे",
      complete: "पूरा करें",
      draftSaved: "प्रारूप सहेजा गया · {id}",
      draftSaveFailed: "प्रारूप सहेजा नहीं जा सका",
      draftId: "प्रारूप आईडी · {id}",
      required: "{label} आवश्यक है",
      invalidType: "{name} के लिए मान्य {dataType} मान दर्ज करें",
      invalidChoice: "{name} में WHO की विकल्प सूची से बाहर का मान है",
      invalidConstraint: "{name} WHO की शर्त पूरी नहीं करता",
      fourDigitYear: "चार अंकों का वर्ष दर्ज करें, उदाहरण: 2026",
      invalidDate: "तारीख {format} के रूप में दर्ज करें, उदाहरण: {example}",
      openingCalendar: "कैलेंडर खोला जा रहा है…",
      selectDate: "तारीख चुनें",
      confirm: "पुष्टि करें",
      confirmed: "पुष्टि हो गई",
      answeredQuestions: "{count} प्रश्नों के उत्तर दिए गए",
      answerPreview: "उत्तर पूर्वावलोकन",
      previewIntro: "अब तक दर्ज उत्तरों की समीक्षा करें। बदलाव करने के लिए प्रपत्र पर वापस जाएँ।",
      noAnswers: "अभी तक कोई उत्तर दर्ज नहीं किया गया है।",
      backToForm: "प्रपत्र पर वापस जाएँ",
      previewAnswers: "उत्तरों का पूर्वावलोकन",
      yes: "हाँ",
      no: "नहीं",
      recorded: "दर्ज किया गया"
    }
  },
  fr: {
    name: "French",
    attachment: [
      "Téléverser le certificat médical (image ou PDF)",
      "Choisissez une image JPEG ou PNG, ou un document PDF."
    ],
    ui: {
      sectionProgress: "Section {current} sur {total}",
      back: "Retour",
      saveDraft: "Enregistrer le brouillon",
      saving: "Enregistrement…",
      next: "Suivant",
      complete: "Terminer",
      draftSaved: "Brouillon enregistré · {id}",
      draftSaveFailed: "Le brouillon n’a pas pu être enregistré",
      draftId: "ID du brouillon · {id}",
      required: "{label} est obligatoire",
      invalidType: "{name} doit être une valeur {dataType} valide",
      invalidChoice: "{name} contient une valeur absente de la liste de choix de l’OMS",
      invalidConstraint: "{name} ne respecte pas la contrainte de l’OMS",
      fourDigitYear: "Saisissez une année à quatre chiffres, par exemple 2026",
      invalidDate: "Saisissez la date au format {format}, par exemple {example}",
      openingCalendar: "Ouverture du calendrier…",
      selectDate: "Sélectionner une date",
      confirm: "Confirmer",
      confirmed: "Confirmé",
      answeredQuestions: "{count} questions répondues",
      answerPreview: "Aperçu des réponses",
      previewIntro: "Vérifiez les réponses saisies jusqu’ici. Revenez au formulaire pour les modifier.",
      noAnswers: "Aucune réponse n’a encore été saisie.",
      backToForm: "Retour au formulaire",
      previewAnswers: "Aperçu des réponses",
      yes: "Oui",
      no: "Non",
      recorded: "Enregistré"
    }
  }
};
const config = languageConfig[targetLocale];
if (!config) throw new Error(`Unsupported locale: ${targetLocale}`);
const outputPath = new URL(`../src/languages/${targetLocale}.ts`, import.meta.url);
const instrument = JSON.parse(await readFile(sourcePath, "utf8"));

function plainText(value) {
  return value
    .replace(/<br\s*\/?\s*>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .trim();
}

function protectPlaceholders(value) {
  const placeholders = [];
  const protectedText = value.replace(
    /\$\{[^}]+\}|\{(?:current|total|count|id|label|name|dataType|format|example)\}|\bId\d+[A-Za-z_]*\b/g,
    (match) => {
      const index = placeholders.push(match) - 1;
      return `\uE000${index}\uE001`;
    }
  );
  return { protectedText, placeholders };
}

async function translate(value, attempt = 1) {
  const text = plainText(value);
  if (!text) return "";
  const { protectedText, placeholders } = protectPlaceholders(text);
  const url = new URL("https://translate.googleapis.com/translate_a/single");
  url.search = new URLSearchParams({
    client: "gtx",
    sl: "en",
    tl: targetLocale,
    dt: "t",
    q: protectedText
  }).toString();
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body = await response.json();
    const translated = body[0].map((segment) => segment[0] ?? "").join("");
    return translated.replace(/\uE000(\d+)\uE001/g, (_match, index) => placeholders[Number(index)] ?? _match);
  } catch (error) {
    if (attempt >= 5) throw error;
    await new Promise((resolve) => setTimeout(resolve, attempt * 750));
    return translate(value, attempt + 1);
  }
}

const strings = [];
for (const section of instrument.sections) if (section.label?.en) strings.push(section.label.en);
for (const question of instrument.questions) {
  for (const field of ["label", "hint", "guidance", "constraintMessage"])
    if (question[field]?.en) strings.push(question[field].en);
  for (const choice of question.choices ?? []) if (choice.label?.en) strings.push(choice.label.en);
}
const uniqueStrings = [...new Set(strings)];
const translated = new Map();
let nextIndex = 0;
await Promise.all(
  Array.from({ length: 8 }, async () => {
    while (nextIndex < uniqueStrings.length) {
      const index = nextIndex++;
      const source = uniqueStrings[index];
      translated.set(source, await translate(source));
      if ((index + 1) % 50 === 0 || index + 1 === uniqueStrings.length)
        process.stdout.write(`Translated ${index + 1}/${uniqueStrings.length}\n`);
    }
  })
);

const sections = Object.fromEntries(
  instrument.sections.flatMap((section) =>
    section.label?.en ? [[section.name, translated.get(section.label.en)]] : []
  )
);
const questions = Object.fromEntries(
  instrument.questions.map((question) => {
    const result = {};
    for (const field of ["label", "hint", "guidance", "constraintMessage"])
      if (question[field]?.en) result[field] = translated.get(question[field].en);
    const choices = Object.fromEntries(
      (question.choices ?? []).flatMap((choice) =>
        choice.label?.en
          ? [[choice.value, plainText(choice.label[targetLocale] ?? translated.get(choice.label.en))]]
          : []
      )
    );
    if (Object.keys(choices).length) result.choices = choices;
    return [question.name, result];
  })
);
questions.custom_medical_certificate_upload = { label: config.attachment[0], hint: config.attachment[1] };

const languageFile = { locale: targetLocale, instrument: { sections, questions }, ui: config.ui };
const output = `/**\n * Machine-generated ${config.name} draft for UI evaluation. Clinical and field terminology\n * must be reviewed by fluent verbal-autopsy specialists before production use.\n */\nimport type { WhoVaLanguageFile } from "../i18n.js";\n\nexport default ${JSON.stringify(languageFile, null, 2)} satisfies WhoVaLanguageFile;\n`;
await writeFile(outputPath, output);
