"""Relabel the machine-translated seed rows from b6d2f4a9c1e7 as 'machine'

Revision ID: c1a4b6e8d3f2
Revises: b6d2f4a9c1e7
Create Date: 2026-09-20

Owner's decision, 2026-09-20: the workbook-imported translations are
approved; the 214 rows b6d2f4a9c1e7 seeded were authored by an LLM, not a
speaker, and need human review. They must stay visible and editable in the
admin panel, and must not be served meanwhile. A locale's approval is
per-locale, not per-row, so the only way to stop serving these rows without
touching the workbook-sourced ones that share the same locale is to give them
a ``source`` value of their own: ``machine`` (see
``app.models.mas_instrument_locales.SOURCE_MACHINE``).

This migration does not import b6d2f4a9c1e7 -- migrations must not import each
other's code (docs/policy/migration-chaining.md) -- so ``SEED_ROWS`` below is
the same literal tuple, copied. It matches on locale, item, field **and
text**, and only rows still ``source='imported'``, exactly as
b6d2f4a9c1e7.downgrade() does: a row an administrator has already corrected
is ``edited`` and is skipped by the source filter, and a row whose text no
longer matches the literal seeded here was changed by someone and is skipped
by the text filter. Both are left standing.

Reversible: downgrade relabels 'machine' back to 'imported' under the same
three-way match.
"""

import sqlalchemy as sa
from alembic import op

revision = 'c1a4b6e8d3f2'
down_revision = 'b6d2f4a9c1e7'
branch_labels = None
depends_on = None

INSTRUMENT_CODE = "WHO_2022_VA"

#: (locale_code, item_kind, item_key, field, text) -- copied verbatim from
#: b6d2f4a9c1e7.SEED_ROWS. Do not edit that migration to keep this in sync;
#: edit both if the seeded strings themselves are ever corrected there.
SEED_ROWS = (
    ('ar', 'choice', 'CONSENT_MODE/in_person', 'label', 'شخصياً'),
    ('ar', 'choice', 'CONSENT_MODE/telephonic', 'label', 'هاتفياً'),
    ('ar', 'choice', 'language/bangla', 'label', 'البنغالية'),
    ('ar', 'choice', 'language/english', 'label', 'الإنجليزية'),
    ('ar', 'choice', 'language/hindi', 'label', 'الهندية'),
    ('ar', 'choice', 'language/kannada', 'label', 'الكانادية'),
    ('ar', 'choice', 'language/malayalam', 'label', 'المالايالامية'),
    ('ar', 'choice', 'language/marathi', 'label', 'المهاراتية'),
    ('ar', 'question', 'consent_mode', 'label', 'الطريقة التي تم بها الحصول على الموافقة'),
    ('ar', 'question', 'custom_medical_certificate_upload', 'hint', 'اختر صورة JPEG أو PNG، أو مستند PDF.'),
    ('ar', 'question', 'custom_medical_certificate_upload', 'label', 'تحميل الشهادة الطبية (صورة أو PDF)'),
    ('ar', 'question', 'digitva_documents', 'label', 'المستندات الطبية ومستندات الوفاة'),
    ('ar', 'question', 'ds_count', 'hint', '0 إلى 5'),
    ('ar', 'question', 'imagenarr', 'label', '(التقاط صورة للسرد) صورة للسرد المكتوب، إذا تم تسجيل السرد على ورق'),
    ('ar', 'question', 'md_count', 'hint', '0 إلى 30'),
    ('ar', 'question', 'narr_language', 'label', 'لغة السرد'),
    ('bn', 'choice', 'CONSENT_MODE/in_person', 'label', 'সশরীরে'),
    ('bn', 'choice', 'CONSENT_MODE/telephonic', 'label', 'টেলিফোনে'),
    ('bn', 'choice', 'language/bangla', 'label', 'বাংলা'),
    ('bn', 'choice', 'language/english', 'label', 'ইংরেজি'),
    ('bn', 'choice', 'language/hindi', 'label', 'হিন্দি'),
    ('bn', 'choice', 'language/kannada', 'label', 'কন্নড়'),
    ('bn', 'choice', 'language/malayalam', 'label', 'মালয়ালম'),
    ('bn', 'choice', 'language/marathi', 'label', 'মারাঠি'),
    ('bn', 'question', 'abha_address', 'hint', 'যেমন: name@abdm'),
    ('bn', 'question', 'abha_address', 'label', 'মৃত ব্যক্তির ABHA ঠিকানা, জানা থাকলে'),
    ('bn', 'question', 'abha_number', 'hint', 'আয়ুষ্মান ভারত হেলথ অ্যাকাউন্ট নম্বর, যেমন: 12-3456-7890-1234'),
    ('bn', 'question', 'abha_number', 'label', 'মৃত ব্যক্তির ABHA নম্বর (14 সংখ্যা), জানা থাকলে'),
    ('bn', 'question', 'consent_mode', 'label', 'কোন পদ্ধতিতে সম্মতি নেওয়া হয়েছে'),
    ('bn', 'question', 'custom_medical_certificate_upload', 'hint', 'একটি JPEG বা PNG ছবি, অথবা একটি PDF নথি নির্বাচন করুন।'),
    ('bn', 'question', 'custom_medical_certificate_upload', 'label', 'চিকিৎসা সনদ আপলোড করুন (ছবি বা PDF)'),
    ('bn', 'question', 'digitva_documents', 'label', 'চিকিৎসা ও মৃত্যু সংক্রান্ত নথি'),
    ('bn', 'question', 'ds_count', 'hint', '0 থেকে 5'),
    ('bn', 'question', 'imagenarr', 'label', '(বিবরণের জন্য ছবি তুলুন) লিখিত বিবরণের ছবি, যদি বিবরণ কাগজে লেখা হয়ে থাকে'),
    ('bn', 'question', 'md_count', 'hint', '0 থেকে 30'),
    ('bn', 'question', 'narr_language', 'label', 'বিবরণের ভাষা'),
    ('es', 'choice', 'CONSENT_MODE/in_person', 'label', 'En persona'),
    ('es', 'choice', 'CONSENT_MODE/telephonic', 'label', 'Por teléfono'),
    ('es', 'choice', 'language/bangla', 'label', 'Bengalí'),
    ('es', 'choice', 'language/english', 'label', 'Inglés'),
    ('es', 'choice', 'language/kannada', 'label', 'Canarés'),
    ('es', 'choice', 'language/marathi', 'label', 'Maratí'),
    ('es', 'question', 'consent_mode', 'label', 'Modo en que se obtuvo el consentimiento'),
    ('es', 'question', 'custom_medical_certificate_upload', 'hint', 'Elija una imagen JPEG o PNG, o un documento PDF.'),
    ('es', 'question', 'custom_medical_certificate_upload', 'label', 'Cargar el certificado médico (imagen o PDF)'),
    ('es', 'question', 'digitva_documents', 'label', 'Documentos médicos y de defunción'),
    ('es', 'question', 'ds_count', 'hint', '0 a 5'),
    ('es', 'question', 'imagenarr', 'label', '(Capturar imagen para el relato) Fotografía del relato escrito, si el relato se registró en papel'),
    ('es', 'question', 'md_count', 'hint', '0 a 30'),
    ('es', 'question', 'narr_language', 'label', 'Idioma del relato'),
    ('fr', 'choice', 'CONSENT_MODE/in_person', 'label', 'En personne'),
    ('fr', 'choice', 'CONSENT_MODE/telephonic', 'label', 'Par téléphone'),
    ('fr', 'choice', 'language/bangla', 'label', 'Bengali'),
    ('fr', 'choice', 'language/english', 'label', 'Anglais'),
    ('fr', 'question', 'consent_mode', 'label', "Mode d'obtention du consentement"),
    ('fr', 'question', 'custom_medical_certificate_upload', 'hint', 'Choisissez une image JPEG ou PNG, ou un document PDF.'),
    ('fr', 'question', 'custom_medical_certificate_upload', 'label', 'Téléverser le certificat médical (image ou PDF)'),
    ('fr', 'question', 'digitva_documents', 'label', 'Documents médicaux et documents de décès'),
    ('fr', 'question', 'ds_count', 'hint', '0 à 5'),
    ('fr', 'question', 'imagenarr', 'label', '(Prendre une photo pour le récit) Photographie du récit écrit, si le récit a été consigné sur papier'),
    ('fr', 'question', 'md_count', 'hint', '0 à 30'),
    ('fr', 'question', 'narr_language', 'label', 'Langue du récit'),
    ('hi', 'choice', 'CONSENT_MODE/in_person', 'label', 'व्यक्तिगत रूप से'),
    ('hi', 'choice', 'CONSENT_MODE/telephonic', 'label', 'टेलीफोन द्वारा'),
    ('hi', 'choice', 'language/bangla', 'label', 'बंगाली'),
    ('hi', 'choice', 'language/english', 'label', 'अंग्रेज़ी'),
    ('hi', 'choice', 'language/hindi', 'label', 'हिन्दी'),
    ('hi', 'choice', 'language/kannada', 'label', 'कन्नड़'),
    ('hi', 'choice', 'language/malayalam', 'label', 'मलयालम'),
    ('hi', 'choice', 'language/marathi', 'label', 'मराठी'),
    ('hi', 'question', 'abha_address', 'hint', 'उदाहरण: name@abdm'),
    ('hi', 'question', 'abha_address', 'label', 'मृतक का ABHA पता, यदि ज्ञात हो'),
    ('hi', 'question', 'abha_number', 'hint', 'आयुष्मान भारत हेल्थ अकाउंट नंबर, उदाहरण: 12-3456-7890-1234'),
    ('hi', 'question', 'abha_number', 'label', 'मृतक का ABHA नंबर (14 अंक), यदि ज्ञात हो'),
    ('hi', 'question', 'consent_mode', 'label', 'सहमति किस माध्यम से ली गई'),
    ('hi', 'question', 'custom_medical_certificate_upload', 'hint', 'JPEG या PNG छवि, या PDF दस्तावेज़ चुनें।'),
    ('hi', 'question', 'custom_medical_certificate_upload', 'label', 'चिकित्सा प्रमाणपत्र अपलोड करें (छवि या PDF)'),
    ('hi', 'question', 'digitva_documents', 'label', 'चिकित्सा और मृत्यु से संबंधित दस्तावेज़'),
    ('hi', 'question', 'ds_count', 'hint', '0 से 5'),
    ('hi', 'question', 'imagenarr', 'label', '(विवरण के लिए छवि लें) लिखित विवरण का फोटो, यदि विवरण कागज़ पर दर्ज किया गया था'),
    ('hi', 'question', 'md_count', 'hint', '0 से 30'),
    ('hi', 'question', 'narr_language', 'label', 'विवरण की भाषा'),
    ('kn', 'choice', 'CONSENT_MODE/in_person', 'label', 'ಮುಖಾಮುಖಿ'),
    ('kn', 'choice', 'CONSENT_MODE/telephonic', 'label', 'ದೂರವಾಣಿ ಮೂಲಕ'),
    ('kn', 'choice', 'language/bangla', 'label', 'ಬಂಗಾಳಿ'),
    ('kn', 'choice', 'language/english', 'label', 'ಇಂಗ್ಲಿಷ್'),
    ('kn', 'choice', 'language/hindi', 'label', 'ಹಿಂದಿ'),
    ('kn', 'choice', 'language/kannada', 'label', 'ಕನ್ನಡ'),
    ('kn', 'choice', 'language/malayalam', 'label', 'ಮಲಯಾಳಂ'),
    ('kn', 'choice', 'language/marathi', 'label', 'ಮರಾಠಿ'),
    ('kn', 'question', 'abha_address', 'hint', 'ಉದಾ. name@abdm'),
    ('kn', 'question', 'abha_address', 'label', 'ಮೃತರ ABHA ವಿಳಾಸ, ತಿಳಿದಿದ್ದರೆ'),
    ('kn', 'question', 'abha_number', 'hint', 'ಆಯುಷ್ಮಾನ್ ಭಾರತ್ ಹೆಲ್ತ್ ಅಕೌಂಟ್ ಸಂಖ್ಯೆ, ಉದಾ. 12-3456-7890-1234'),
    ('kn', 'question', 'abha_number', 'label', 'ಮೃತರ ABHA ಸಂಖ್ಯೆ (14 ಅಂಕಿ), ತಿಳಿದಿದ್ದರೆ'),
    ('kn', 'question', 'consent_mode', 'label', 'ಸಮ್ಮತಿಯನ್ನು ಯಾವ ವಿಧಾನದಲ್ಲಿ ಪಡೆಯಲಾಯಿತು'),
    ('kn', 'question', 'custom_medical_certificate_upload', 'hint', 'JPEG ಅಥವಾ PNG ಚಿತ್ರ, ಅಥವಾ PDF ದಾಖಲೆಯನ್ನು ಆಯ್ಕೆಮಾಡಿ.'),
    ('kn', 'question', 'custom_medical_certificate_upload', 'label', 'ವೈದ್ಯಕೀಯ ಪ್ರಮಾಣಪತ್ರವನ್ನು ಅಪ್‌ಲೋಡ್ ಮಾಡಿ (ಚಿತ್ರ ಅಥವಾ PDF)'),
    ('kn', 'question', 'digitva_documents', 'label', 'ವೈದ್ಯಕೀಯ ಮತ್ತು ಮರಣ ದಾಖಲೆಗಳು'),
    ('kn', 'question', 'ds_count', 'hint', '0 ರಿಂದ 5'),
    ('kn', 'question', 'imagenarr', 'label', '(ವಿವರಣೆಗಾಗಿ ಚಿತ್ರ ತೆಗೆಯಿರಿ) ಬರೆದ ವಿವರಣೆಯ ಛಾಯಾಚಿತ್ರ, ವಿವರಣೆಯನ್ನು ಕಾಗದದಲ್ಲಿ ದಾಖಲಿಸಿದ್ದರೆ'),
    ('kn', 'question', 'md_count', 'hint', '0 ರಿಂದ 30'),
    ('kn', 'question', 'narr_language', 'label', 'ವಿವರಣೆಯ ಭಾಷೆ'),
    ('ml', 'choice', 'CONSENT_MODE/in_person', 'label', 'നേരിട്ട്'),
    ('ml', 'choice', 'CONSENT_MODE/telephonic', 'label', 'ടെലിഫോണിലൂടെ'),
    ('ml', 'choice', 'language/bangla', 'label', 'ബംഗാളി'),
    ('ml', 'choice', 'language/english', 'label', 'ഇംഗ്ലീഷ്'),
    ('ml', 'choice', 'language/hindi', 'label', 'ഹിന്ദി'),
    ('ml', 'choice', 'language/kannada', 'label', 'കന്നഡ'),
    ('ml', 'choice', 'language/malayalam', 'label', 'മലയാളം'),
    ('ml', 'choice', 'language/marathi', 'label', 'മറാഠി'),
    ('ml', 'question', 'abha_address', 'hint', 'ഉദാ. name@abdm'),
    ('ml', 'question', 'abha_address', 'label', 'മരിച്ചയാളുടെ ABHA വിലാസം, അറിയാമെങ്കിൽ'),
    ('ml', 'question', 'abha_number', 'hint', 'ആയുഷ്മാൻ ഭാരത് ഹെൽത്ത് അക്കൗണ്ട് നമ്പർ, ഉദാ. 12-3456-7890-1234'),
    ('ml', 'question', 'abha_number', 'label', 'മരിച്ചയാളുടെ ABHA നമ്പർ (14 അങ്കങ്ങൾ), അറിയാമെങ്കിൽ'),
    ('ml', 'question', 'consent_mode', 'label', 'സമ്മതം ഏത് രീതിയിൽ വാങ്ങി'),
    ('ml', 'question', 'custom_medical_certificate_upload', 'hint', 'ഒരു JPEG അല്ലെങ്കിൽ PNG ചിത്രം, അല്ലെങ്കിൽ PDF രേഖ തിരഞ്ഞെടുക്കുക.'),
    ('ml', 'question', 'custom_medical_certificate_upload', 'label', 'മെഡിക്കൽ സർട്ടിഫിക്കറ്റ് അപ്‌ലോഡ് ചെയ്യുക (ചിത്രം അല്ലെങ്കിൽ PDF)'),
    ('ml', 'question', 'digitva_documents', 'label', 'മെഡിക്കൽ, മരണ രേഖകൾ'),
    ('ml', 'question', 'ds_count', 'hint', '0 മുതൽ 5 വരെ'),
    ('ml', 'question', 'imagenarr', 'label', '(വിവരണത്തിനായി ചിത്രം എടുക്കുക) എഴുതിയ വിവരണത്തിന്റെ ഫോട്ടോ, വിവരണം കടലാസിൽ രേഖപ്പെടുത്തിയിട്ടുണ്ടെങ്കിൽ'),
    ('ml', 'question', 'md_count', 'hint', '0 മുതൽ 30 വരെ'),
    ('ml', 'question', 'narr_language', 'label', 'വിവരണത്തിന്റെ ഭാഷ'),
    ('mr', 'choice', 'CONSENT_MODE/in_person', 'label', 'प्रत्यक्ष भेटीत'),
    ('mr', 'choice', 'CONSENT_MODE/telephonic', 'label', 'दूरध्वनीद्वारे'),
    ('mr', 'choice', 'language/bangla', 'label', 'बंगाली'),
    ('mr', 'choice', 'language/english', 'label', 'इंग्रजी'),
    ('mr', 'choice', 'language/hindi', 'label', 'हिंदी'),
    ('mr', 'choice', 'language/kannada', 'label', 'कन्नड'),
    ('mr', 'choice', 'language/malayalam', 'label', 'मलयाळम'),
    ('mr', 'choice', 'language/marathi', 'label', 'मराठी'),
    ('mr', 'question', 'abha_address', 'hint', 'उदा. name@abdm'),
    ('mr', 'question', 'abha_address', 'label', 'मृताचा ABHA पत्ता, माहीत असल्यास'),
    ('mr', 'question', 'abha_number', 'hint', 'आयुष्मान भारत हेल्थ अकाउंट क्रमांक, उदा. 12-3456-7890-1234'),
    ('mr', 'question', 'abha_number', 'label', 'मृताचा ABHA क्रमांक (14 अंक), माहीत असल्यास'),
    ('mr', 'question', 'consent_mode', 'label', 'संमती कोणत्या पद्धतीने घेतली'),
    ('mr', 'question', 'custom_medical_certificate_upload', 'hint', 'JPEG किंवा PNG प्रतिमा, किंवा PDF दस्तऐवज निवडा.'),
    ('mr', 'question', 'custom_medical_certificate_upload', 'label', 'वैद्यकीय प्रमाणपत्र अपलोड करा (प्रतिमा किंवा PDF)'),
    ('mr', 'question', 'digitva_documents', 'label', 'वैद्यकीय आणि मृत्यूसंबंधित दस्तऐवज'),
    ('mr', 'question', 'ds_count', 'hint', '0 ते 5'),
    ('mr', 'question', 'imagenarr', 'label', '(वर्णनासाठी प्रतिमा घ्या) लिखित वर्णनाचा फोटो, वर्णन कागदावर नोंदवले असल्यास'),
    ('mr', 'question', 'md_count', 'hint', '0 ते 30'),
    ('mr', 'question', 'narr_language', 'label', 'वर्णनाची भाषा'),
    ('or', 'choice', 'CONSENT_MODE/in_person', 'label', 'ପ୍ରତ୍ୟକ୍ଷ ଭାବେ'),
    ('or', 'choice', 'CONSENT_MODE/telephonic', 'label', 'ଟେଲିଫୋନ ମାଧ୍ୟମରେ'),
    ('or', 'choice', 'language/bangla', 'label', 'ବଙ୍ଗଳା'),
    ('or', 'choice', 'language/english', 'label', 'ଇଂରାଜୀ'),
    ('or', 'choice', 'language/hindi', 'label', 'ହିନ୍ଦୀ'),
    ('or', 'choice', 'language/kannada', 'label', 'କନ୍ନଡ'),
    ('or', 'choice', 'language/malayalam', 'label', 'ମଲୟାଳମ'),
    ('or', 'choice', 'language/marathi', 'label', 'ମରାଠୀ'),
    ('or', 'question', 'abha_address', 'hint', 'ଉଦାହରଣ: name@abdm'),
    ('or', 'question', 'abha_address', 'label', 'ମୃତଙ୍କ ABHA ଠିକଣା, ଯଦି ଜଣା ଥାଏ'),
    ('or', 'question', 'abha_number', 'hint', 'ଆୟୁଷ୍ମାନ ଭାରତ ହେଲ୍ଥ ଆକାଉଣ୍ଟ ନମ୍ବର, ଉଦାହରଣ: 12-3456-7890-1234'),
    ('or', 'question', 'abha_number', 'label', 'ମୃତଙ୍କ ABHA ନମ୍ବର (14 ଅଙ୍କ), ଯଦି ଜଣା ଥାଏ'),
    ('or', 'question', 'consent_mode', 'label', 'ସମ୍ମତି କେମିତି ନିଆଯାଇଥିଲା'),
    ('or', 'question', 'custom_medical_certificate_upload', 'hint', 'ଏକ JPEG କିମ୍ବା PNG ଛବି, କିମ୍ବା PDF ଡକ୍ୟୁମେଣ୍ଟ ବାଛନ୍ତୁ।'),
    ('or', 'question', 'custom_medical_certificate_upload', 'label', 'ଚିକିତ୍ସା ପ୍ରମାଣପତ୍ର ଅପଲୋଡ କରନ୍ତୁ (ଛବି କିମ୍ବା PDF)'),
    ('or', 'question', 'digitva_documents', 'label', 'ଚିକିତ୍ସା ଏବଂ ମୃତ୍ୟୁ ସମ୍ବନ୍ଧୀୟ ଡକ୍ୟୁମେଣ୍ଟ'),
    ('or', 'question', 'ds_count', 'hint', '0 ରୁ 5'),
    ('or', 'question', 'imagenarr', 'label', '(ବର୍ଣ୍ଣନା ପାଇଁ ଛବି ନିଅନ୍ତୁ) ଲିଖିତ ବର୍ଣ୍ଣନାର ଫଟୋ, ଯଦି ବର୍ଣ୍ଣନା କାଗଜରେ ଲେଖାଯାଇଥିଲା'),
    ('or', 'question', 'md_count', 'hint', '0 ରୁ 30'),
    ('or', 'question', 'narr_language', 'label', 'ବର୍ଣ୍ଣନାର ଭାଷା'),
    ('pt', 'choice', 'CONSENT_MODE/in_person', 'label', 'Presencialmente'),
    ('pt', 'choice', 'CONSENT_MODE/telephonic', 'label', 'Por telefone'),
    ('pt', 'choice', 'language/bangla', 'label', 'Bengali'),
    ('pt', 'choice', 'language/english', 'label', 'Inglês'),
    ('pt', 'choice', 'language/hindi', 'label', 'Híndi'),
    ('pt', 'choice', 'language/kannada', 'label', 'Canarês'),
    ('pt', 'choice', 'language/malayalam', 'label', 'Malaiala'),
    ('pt', 'choice', 'language/marathi', 'label', 'Marati'),
    ('pt', 'question', 'consent_mode', 'label', 'Modo como o consentimento foi obtido'),
    ('pt', 'question', 'custom_medical_certificate_upload', 'hint', 'Escolha uma imagem JPEG ou PNG, ou um documento PDF.'),
    ('pt', 'question', 'custom_medical_certificate_upload', 'label', 'Carregar o certificado médico (imagem ou PDF)'),
    ('pt', 'question', 'digitva_documents', 'label', 'Documentos médicos e de óbito'),
    ('pt', 'question', 'ds_count', 'hint', '0 a 5'),
    ('pt', 'question', 'imagenarr', 'label', '(Capturar imagem para o relato) Fotografia do relato escrito, se o relato foi registado em papel'),
    ('pt', 'question', 'md_count', 'hint', '0 a 30'),
    ('pt', 'question', 'narr_language', 'label', 'Idioma do relato'),
    ('sw', 'choice', 'CONSENT_MODE/in_person', 'label', 'Ana kwa ana'),
    ('sw', 'choice', 'CONSENT_MODE/telephonic', 'label', 'Kwa simu'),
    ('sw', 'choice', 'language/bangla', 'label', 'Kibengali'),
    ('sw', 'choice', 'language/english', 'label', 'Kiingereza'),
    ('sw', 'choice', 'language/hindi', 'label', 'Kihindi'),
    ('sw', 'choice', 'language/kannada', 'label', 'Kikannada'),
    ('sw', 'choice', 'language/malayalam', 'label', 'Kimalayalam'),
    ('sw', 'choice', 'language/marathi', 'label', 'Kimarathi'),
    ('sw', 'question', 'consent_mode', 'label', 'Njia iliyotumika kupata idhini'),
    ('sw', 'question', 'custom_medical_certificate_upload', 'hint', 'Chagua picha ya JPEG au PNG, au hati ya PDF.'),
    ('sw', 'question', 'custom_medical_certificate_upload', 'label', 'Pakia cheti cha matibabu (picha au PDF)'),
    ('sw', 'question', 'digitva_documents', 'label', 'Hati za matibabu na za kifo'),
    ('sw', 'question', 'ds_count', 'hint', '0 hadi 5'),
    ('sw', 'question', 'imagenarr', 'label', '(Piga picha kwa maelezo) Picha ya maelezo yaliyoandikwa, ikiwa maelezo yaliandikwa kwenye karatasi'),
    ('sw', 'question', 'md_count', 'hint', '0 hadi 30'),
    ('sw', 'question', 'narr_language', 'label', 'Lugha ya maelezo'),
    ('ta', 'choice', 'CONSENT_MODE/in_person', 'label', 'நேரில்'),
    ('ta', 'choice', 'CONSENT_MODE/telephonic', 'label', 'தொலைபேசி வழியாக'),
    ('ta', 'choice', 'language/bangla', 'label', 'வங்காளம்'),
    ('ta', 'choice', 'language/english', 'label', 'ஆங்கிலம்'),
    ('ta', 'choice', 'language/hindi', 'label', 'இந்தி'),
    ('ta', 'choice', 'language/kannada', 'label', 'கன்னடம்'),
    ('ta', 'choice', 'language/malayalam', 'label', 'மலையாளம்'),
    ('ta', 'choice', 'language/marathi', 'label', 'மராத்தி'),
    ('ta', 'question', 'abha_address', 'hint', 'எ.கா. name@abdm'),
    ('ta', 'question', 'abha_address', 'label', 'இறந்தவரின் ABHA முகவரி, தெரிந்தால்'),
    ('ta', 'question', 'abha_number', 'hint', 'ஆயுஷ்மான் பாரத் ஹெல்த் அக்கவுன்ட் எண், எ.கா. 12-3456-7890-1234'),
    ('ta', 'question', 'abha_number', 'label', 'இறந்தவரின் ABHA எண் (14 இலக்கங்கள்), தெரிந்தால்'),
    ('ta', 'question', 'consent_mode', 'label', 'ஒப்புதல் எந்த முறையில் பெறப்பட்டது'),
    ('ta', 'question', 'custom_medical_certificate_upload', 'hint', 'JPEG அல்லது PNG படம், அல்லது PDF ஆவணத்தைத் தேர்ந்தெடுக்கவும்.'),
    ('ta', 'question', 'custom_medical_certificate_upload', 'label', 'மருத்துவச் சான்றிதழைப் பதிவேற்றவும் (படம் அல்லது PDF)'),
    ('ta', 'question', 'digitva_documents', 'label', 'மருத்துவ மற்றும் இறப்பு ஆவணங்கள்'),
    ('ta', 'question', 'ds_count', 'hint', '0 முதல் 5 வரை'),
    ('ta', 'question', 'imagenarr', 'label', '(விவரிப்புக்கான படத்தை எடுக்கவும்) எழுதப்பட்ட விவரிப்பின் புகைப்படம், விவரிப்பு காகிதத்தில் பதிவு செய்யப்பட்டிருந்தால்'),
    ('ta', 'question', 'md_count', 'hint', '0 முதல் 30 வரை'),
    ('ta', 'question', 'narr_language', 'label', 'விவரிப்பு மொழி'),
)


def _relabel(from_source: str, to_source: str) -> None:
    bind = op.get_bind()
    for locale_code, item_kind, item_key, field, text in SEED_ROWS:
        bind.execute(
            sa.text(
                """
                UPDATE map_instrument_translations
                SET source = :to_source
                WHERE instrument_code = :code
                  AND locale_code = :locale
                  AND item_kind = :kind
                  AND item_key = :key
                  AND field = :field
                  AND source = :from_source
                  AND text = :text
                """
            ),
            {
                "code": INSTRUMENT_CODE,
                "locale": locale_code,
                "kind": item_kind,
                "key": item_key,
                "field": field,
                "text": text,
                "from_source": from_source,
                "to_source": to_source,
            },
        )


def upgrade():
    _relabel("imported", "machine")


def downgrade():
    _relabel("machine", "imported")
