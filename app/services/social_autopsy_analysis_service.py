SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS = [
    {
        "delay_level": "delay_1_decision",
        "title": "Delay 1: Delay in decision to seek care",
        "options": [
            {
                "option_code": "none",
                "label": "None",
                "description": (
                    "No delay factor from this delay level was identified for this case."
                ),
            },
            {
                "option_code": "traditions",
                "label": "Traditions",
                "description": (
                    "Traditional practices, cultural beliefs, or reliance on home "
                    "remedies influenced health-seeking behaviour and delayed seeking "
                    "formal medical care."
                ),
            },
            {
                "option_code": "recognition",
                "label": "Recognition",
                "description": (
                    "Lack of recognition or awareness of serious illness, symptoms, "
                    "or severity of disease led to delayed decision-making in seeking care."
                ),
            },
            {
                "option_code": "inevitability",
                "label": "Inevitability",
                "description": (
                    "Death occurred under circumstances where seeking care was unlikely "
                    "to change the outcome, such as very advanced age or recognised "
                    "terminal illness."
                ),
            },
        ],
    },
    {
        "delay_level": "delay_2_reaching",
        "title": "Delay 2: Delay in reaching health facility",
        "options": [
            {
                "option_code": "none",
                "label": "None",
                "description": (
                    "No delay factor from this delay level was identified for this case."
                ),
            },
            {
                "option_code": "transport_logistics",
                "label": "Transport and Logistics",
                "description": (
                    "Difficulties in arranging or accessing transportation, long "
                    "distances to health facilities, poor road connectivity, or lack "
                    "of timely transport services delayed reaching appropriate care."
                ),
            },
            {
                "option_code": "financial_barrier",
                "label": "Financial Barrier",
                "description": (
                    "Lack of money for transportation, consultation, or treatment "
                    "costs made it difficult for the patient or family to reach a "
                    "health facility in time."
                ),
            },
            {
                "option_code": "emergencies",
                "label": "Emergencies",
                "description": (
                    "Sudden and severe medical conditions progressed rapidly, leaving "
                    "limited time to reach appropriate health care services."
                ),
            },
        ],
    },
    {
        "delay_level": "delay_3_receiving",
        "title": "Delay 3: Delay in receiving adequate care",
        "options": [
            {
                "option_code": "none",
                "label": "None",
                "description": (
                    "No delay factor from this delay level was identified for this case."
                ),
            },
            {
                "option_code": "lack_of_services_first_facility",
                "label": "Lack of Services at the first facility",
                "description": (
                    "Problems encountered within health facilities such as delays in "
                    "admission, lack of treatment, unavailability of medicines, or "
                    "referral issues affected care."
                ),
            },
            {
                "option_code": "delay_in_referral",
                "label": "Delay in Referral",
                "description": (
                    "Delay in referring the patient to an appropriate higher-level "
                    "facility despite the need for advanced care, leading to loss of "
                    "critical time for treatment."
                ),
            },
            {
                "option_code": "financial_barrier",
                "label": "Financial Barrier",
                "description": (
                    "Inability to arrange funds for hospital admission, medicines, "
                    "investigations, or treatment after reaching the health facility."
                ),
            },
        ],
    },
]


def social_autopsy_option_set():
    return {
        (question["delay_level"], option["option_code"])
        for question in SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS
        for option in question["options"]
    }
