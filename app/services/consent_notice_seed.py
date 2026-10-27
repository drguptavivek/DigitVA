"""The respondent consent notice seeded by Project Setup's "Seed from draft"
(digitva-athy). The texts are the "English seed" and "Hindi seed" blocks of
docs/policy/respondent-consent-notice-draft.md, kept here because the app does
not read docs at run time; tests/services/test_consent_notice_seed.py fails if
the two differ. ``[PROJECT NAME]`` is replaced by the project's name; the
other bracketed items are left for the project to fill in (a new version).
"""

PROJECT_NAME_PLACEHOLDER = "[PROJECT NAME]"

SEED_TEXT = {
    "en": (
        "[PROJECT NAME]: information about a death in your family\n"
        "\n"
        "We are asking about a death so that the cause can be understood and health services can improve. Please listen to or read this before you answer. You can say no to any part marked optional and still take part.\n"
        "\n"
        "What we collect. About you: your name, phone number, address and how you are related to the person who died. About the person who died: age, sex, the date and place of death, the illness and events before death, and, if you choose to give them, identity numbers such as Aadhaar (only the last three digits are kept) or ABHA.\n"
        "\n"
        "Why we collect it, and who sees it.\n"
        "1. To record the death and complete the interview (required). Health workers, interviewers and their supervisors see your name, phone and address so that the interview can be done and checked.\n"
        "2. To contact you (required if you give a phone number). We may call or visit to complete or clarify the answers.\n"
        "3. To send you messages (optional). SMS or WhatsApp messages about this interview, such as a reminder or a thank-you.\n"
        "4. To decide the cause of death (required). Doctors and coders review the answers. They do not see your name, phone, address or any identity number.\n"
        "5. For government and statistical reports (required). Counts and summaries that do not name anyone.\n"
        "6. For research on verbal autopsy (optional). De-identified answers may be shared in research repositories in India and other countries. Your name, phone, exact address, identity numbers and the exact date of death are never included.\n"
        "7. Computer help to check and translate your account (optional). Programs on systems controlled by [ORGANISATION] in India may remove names, places and numbers from a copy of your account, check whether it has enough detail, translate it into English, and point out symptoms for the doctors. They do not decide the cause of death, and your account is not sent to any outside company.\n"
        "\n"
        "How we protect it. Your name, phone number, address and identity numbers are stored in encrypted form. Only people whose work needs them can see them, and what they see is recorded.\n"
        "\n"
        "How long we keep it. [RETENTION PERIOD AND WHAT HAPPENS AFTER]\n"
        "\n"
        "Your rights. You can ask to see, correct or erase the details we hold about you, or ask that your answers be left out of reports and research. You can withdraw your agreement at any time through the contacts below. De-identified data already shared for research cannot be taken back. You can complain to [DATA PROTECTION OFFICER] and then to the Data Protection Board of India.\n"
        "\n"
        "Who to contact.\n"
        "- Deletion or exclusion of your data: [DELETION AND EXCLUSION EMAIL], [PHONE]. Quote the case number given to you.\n"
        "- Your district team: [DISTRICT CONTACT NAME, EMAIL, PHONE].\n"
        "- The mentoring institution: [INSTITUTION NAME, EMAIL, PHONE].\n"
        "- The central team: [EMAIL, PHONE].\n"
        "\n"
        "Your choice. Please say yes or no to each numbered item."
    ),
    "hi": (
        "[PROJECT NAME]: आपके परिवार में हुई मृत्यु के बारे में जानकारी\n"
        "\n"
        'हम यह मृत्यु के बारे में इसलिए पूछ रहे हैं ताकि मृत्यु का कारण समझा जा सके और स्वास्थ्य सेवाएँ बेहतर हो सकें। उत्तर देने से पहले कृपया इसे सुनें या पढ़ें। "वैकल्पिक" लिखे किसी भी भाग के लिए आप मना कर सकते हैं और फिर भी भाग ले सकते हैं।\n'
        "\n"
        "हम क्या जानकारी लेते हैं। आपके बारे में: आपका नाम, फ़ोन नंबर, पता और मृत व्यक्ति से आपका संबंध। मृत व्यक्ति के बारे में: आयु, लिंग, मृत्यु की तारीख और स्थान, मृत्यु से पहले की बीमारी और घटनाएँ, और यदि आप देना चाहें तो आधार (केवल अंतिम तीन अंक रखे जाते हैं) या ABHA जैसे पहचान नंबर।\n"
        "\n"
        "हम यह क्यों लेते हैं और इसे कौन देखता है।\n"
        "1. मृत्यु दर्ज करने और साक्षात्कार पूरा करने के लिए (आवश्यक)। स्वास्थ्य कार्यकर्ता, साक्षात्कारकर्ता और उनके पर्यवेक्षक आपका नाम, फ़ोन और पता देखते हैं ताकि साक्षात्कार किया और जाँचा जा सके।\n"
        "2. आपसे संपर्क करने के लिए (फ़ोन नंबर देने पर आवश्यक)। उत्तर पूरे करने या स्पष्ट करने के लिए हम आपको फ़ोन कर सकते हैं या मिलने आ सकते हैं।\n"
        "3. आपको संदेश भेजने के लिए (वैकल्पिक)। इस साक्षात्कार के बारे में SMS या WhatsApp संदेश, जैसे याद दिलाना या धन्यवाद।\n"
        "4. मृत्यु का कारण तय करने के लिए (आवश्यक)। डॉक्टर और कोडर उत्तरों की समीक्षा करते हैं। वे आपका नाम, फ़ोन, पता या कोई पहचान नंबर नहीं देखते।\n"
        "5. सरकारी और सांख्यिकीय रिपोर्टों के लिए (आवश्यक)। गिनती और सारांश, जिनमें किसी का नाम नहीं होता।\n"
        "6. वर्बल ऑटोप्सी पर शोध के लिए (वैकल्पिक)। पहचान हटाए गए उत्तर भारत और अन्य देशों के शोध भंडारों में साझा किए जा सकते हैं। आपका नाम, फ़ोन, सटीक पता, पहचान नंबर और मृत्यु की सटीक तारीख कभी शामिल नहीं की जाती।\n"
        "7. आपके विवरण की जाँच और अनुवाद में कंप्यूटर की मदद (वैकल्पिक)। भारत में [ORGANISATION] द्वारा नियंत्रित प्रणालियों पर चलने वाले प्रोग्राम आपके विवरण की एक प्रति से नाम, स्थान और नंबर हटा सकते हैं, जाँच सकते हैं कि उसमें पर्याप्त जानकारी है या नहीं, उसका अंग्रेज़ी में अनुवाद कर सकते हैं, और डॉक्टरों के लिए लक्षण बता सकते हैं। ये मृत्यु का कारण तय नहीं करते, और आपका विवरण किसी बाहरी कंपनी को नहीं भेजा जाता।\n"
        "\n"
        "हम इसकी सुरक्षा कैसे करते हैं। आपका नाम, फ़ोन नंबर, पता और पहचान नंबर एन्क्रिप्ट करके रखे जाते हैं। केवल वही लोग इन्हें देख सकते हैं जिनके काम के लिए ये ज़रूरी हैं, और वे क्या देखते हैं, यह दर्ज किया जाता है।\n"
        "\n"
        "हम इसे कितने समय तक रखते हैं। [रखने की अवधि और उसके बाद क्या होगा]\n"
        "\n"
        "आपके अधिकार। आप हमारे पास रखी अपनी जानकारी देखने, उसे सुधारने या मिटाने के लिए कह सकते हैं, या कह सकते हैं कि आपके उत्तर रिपोर्टों और शोध से बाहर रखे जाएँ। आप नीचे दिए संपर्कों के माध्यम से किसी भी समय अपनी सहमति वापस ले सकते हैं। शोध के लिए पहले से साझा किया गया पहचान-रहित डेटा वापस नहीं लिया जा सकता। आप [डेटा संरक्षण अधिकारी] से और फिर भारतीय डेटा संरक्षण बोर्ड से शिकायत कर सकते हैं।\n"
        "\n"
        "किससे संपर्क करें।\n"
        "- अपना डेटा मिटाने या बाहर रखने के लिए: [डेटा मिटाने और बाहर रखने का ईमेल], [फ़ोन]। आपको दिया गया केस नंबर बताएँ।\n"
        "- आपकी ज़िला टीम: [ज़िला संपर्क का नाम, ईमेल, फ़ोन]।\n"
        "- मार्गदर्शक संस्थान: [संस्थान का नाम, ईमेल, फ़ोन]।\n"
        "- केंद्रीय टीम: [ईमेल, फ़ोन]।\n"
        "\n"
        "आपकी पसंद। कृपया हर क्रमांकित बिंदु के लिए हाँ या ना कहें।"
    ),
}

#: Per language, the same codes and required flags (sorted by code on save).
SEED_PURPOSES = {
    "en": [
        {"code": "record_and_interview", "label": "Record the death and complete the interview", "required": True},
        {"code": "contact_followup", "label": "Contact me by phone or visit to complete or clarify the answers", "required": True},
        {"code": "messages", "label": "Send me SMS or WhatsApp messages about this interview", "required": False},
        {"code": "cause_of_death_coding", "label": "Doctors and coders decide the cause of death (without my name, phone or address)", "required": True},
        {"code": "statistics_reports", "label": "Use counts and summaries in government and statistical reports", "required": True},
        {"code": "research_sharing", "label": "Share de-identified answers in research repositories", "required": False},
        {"code": "narrative_automated_processing", "label": "Computer programs on [ORGANISATION]'s systems in India may de-identify, check, translate and suggest symptoms from my account (they do not decide the cause of death)", "required": False},
    ],
    "hi": [
        {"code": "record_and_interview", "label": "मृत्यु दर्ज करना और साक्षात्कार पूरा करना", "required": True},
        {"code": "contact_followup", "label": "उत्तर पूरे करने या स्पष्ट करने के लिए मुझसे फ़ोन या मुलाक़ात द्वारा संपर्क करना", "required": True},
        {"code": "messages", "label": "इस साक्षात्कार के बारे में मुझे SMS या WhatsApp संदेश भेजना", "required": False},
        {"code": "cause_of_death_coding", "label": "डॉक्टर और कोडर मृत्यु का कारण तय करें (मेरा नाम, फ़ोन या पता देखे बिना)", "required": True},
        {"code": "statistics_reports", "label": "सरकारी और सांख्यिकीय रिपोर्टों में गिनती और सारांश का उपयोग", "required": True},
        {"code": "research_sharing", "label": "पहचान हटाए गए उत्तरों को शोध भंडारों में साझा करना", "required": False},
        {"code": "narrative_automated_processing", "label": "भारत में [ORGANISATION] की प्रणालियों पर कंप्यूटर प्रोग्राम मेरे विवरण से पहचान हटा सकते हैं, उसकी जाँच, अनुवाद और लक्षण सुझा सकते हैं (वे मृत्यु का कारण तय नहीं करते)", "required": False},
    ],
}

SEED_ALLOWED_MODES = ["spoken", "tap", "signed"]
