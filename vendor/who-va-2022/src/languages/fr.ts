/**
 * Machine-generated French draft for UI evaluation. Clinical and field terminology
 * must be reviewed by fluent verbal-autopsy specialists before production use.
 */
import type { WhoVaLanguageFile } from "../i18n.js";

export default {
  locale: "fr",
  instrument: {
    sections: {
      Interviewer: "Intervieweur VA",
      presets: "Préréglez la mortalité et la saison du VIH-paludisme.",
      respondent_backgr: "Informations sur le répondant et historique de l'entretien",
      consented: "Fin de l’entretien",
      deceased_CRVS: "Informations sur le défunt et état civil",
      info_on_deceased: "Informations sur le défunt",
      narrat: "Récit ouvert",
      stillbirth: "Vérification d'une éventuelle mortinatalité",
      med_hist_final_illness: "Antécédents médicaux associés à la maladie finale",
      injuries_accidents: "Antécédents de blessures/accidents",
      injuries_accidents_yes: "Détail des blessures et des accidents",
      illhistory: "Antécédents de santé",
      illdur: "Durée de la maladie",
      signs_symptoms_final_illness: "Signes et symptômes généraux associés à la maladie finale",
      breathdur: "Durée des difficultés respiratoires",
      paindur: "Durée de la douleur thoracique",
      abdominal_pain: "Douleur abdominale",
      neonatal_childC: "Questions sur l'enfant néonatal, partie C",
      pregnancy_women: "Signes et symptômes associés à la grossesse et aux femmes",
      group_maternal: "Questions sur d’éventuels décès maternels",
      deliverytype: "Comment la mère a-t-elle accouché de son bébé ?",
      neonatal_child: "Antécédents, signes et symptômes néonatals et infantiles",
      neonatal_childA: "Questions sur l'enfant néonatal, partie A",
      g10366: "Poids (en grammes) du défunt à la naissance",
      neonatal_childB: "(neonatal_childB) Questions sur l'enfant néonatal, partie B",
      mother_deliv: "(mother_deliv) Comment le bébé a-t-il été accouché ?",
      risk_factors: "Facteurs de risque",
      health_service_utilization: "Utilisation des services de santé",
      vital_reg_certif: "Numéros d'état civil",
      deathcert: "Certificat médical de la cause du décès"
    },
    questions: {
      audit: {},
      Id10010: {
        label: "(Id10010) [Nom de l'intervieweur VA]",
        guidance:
          "Enregistrez ici le nom de l’intervieweur VA principal. Le bureau du projet peut ajouter une liste de noms d'intervieweurs ou recommander un format standard pour déclarer les noms (par exemple prénom, nom)."
      },
      Id10010a: {
        label: "(Id10010a) [Âge de l'intervieweur VA]",
        hint: "Entrez 99 si vous ne souhaitez pas divulguer l'âge",
        guidance:
          "Enregistrez ici l’âge en années de l’intervieweur principal VA. Une fois renseigné ODK Collect, la réponse au champ devient pré-remplie. Le champ n'est pas associé à l'attribution de la cause du décès ; cependant, il s’agit d’informations utiles pour voir comment fonctionne le système VA. Si les enquêteurs ne souhaitent pas répondre, inscrivez « 99 ».",
        constraintMessage: "L'intervieweur doit être un adulte et pas plus de 89 ans"
      },
      Id10010b: {
        label: "(Id10010b) [Sexe de l'intervieweur VA]",
        guidance:
          "Enregistrez le sexe de l’intervieweur VA principal comme étant femme, homme ou ambigu/intersexué. Une fois renseigné ODK Collect, la réponse au champ devient pré-remplie.",
        choices: {
          female: "Féminin",
          male: "Masculin",
          undetermined: "Ambiguous/intersex"
        }
      },
      Id10010c: {
        label: "(Id10010c) [ID de l'intervieweur VA]",
        hint: "Entrez « NA » si l'identifiant de l'intervieweur n'est pas disponible.",
        guidance:
          "Enregistrez un code d’identification unique pour l’intervieweur VA principal. L'identifiant de l'intervieweur peut comporter des chiffres et des lettres. Les types de pièces d'identité utilisées pour les enquêteurs VA varient selon les sites. Le bureau du projet doit conserver une liste des noms des enquêteurs et des codes d'identification uniques. Une fois rempli dans ODK Collect, la réponse au champ devient pré-remplie. Entrez « NA » si l’identité de l’intervieweur n’est pas disponible."
      },
      language: {
        label: "Langue d'entretien",
        guidance:
          "Sélectionnez la langue utilisée pour l'entretien. Les options de réponses pour ce champ sont programmables au niveau du projet. Pour obtenir des instructions sur la façon de modifier les options de réponse aux questions, veuillez vous référer au ODK for VA : Un guide rapide. Pour modifier les réponses, dans la feuille de choix de l'instrument ODK VA, aux lignes 3 à 5, il est possible de remplacer les valeurs de la colonne d'étiquette (actuellement anglais, langue 2, langue 3) par les langues utilisées dans les paramètres VA. Si moins de 3 langues sont utilisées, est-il possible de supprimer une ou plusieurs lignes, ou si plus de 3 sont utilisées, est-il possible d'ajouter une ou plusieurs lignes avec les autres langues (par exemple langue 4 Langue 4).",
        choices: {
          en: "Anglais"
        }
      },
      Id10002: {
        label: "(Id10002) [Est-ce une région où la mortalité par VIH/SIDA est élevée ?]",
        hint: "A compléter par le bureau central. ÉLEVÉ correspond à plus de 1% des décès dus au VIH/SIDA, FAIBLE autour de 0,1%, TRÈS FAIBLE moins de 0,01%. Le remplissage lors de l'entretien n'est pas obligatoire. Habituellement, la valeur est prédéterminée pour la région.",
        guidance:
          "La réponse à cette question doit être décidée par le bureau du projet avant l'entretien avec le VA. La mortalité élevée du VIH/SIDA ne repose pas sur une mortalité spécifique du VIH dans la population étudiée, mais sur la mortalité régionale où se situe la population. Généralement, tous les pays d’Afrique orientale et australe sont classés comme ayant une mortalité élevée et le reste des régions d’AFRO, SEARO, WPRO et PAHO comme ayant une mortalité faible ou très faible. ÉLEVÉ correspond à >1% des décès, FAIBLE autour de 0,1% et TRÈS FAIBLE",
        choices: {
          high: "Haut",
          low: "Bas",
          veryl: "Très bas"
        }
      },
      Id10003: {
        label: "(Id10003) [Est-ce une région où la mortalité due au paludisme est élevée ?]",
        hint: "A compléter par le bureau central. ÉLEVÉ correspond à plus de 1% des décès dus au paludisme, FAIBLE autour de 0,1%, TRÈS FAIBLE moins de 0,01%. Le remplissage lors de l'entretien n'est pas obligatoire. Habituellement, la valeur est prédéterminée pour la région.",
        guidance:
          "La réponse à cette question doit être décidée par le bureau du projet avant l'entretien avec le VA. La mortalité élevée du paludisme ne repose pas sur une mortalité spécifique du paludisme dans la population étudiée, mais sur la prévalence régionale où se situe la population. Généralement, tous les pays d’Afrique orientale et australe sont classés comme ayant une mortalité élevée et le reste des régions d’AFRO, SEARO, WPRO et PAHO comme ayant une mortalité faible ou très faible. ÉLEVÉ correspond à plus de 1% des décès, FAIBLE autour de 0,1% et TRÈS FAIBLE",
        choices: {
          high: "Haut",
          low: "Bas",
          veryl: "Très bas"
        }
      },
      Id10004: {
        label: "(Id10004) [Pendant quelle saison est-il mort ?]",
        hint: "Doit être complété par le bureau central.",
        guidance:
          "L'équipe de projet doit fournir une liste de mois classés comme humides ou secs. Sélectionnez humide ou sec selon la liste fournie. La manière dont les informations sont complétées varie selon les sites, mais idéalement, elles sont remplies par le bureau central ; les enquêteurs étant en mesure de modifier les informations si elles sont vérifiées différemment en consultation avec le bureau central.",
        choices: {
          wet: "HUMIDE",
          dry: "SÈCHE",
          DK: "Ne sait pas"
        }
      },
      Id10007: {
        label: "(Id10007) Quel est le nom complet du répondant VA ?",
        guidance:
          "Enregistrez le nom déclaré du répondant. Déclarez les noms de façon standard comme suit : prénom (prénom), nom de famille. La question n’est pas nécessaire pour l’attribution de la cause du décès et peut être ignorée."
      },
      Id10007a: {
        label: "(Id10007a) [Quel est le sexe du répondant VA ?]",
        guidance: "Enregistrez le sexe du répondant comme étant féminin, masculin ou ambigu/intersexué.",
        choices: {
          female: "Féminin",
          male: "Masculin",
          undetermined: "Ambiguous/intersex"
        }
      },
      Id10007b: {
        label: "(Id10007b) Quel est l'âge du répondant VA ?",
        guidance:
          "Enregistrez l’âge en années du répondant. La question n’est pas nécessaire pour l’attribution de la cause du décès et peut être ignorée.",
        constraintMessage: "Le répondant doit être un adulte et pas plus de 90 ans"
      },
      Id10008: {
        label: "(Id10008) Quel est votre lien ou celui du répondant avec la personne décédée ?",
        hint: "Vérifiez d'abord si le répondant est un membre de la famille, et seulement si ce n'est pas un membre de la famille, choisissez les autres catégories comme agent de santé ou agent public.",
        guidance:
          "Vérifiez d’abord si le répondant est un membre de la famille, et seulement s’il ne s’agit pas d’un membre de la famille, choisissez parmi les autres catégories de réponses, comme « agent de santé », « agent public » ou « autre relation ». Une seule case de réponse peut être sélectionnée. Cochez la case appropriée qui représente la relation déclarée par le répondant.",
        choices: {
          parent: "Parent",
          child: "Enfant",
          family_member: "Autre membre de la famille",
          friend: "Ami",
          spouse: "Spouse",
          health_worker: "Soignant",
          public_official: "Agent Public",
          another_relationship: "une autre relation",
          Ref: "Refus de repondre"
        }
      },
      Id10009: {
        label:
          "(Id10009) Est-ce que vous/le répondant viviez avec la personne décédée au cours de la période précédant son décès ?",
        hint: "La période ayant conduit au décès désigne la période au cours de laquelle la maladie ayant entraîné le décès a débuté ; la période pendant laquelle la personne était malade ayant entraîné son décès. Cela peut prendre 2 jours, 1 semaine, 3 mois, etc.",
        guidance:
          "Sélectionnez la réponse appropriée. Dans le cas de mortinaissances ou de décès néonatals, des éclaircissements supplémentaires peuvent être nécessaires de la part du répondant avant de sélectionner directement une réponse.\n● Si l'enquêtée est la mère et qu'il s'agit d'un enfant mort-né, inscrivez « OUI ».\n● Si le répondant est la mère et qu'il s'agit d'un décès néonatal, la réponse est probablement « OUI », MAIS peut être « NON » si le répondant indique une circonstance dans laquelle il n'était pas avec son nouveau-né.\n● Si le répondant n'est pas la mère et qu'il s'agissait d'un enfant mort-né, inscrivez « OUI » si le répondant indique qu'il vivait avec la mère du défunt. \n● Si le répondant n'est pas la mère et qu'il s'agissait d'un nouveau-né, si le répondant vivait avec la mère, la réponse est probablement « OUI ». Cependant, cela dépend des circonstances (par exemple, le répondant et la mère n'étaient pas avec le nouveau-né). Des explications supplémentaires de la part du répondant pourraient donc être nécessaires. \nREMARQUE : Sauf indication contraire, les questions font généralement référence à la période « pendant la maladie ayant entraîné le décès ». Certaines pathologies (par exemple les difficultés respiratoires dans la BPCO) peuvent persister de manière constante pendant une longue période, conduisant éventuellement à la mort. D'autres affections ou maladies peuvent avoir présenté des symptômes dans le passé, mais si la personne s'est rétablie de ces symptômes avant son décès, ils ne sont probablement pas liés au décès.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10012: {
        label: "(Id10012) Date de l'entretien"
      },
      Id10013: {
        label: "(Id10013) [Le répondant a-t-il donné son consentement ?]",
        guidance:
          "Sélectionnez la réponse appropriée. Si le répondant n'a pas donné son consentement, clôturez l'entretien ici et enregistrez l'heure à laquelle l'entretien s'est terminé. Le consentement est demandé après Id10007-10009 comme information minimale nécessaire au contrôle de la qualité des processus d'AV.",
        choices: {
          yes: "Oui",
          no: "Non"
        }
      },
      Id10011: {
        label: "(Id10011) Heure de début de l'entretien"
      },
      Id10017: {
        label: "(Id10017) Quel était le prénom ou le(s) nom(s) du défunt ?",
        guidance:
          "Vérifiez le(s) nom(s) du défunt dans la liste papier/électronique du cas d'autopsie verbale assigné avec ce qui est rapporté par le défendeur. En cas d'incohérence, signalez-le au superviseur. Si le nom est cohérent, enregistrez-le (si vous utilisez un formulaire papier, assurez-vous qu'il est lisible). En Id10017, il vous est demandé le(s) prénom(s) du défunt. En Id10018, il vous est demandé le(s) nom(s) de famille (ou nom(s) de famille) (c'est-à-dire que plusieurs noms peuvent être ajoutés) du défunt."
      },
      Id10018: {
        label: "(Id10018) Quel était le(s) nom(s) (ou nom(s) de famille) du défunt ?",
        guidance:
          "Vérifiez le(s) nom(s) du défunt dans la liste papier/électronique du cas d'autopsie verbale assigné avec ce qui est rapporté par le défendeur. En cas d'incohérence, signalez-le au superviseur. Si le nom est cohérent, enregistrez-le (si vous utilisez un formulaire papier, assurez-vous qu'il est lisible). En Id10017, il vous est demandé le(s) prénom(s) du défunt. En Id10018, il vous est demandé le(s) nom(s) de famille (ou nom(s) de famille) (c'est-à-dire que plusieurs noms peuvent être ajoutés) du défunt."
      },
      Id10019: {
        label: "(Id10019) Quel était le sexe du défunt ?",
        guidance:
          "Vérifiez le sexe biologique de la personne décédée dans la liste papier/électronique du cas d'autopsie verbale attribué avec ce qui est rapporté par le répondant. En cas d'incohérence, signalez-le au superviseur. Assurez-vous de sélectionner la bonne case de réponse. Si vous cochez la mauvaise case, la cause du décès pourrait être incorrecte. Si le sexe biologique n’est généralement pas masculin ou féminin, sélectionnez « organes génitaux ambigus/intersexués ». Cette sélection peut être le choix approprié si le bébé souffre d'une maladie rare dans laquelle les organes génitaux externes du nourrisson ne semblent pas clairement être masculins ou féminins. Dans de tels cas, les organes génitaux peuvent ne pas être bien formés ou le bébé peut présenter des caractéristiques des deux sexes.",
        choices: {
          female: "Féminin",
          male: "Masculin",
          undetermined: "Ambiguous/intersex"
        }
      },
      Id10020: {
        label: "(Id10020) La date de naissance est-elle connue ?",
        guidance:
          "Si vous ne connaissez pas la date de naissance complète, sélectionnez l'option « NON » ; vous sauterez ensuite la question suivante sur la date de naissance (Id10021) pour préciser la date – et passerez à la question sur la connaissance de la date du décès (Id10022). Cela se produit automatiquement dans ODK. Dans certains cas, notamment pour les personnes âgées, l'utilisation de calendriers communautaires d'événements historiques significatifs peut faciliter l'approximation de l'année de naissance. Si la réponse est « OUI », complétez la date de naissance.",
        choices: {
          yes: "Oui",
          no: "Non",
          ref: "Refus de repondre"
        }
      },
      Id10021: {
        label: "(Id10021) Quand le défunt est-il né ?",
        guidance:
          "Enregistrez la date de naissance. Le format de la date est le jour, le mois et l'année (jj/mm/aaaa). Ce sera un format de calendrier pour ODK.",
        constraintMessage: "La date ne peut pas être postérieure"
      },
      Id10022: {
        label: "(Id10022) La date du décès est-elle connue ?",
        guidance:
          "La liste des décès figurant dans les documents relatifs au cas d'autopsie verbale assigné doit contenir ces informations, mais la question doit également être posée aux personnes interrogées. REMARQUE : Pour ODK, vous devrez disposer de la date complète du décès pour la saisir. Si vous n'avez pas la date complète du décès, vous devez sélectionner « NON ». Ensuite, dans ODK, une question supplémentaire vous sera posée sur l’année du décès. Remplissez l'année du décès en quatre chiffres. Pour la version papier du questionnaire, s’ils ne sont pas sûrs de la date, inscrivez l’année du décès si elle est connue.",
        choices: {
          yes: "Oui",
          no: "Non",
          ref: "Refus de repondre"
        }
      },
      Id10023_a: {
        label: "(Id10023_a) Quand est-il mort ?",
        hint: "Si le défunt était un bébé mort-né, inscrivez la date de l'accouchement comme date du décès.",
        guidance:
          "Les informations sur le décès contenues dans les documents relatifs à l'autopsie verbale assignée devraient contenir ces informations. Vous devez quand même demander au répondant, puis enregistrer sa réponse concernant la date du décès en utilisant le format jour/mois/année (jj/mm/aaaa). Il s'agira d'un format de calendrier pour ODK, vous devrez donc indiquer la date complète. Pour le questionnaire papier, vous remplirez les cases prévues à cet effet. S'ils ne sont pas sûrs de la date exacte, enregistrez l'année du décès. Si le défunt était un bébé mort-né, inscrivez la date de l'accouchement comme date du décès. Si vous avez enregistré la date complète de naissance et la date complète de décès, le dispositif électronique sélectionnera automatiquement le questionnaire correspondant à l'une des trois tranches d'âge : nouveau-né, enfant ou adulte. Soyez donc très prudent en complétant la date de naissance et la date de décès. Si vous faites une erreur dans la date de naissance ou de décès, vous remplirez un mauvais questionnaire.",
        constraintMessage:
          "La date du décès doit être identique ou postérieure à la date de naissance et ne peut pas être postérieure à la date future."
      },
      Id10023_b: {
        label: "(Id10023_b) Quand est-il mort ?",
        hint: "Si le défunt était un bébé mort-né, inscrivez la date de l'accouchement comme date du décès.",
        guidance:
          "Les informations sur le décès contenues dans les documents relatifs à l'autopsie verbale assignée devraient contenir ces informations. Vous devez quand même demander au répondant, puis enregistrer sa réponse concernant la date du décès en utilisant le format jour/mois/année (jj/mm/aaaa). Il s'agira d'un format de calendrier pour ODK, vous devrez donc indiquer la date complète. Pour le questionnaire papier, vous remplirez les cases prévues à cet effet. S'ils ne sont pas sûrs de la date exacte, enregistrez l'année du décès. Si le défunt était un bébé mort-né, inscrivez la date de l'accouchement comme date du décès. Si vous avez enregistré la date complète de naissance et la date complète de décès, le dispositif électronique sélectionnera automatiquement le questionnaire correspondant à l'une des trois tranches d'âge : nouveau-né, enfant ou adulte. Soyez donc très prudent en complétant la date de naissance et la date de décès. Si vous faites une erreur dans la date de naissance ou de décès, vous remplirez un mauvais questionnaire.",
        constraintMessage: "La date du décès ne peut pas être postérieure."
      },
      Id10023: {
        label: "(Id10023) Quand est-il mort ?"
      },
      Id10024: {
        label: "(Id10024) Veuillez indiquer l'année du décès.",
        guidance: "Enregistrez l'année du décès.",
        constraintMessage: "L'année du décès ne peut pas être dans le futur"
      },
      ageInDays: {
        label: "Âge en jours"
      },
      ageInDays2: {
        label: "Âge en jours"
      },
      ageInYears: {
        label: "Âge en années"
      },
      ageInYearsRemain: {},
      ageInMonths: {
        label: "Âge en mois"
      },
      ageInMonthsRemain: {},
      isNeonatal1: {
        label: "La personne décédée est un nouveau-né"
      },
      isChild1: {
        label: "La personne décédée est un enfant"
      },
      isAdult1: {
        label: "La personne décédée est une personne majeure"
      },
      displayAgeNeonate: {
        label: "NEONATE était âgé de ${ageInDays} jours.",
        hint: "Veuillez vérifier que l'âge est correct avant de continuer. Vous allez maintenant remplir le questionnaire pour un NOUVEAU-NÉ."
      },
      displayAgeChild: {
        label: "L'ENFANT avait ${ageInYears} ans, ${ageInMonths} mois et ${ageInMonthsRemain} jours.",
        hint: "Veuillez vérifier que l'âge est correct avant de continuer. Vous allez maintenant remplir le questionnaire pour un ENFANT."
      },
      displayAgeAdult: {
        label: "ADULTE avait ${ageInYears} ans.",
        hint: "Veuillez vérifier que l'âge est correct avant de continuer. Vous allez maintenant remplir le questionnaire pour un ADULTE."
      },
      age_group: {
        label: "[Quelle tranche d'âge correspond au défunt ?]",
        hint: "(1) Néonatal 0-27 jours révolus ; (2) Enfant de 28 jours à 11 ans ; (3) Adulte – plus de 12 ans.",
        guidance:
          "Cet élément s'applique uniquement au format de collecte de données électronique. Si vous n'avez pas pu compléter la date de naissance ou la date de décès, vous serez obligé de sélectionner un questionnaire correspondant aux trois tranches d'âge : nouveau-né, enfant ou adulte. Sélectionnez la tranche d’âge du défunt, en fonction de votre évaluation de l’âge du défunt. Sélectionnez cette option très soigneusement. Si vous faites une erreur dans la tranche d'âge, des questions importantes seront sautées car certaines sections du questionnaire dépendent de la tranche d'âge pour déterminer les questions posées. Notez que cette question est utilisée pour déterminer la séquence de questions à utiliser. C'est une question obligatoire. Si le répondant ne connaît pas l'âge exact, inscrivez la meilleure estimation.",
        constraintMessage:
          "La tranche d’âge n’est pas compatible avec la date de naissance et l’année de décès indiquées. Veuillez revoir la sélection ou corriger les données saisies précédemment.",
        choices: {
          neonate: "nouveau-né",
          child: "enfant",
          adult: "adulte"
        }
      },
      age_neonate_days: {
        label: "Combien de jours avait le bébé ? [Entrez l'âge du nouveau-né en jours :]",
        hint: "L'âge néonatal est inférieur à 28 jours, soit 0 à 27 jours révolus. Si moins de 1 jour ou 24 heures, entrez 0 jour. Une réponse est requise pour cette question. Si l'âge exact est inconnu, entrez la meilleure estimation.",
        guidance:
          "Si vous avez sélectionné le questionnaire néonatal, vous devez saisir l'âge en jours. L'âge néonatal est inférieur à 28 jours, soit 0 à 27 jours révolus ; une entrée valide est comprise entre 0 et 27. Si le nouveau-né a moins de 1 jour ou 24 heures, entrez « 0 » jour.",
        constraintMessage: "L'âge néonatal est de 0 à 27 jours seulement !"
      },
      age_neonate_hours: {
        label: "Combien d'heures le bébé a-t-il été en vie ?",
        constraintMessage: "maximum 23 heures"
      },
      age_child_unit: {
        label: "Quel âge avait l'enfant ? [Entrez l'âge de l'enfant dans :]",
        hint: "L'âge de l'enfant est compris entre 28 jours et 11 ans. Une réponse est requise pour cette question. Si l'âge exact est inconnu, entrez la meilleure estimation.",
        choices: {
          days: "Jour",
          months: "mois",
          years: "année"
        }
      },
      age_child_days: {
        label: "[Entrez l'âge de l'enfant en jours :]",
        constraintMessage:
          "L'âge de l'enfant est supérieur à 28 jours ; Si la réponse était supérieure à 60 jours, demandez au répondant de déclarer le temps passé dans une autre unité."
      },
      age_child_months: {
        label: "[Entrez l'âge de l'enfant en mois :]",
        constraintMessage:
          "Le nombre saisi est peu probable. Si la réponse était supérieure à 59 mois, demandez au répondant de déclarer le temps en années."
      },
      age_child_years: {
        label: "[Entrez l'âge de l'enfant en années :]",
        constraintMessage: "L'âge de l'enfant est compris entre 28 jours et 11 ans seulement !"
      },
      age_adult: {
        label: "[Entrez l'âge de l'adulte en années :]",
        hint: "Une réponse est requise pour cette question. Si l'âge exact est inconnu, entrez la meilleure estimation.",
        constraintMessage:
          "L'âge adulte est supérieur à 11 ans ; un âge supérieur à 120 ans est peu probable."
      },
      ageInMonthsByYear: {
        label: "Âge en mois"
      },
      ageInYears2: {
        label: "Âge en années"
      },
      isNeonatal2: {
        label: "La personne décédée est un nouveau-né"
      },
      isChild2: {
        label: "La personne décédée est un enfant"
      },
      isAdult2: {
        label: "La personne décédée est une personne majeure"
      },
      isNeonatal: {
        label: "La personne décédée est un nouveau-né"
      },
      isChild: {
        label: "La personne décédée est un enfant"
      },
      isAdult: {
        label: "La personne décédée est une personne majeure"
      },
      ageInDaysNeonate: {
        label: "Âge en jours"
      },
      Id10008_check: {
        label:
          "(Id10008_check) Il n'est pas possible de sélectionner que le répondant est l'enfant du défunt et de saisir que le défunt est un nouveau-né ou un enfant. Veuillez revenir en arrière et corriger la sélection."
      },
      Id10058: {
        label: "(Id10058) Où le défunt est-il décédé ?",
        guidance: "Enregistrez le lieu du décès en cochant la case appropriée.",
        choices: {
          hospital: "hôpital",
          other_health_facility: "autre établissement de santé",
          home: "à domicile",
          on_route_to_hospital_or_facility: "sur la route de hôpital ou de établissement",
          other: "autres",
          DK: "Ne sait pas",
          Ref: "Refus de repondre"
        }
      },
      Id10487: {
        label:
          "(Id10487) Au cours des deux semaines précédant le décès, a-t-il vécu avec, rendu visite ou pris soin d'une personne présentant des symptômes de la COVID-19 ou un test de dépistage de la COVID-19 positif ?",
        hint: "Les symptômes du COVID-19 comprennent de la fièvre, des difficultés respiratoires, de la toux, une fatigue extrême et des modifications de l’odorat ou du goût. Dans le cas de nouveau-nés ou de jeunes enfants, veuillez omettre « prendre soin de ».",
        guidance:
          "Le fait d'avoir récemment vécu, visité ou pris soin d'une personne ayant souffert de la COVID-19 suggère que la personne décédée pourrait également avoir souffert de la COVID-19. Veuillez noter que dans le cas de nouveau-nés ou de jeunes enfants, vous devez omettre la question « prendre soin de ». Le répondant peut ne pas savoir si la personne décédée a eu un contact avec une personne atteinte de la COVID-19. Cependant, vous pouvez sonder doucement. Demandez d’abord si toute personne ayant vécu avec la personne décédée ou lui ayant rendu visite a été testée positive à la COVID-19. Parfois, les personnes qui présentaient des symptômes évocateurs de la COVID-19 n’ont pas fait de test pour confirmer la COVID-19. Dans le cas où le répondant affirme qu'aucune des personnes avec qui le défunt vivait ou lui rendait visite n'a fait de test COVID, demandez-lui doucement si quelqu'un présentait les symptômes suivants : forte fièvre, difficultés respiratoires, toux, fatigue extrême et changements d'odeur et/ou de goût. Si une personne a été testée positive ou présente au moins 4 de ces symptômes, sélectionnez la réponse « OUI ».\nREMARQUE : Les questions Id10051 à Id10073 sont liées à la citoyenneté, les données socio-économiques ne sont pas requises pour évaluer les causes de décès.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10051: {
        label:
          "(Id10051) [Est-il nécessaire de collecter des données démographiques supplémentaires sur le défunt ?]",
        hint: "Si vous choisissez « Non », cette question permet de ne pas demander de détails sur le lieu de résidence, l'éducation et la famille. La question sur le statut matrimonial sera toujours posée pour les adultes.",
        guidance:
          "Le site du projet déterminera si ces informations doivent être collectées. Si vous choisissez « NON », vous ignorerez les détails sur le lieu de résidence, l'éducation et la famille. Si vous sélectionnez « OUI », passez à la question suivante. Les programmeurs du site peuvent cacher cette question aux enquêteurs.",
        choices: {
          yes: "Oui",
          no: "Non"
        }
      },
      Id10052: {
        label: "(Id10052) Quelle était sa citoyenneté/nationalité ?",
        guidance:
          "Sélectionnez la réponse appropriée en fonction des définitions locales de la citoyenneté. Un citoyen naturalisé est une personne née ailleurs mais devenue citoyenne du pays. Un ressortissant étranger est une personne physique qui n’est pas citoyen du pays d’accueil dans lequel il réside ou séjourne temporairement.",
        choices: {
          citizen_at_birth: "Citoyen à la naissance",
          naturalized_citizen: "Citoyen naturalisé",
          foreign_national: "Ressortissant étranger",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10053: {
        label: "(Id10053) Quelle était son origine ethnique ?",
        hint: "Entrez un « - » si cette information n'est pas disponible.",
        guidance:
          "Enregistrez l’origine ethnique déclarée. N’insistez pas trop si la personne interrogée est mal à l’aise. Entrez « - », si cette information n'est pas disponible ou si le répondant n'est pas content de déclarer son origine ethnique."
      },
      Id10054: {
        label: "(Id10054) Quel était son lieu de naissance ?",
        hint: "Précisez ici le village et le quartier. Une question sur l'installation et les circonstances sera posée ultérieurement. Entrez un « - » si cette information n'est pas disponible.",
        guidance:
          "Enregistrez le lieu de naissance déclaré. Précisez ici le village et le quartier. Une question sur l'installation et les circonstances sera posée ultérieurement. Entrez un « - » si cette information n'est pas disponible ou inconnue."
      },
      Id10055: {
        label:
          "(Id10055) Quel était son lieu de résidence habituelle ? (l'endroit où la personne a vécu la majeure partie de l'année)",
        hint: "Pour les cas périnatals, il suffit de demander l'adresse de la formation sanitaire ou, en cas de sortie et à domicile, l'adresse du domicile.",
        guidance:
          "Pour les cas périnatals, il suffit de demander l'adresse de la formation sanitaire ou, en cas de sortie et à domicile, l'adresse du domicile. Pour les décès néonatals, le lieu de résidence sera généralement le même que celui où le décès est survenu."
      },
      Id10057: {
        label:
          "(Id10057) Où le décès est-il survenu ? (préciser le pays, la province, le district, le village)",
        hint: "Doit être complété selon les instructions du bureau central.",
        guidance:
          "Vous pouvez renseigner la ville/village au lieu du village si cela est plus pertinent. La question doit être adaptée spécifiquement au contexte local par l'équipe du projet."
      },
      Id10059: {
        label: "(Id10059) Quel était son état civil ?",
        hint: "Le partenaire de vie est défini ici comme vivant longtemps avec quelqu'un sans jamais s'être marié.",
        guidance:
          "Sélectionnez la réponse appropriée. Un partenaire de vie est semblable à un conjoint de fait. Ces termes désignent un partenariat dans lequel des personnes vivent ensemble de manière continue dans une relation équivalente au mariage. Les options de réponse fournies sont utilisées par les algorithmes. Notez qu'il peut être pertinent de définir des termes spécifiques et, si possible, d'utiliser la terminologie locale pour vérifier l'état civil, à condition que le sens original n'ait pas été modifié. Les options de réponse doivent être adaptées spécifiquement au contexte local par l’équipe du projet.",
        choices: {
          single: "Célibataire",
          married: "Marié(e)",
          partner: "Vie avec un Partenaire",
          divorced: "Divorcé(e)",
          widowed: "Veuf (ve)",
          too_young_to_be_married: "Trop jeune pour être marié(e)",
          DK: "Ne sait pas",
          Ref: "Refus de repondre"
        }
      },
      Id10063: {
        label: "(Id10063) Quel était son niveau de scolarité le plus élevé ?",
        guidance: "Sélectionnez la réponse appropriée.",
        choices: {
          no_formal_education: "Aucune éducation formelle",
          primary_school: "école primaire",
          secondary_school: "Secondary school",
          higher_than_secondary_school: "Higher than secondary school",
          DK: "Ne sait pas",
          Ref: "Refus de repondre"
        }
      },
      Id10064: {
        label: "(Id10064) Était-il capable de lire et/ou d'écrire ?",
        hint: "Cette question vise à mesurer l'alphabétisation (c'est-à-dire non le handicap), si la personne décédée a appris à lire et/ou à écrire au cours de sa vie.",
        guidance:
          "Sélectionnez la réponse appropriée. Répondez « OUI » également si le défunt ne connaissait qu'un seul élément de lecture ou d'écriture. Notez que cette question vise à mesurer l'alphabétisation (c'est-à-dire non le handicap), si la personne décédée a appris à lire et/ou à écrire au cours de sa vie.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10065: {
        label: "(Id10065) Quel était son statut d'activité économique l'année précédant son décès ?",
        hint: "Le défunt aurait pu avoir plusieurs activités.  Choisissez celle qui était probablement vraie pendant la majeure partie de l'année précédant la maladie ou le décès.",
        guidance:
          "Le défunt aurait pu avoir plusieurs activités. Choisissez celle qui était probablement vraie pendant la majeure partie de l’année précédant la maladie ou le décès. Sélectionnez la réponse appropriée. Si la réponse est « Principalement employé », passez à la question suivante. Sinon, passez à Id10476",
        choices: {
          mainly_unemployed: "Principalement au chômage",
          mainly_employed: "Employé",
          "home-maker": "Auxiliaire familial",
          pensioner: "Pensionné",
          student: "Etudiant",
          other: "Autres",
          DK: "Ne sait pas",
          Ref: "Refus de repondre"
        }
      },
      Id10066: {
        label:
          "(Id10066) Quelle était sa profession, c'est-à-dire quel genre de travail faisait-il principalement ?",
        guidance:
          "Cette question ne sera posée que si la réponse à Id10065 est « Principalement employé ». Enregistrez la réponse appropriée."
      },
      Id10061: {
        label: "(Id10061) Quel était le nom complet du père ?",
        guidance:
          "Enregistrez le nom complet du père. Déclarez les noms de façon standard sous forme de prénom (prénom) et de nom de famille. Ces informations peuvent être utilisées à des fins d’état civil et/ou pour faciliter l’appariement ou la localisation."
      },
      Id10062: {
        label: "(Id10062) Quel était le nom complet de la mère ?",
        guidance:
          "Enregistrez le nom complet de la mère. Déclarez les noms de façon standard sous forme de prénom (prénom) et de nom de famille. Ces informations peuvent être utilisées à des fins d’état civil et/ou pour faciliter l’appariement ou la localisation."
      },
      noteon: {
        label:
          "Enregistrez des notes détaillées de réponse ou enregistrez la réponse audio si l’option est disponible. Si nécessaire, demandez au répondant des détails supplémentaires sur le moment où le défunt a reconnu des symptômes, des anomalies, les soins recherchés, etc. Demandez au répondant si des dossiers médicaux datant de la période précédant le décès sont disponibles et enregistrez toute information pertinente. Certaines des questions suivantes peuvent être répétitives ou sans rapport avec le répondant, mais elles sont très importantes dans le processus d'attribution des COD.",
        guidance:
          "Demandez aux personnes interrogées de décrire les événements qui ont conduit au décès. Vous lirez \"Merci pour vos informations. Maintenant, pouvez-vous s'il vous plaît me raconter dans vos propres mots les événements qui ont conduit au décès ?\" Pendant la réponse, enregistrez des notes écrites détaillées de ce qui est mentionné ou enregistrez la réponse si l’option est disponible. Assurez-vous de capturer les éléments clés tels que les signes et symptômes, le moment de la recherche de soins et tous les points qui doivent être clarifiés. Si vous utilisez un système électronique de saisie de données (par exemple ODK), saisissez les notes dans le système électronique après avoir terminé l'entretien. Une fois que le répondant a terminé la réponse initiale, demandez-lui des informations supplémentaires, le cas échéant :\n ● Reconnaissance des symptômes (quand les premiers symptômes ont-ils été reconnus, quels autres symptômes présentait-il, quand le répondant/la famille s'est-il rendu compte qu'ils étaient graves, qui a reconnu les premiers et les plus graves symptômes) ;\n ● Le timing (combien de temps s'est écoulé entre les premiers symptômes et la prise de conscience de leur gravité) ; \n ● Actions entreprises à la maison et à l'extérieur du domicile (combien de temps après les premiers symptômes et symptômes graves une action a-t-elle été entreprise, quelles actions, un traitement a-t-il été administré, quel traitement, qui a pris la décision de demander ou non des soins, la raison de cette action, si des soins en dehors du domicile n'ont pas été demandés – pourquoi ?)\n ● Transport (temps passé entre la prise de décision de rechercher des soins à l'extérieur du domicile et l'obtention du transport, type de transport utilisé pour atteindre le premier niveau de soins et éventuelles références, temps passé pendant le transport, éventuels retards pouvant survenir avant d'atteindre les soins). \n ● Comportement du prestataire (conseils donnés, traitement administré, combien de temps a-t-il fallu pour recevoir les soins après avoir atteint les services de soins de santé, historique complet de référence, moment de la référence, temps passé à voyager vers et entre les établissements, raisons pour ne pas y aller ou retarder la référence, expérience de référence).\n Lorsque l’on tente d’identifier les décès suspects dus au COVID-19, le récit ouvert peut s’avérer très utile pour découvrir des détails et des informations importants non inclus dans la section des questions fermées du questionnaire VA. Pour obtenir des conseils sur les questions utiles qui peuvent être utilisées pour interroger les répondants sur les informations pertinentes pour le COVID-19, consultez le manuel d'orientation PCVA (qui sera disponible sur la page Web des normes VA de l'OMS). La liste de contrôle ci-dessous fournit une liste d'éléments supplémentaires qui peuvent être inclus dans le récit ouvert s'ils sont identifiés lors de l'entretien. N'hésitez pas à indiquer des éléments supplémentaires même s'ils ne figurent pas sur la liste de contrôle. \n LISTE DE CONTRÔLE DES ÉLÉMENTS SUPPLÉMENTAIRES À ENREGISTRER DANS L’ESPACE OUVERT NARRATIF\n ● S'il existe un avis officiel de la police ou médico-légal quant à la cause du décès – fourni par les autorités locales (généralement pour des accidents ou des blessures). Informations supplémentaires sur les blessures Si la famille a signalé une blessure, enregistrez les détails de la blessure (type, mode, lieu de l'événement et parties du corps affectées qui ont été blessées) ;\n ● S'il s'agit d'un acte auto-infligé même si vous ne l'avez pas demandé ;\n ● s'il s'agit d'un accident de transport autre que routier, par ex. blessure mortelle causée par un train/un bateau/un avion ; \n ● En cas de chute, enregistrer les parties du corps blessées ; \n ● En cas d'intoxication par des pesticides, du kérosène ou tout autre produit chimique, enregistrez le type de poison ;\n ● En cas de noyade, enregistrer le lieu où la noyade s'est produite – rivière/lac/mer/piscine, etc. ;\n ● En cas de blessure par brûlure/incendie, enregistrer toutes les parties du corps touchées par les brûlures et la manière dont la brûlure s'est produite ;\n ● Si vous êtes blessé par une force de la nature, enregistrez le type de force de la nature (foudre, inondation, tremblement de terre, etc.). \n Constatations supplémentaires chez le défunt\n ● Si la personne décédée présentait des malformations congénitales, décrivez les parties du corps et à quoi elles ressemblaient, et/ou si la personne décédée avait des organes génitaux/intersexués ambigus. \n ● Si vous avez enregistré le poids à la naissance qui vous a été donné et qu'il a été auto-déclaré (non vérifié dans les dossiers), alors enregistrez ici que le poids à la naissance a été déclaré par l'enquêtée. \n ● Si la personne décédée semblait en bonne santé et est décédée subitement (de manière inattendue dans les 24 heures après avoir été en bonne santé) et qu'il existe d'autres détails sur le décès, enregistrez-les (par exemple, s'il s'est produit pendant le sommeil). Dans certains cas, il peut s'agir de la principale information fournie par le répondant. \n ● Si la personne décédée a récemment eu une visite médicale, notez tous les détails du diagnostic, des tests de laboratoire, du traitement, etc. dans la section narrative ouverte du questionnaire.\n ● S'il existe des informations supplémentaires sur les services de santé ou des avis médicaux fournis sur la cause du décès du défunt qui aurait pu avoir reçu des soins médicaux avant son décès, indiquez-le ici. \n ● Si la personne décédée a reçu ou a eu besoin d'un traitement ou si de la nourriture est passée par le nez, demandez combien de temps l'alimentation a été fournie par la sonde et si la sonde était en place avant le décès, et enregistrez les informations pertinentes ici. \n ● Si le défunt présentait des bosses sur le cou, s'il y avait une opinion quant à la cause médicale de la bosse et s'il a reçu un traitement, enregistrez ici les informations pertinentes. \n ● Si la personne décédée a subi une opération, demandez au répondant s'il connaît le problème de santé (par exemple, cancer, ulcère d'estomac, maladie cardiaque, etc.) qui a motivé l'opération ; notez les détails pertinents ici.\n Informations sur la mère et l'accouchement\n ● Pour les mortinaissances et les décès néonatals, enregistrez tous les détails de la grossesse, du travail et de l'accouchement. \n ● Si l'eau s'est rompue lors de la livraison et que l'eau était anormale, notez toute description ici. \n ● Si la mère est décédée et que vous avez obtenu des informations supplémentaires, enregistrez ce que vous avez appris sur le décès de la mère (par exemple, le moment du décès par rapport à l'accouchement, les symptômes, etc.)."
      },
      Id10476_audio: {
        label:
          "(Id10476_audio) Merci pour vos informations. Maintenant, pouvez-vous s'il vous plaît me raconter dans vos propres mots les événements qui ont conduit à cette mort ?",
        hint: "[Enregistrez les informations audio ou sautez et saisissez le texte de la question suivante]"
      },
      Id10476: {
        label:
          "(Id10476) Merci pour vos informations. Maintenant, pouvez-vous s'il vous plaît me raconter dans vos propres mots les événements qui ont conduit à cette mort ?",
        hint: '[Si aucune information n\'est disponible, veuillez saisir "aucune information disponible"]'
      },
      Id10477: {
        label:
          "(Id10477) [Sélectionnez l'un des mots suivants qui ont été mentionnés comme présents dans le récit.]",
        guidance:
          "Cette question énumère certains des principaux risques associés à la mortalité dans le groupe d'âge des personnes décédées. Une fois que le répondant a fourni sa description des circonstances entourant le décès, relisez et notez tous les mots clés qu'il a pu mentionner et que le défunt possédait.",
        constraintMessage:
          "Il n'est pas possible de sélectionner « Ne sait pas » ou « Aucune des réponses ci-dessus » avec d'autres options.",
        choices: {
          Chronic_kidney_disease: "Maladie rénale chronique",
          Dialysis: "Dialyse",
          Fever: "Fièvre",
          Heart_attack: "Crise cardiaque",
          Heart_problem: "Problème cardiaque",
          Jaundice: "Jaunisse",
          Liver_failure: "Insuffisance hépatique",
          Malaria: "Paludisme",
          Pneumonia: "Pneumonie",
          Renal_kidney_failure: "Insuffisance rénale (reine)",
          Suicide: "Suicide",
          None: "Aucun des mots ci-dessus n'a été mentionné"
        }
      },
      Id10478: {
        label:
          "(Id10478) [Sélectionnez l'un des mots suivants qui ont été mentionnés comme présents dans le récit.]",
        guidance:
          "Cette question énumère certains des principaux risques associés à la mortalité dans le groupe d'âge des personnes décédées. Une fois que le répondant a fourni sa description des circonstances entourant le décès, relisez et notez tous les mots clés qu'il a pu mentionner et que le défunt possédait.",
        constraintMessage:
          "Il n'est pas possible de sélectionner « Ne sait pas » ou « Aucune des réponses ci-dessus » avec d'autres options.",
        choices: {
          abdomen: "Abdomen",
          cancer: "Cancer",
          dehydration: "Déshydratation",
          dengue: "Dengue",
          diarrhea: "Diarrhée",
          fever: "Fièvre",
          heart_problem: "Problèmes cardiaques",
          jaundice: "Jaunisse (peau ou yeux jaunes)",
          pneumonia: "Pneumonie",
          rash: "Éruption cutanée",
          None: "Aucun des mots ci-dessus n'a été mentionné"
        }
      },
      Id10479: {
        label:
          "(Id10479) [Sélectionnez l'un des mots suivants qui ont été mentionnés comme présents dans le récit.]",
        guidance:
          "Cette question énumère certains des principaux risques associés à la mortalité dans le groupe d'âge des personnes décédées. Une fois que le répondant a fourni sa description des circonstances entourant le décès, relisez et notez tous les mots clés qu'il a pu mentionner et qui étaient présents dans le mot du défunt.",
        constraintMessage:
          "Il n'est pas possible de sélectionner « Ne sait pas » ou « Aucune des réponses ci-dessus » avec d'autres options.",
        choices: {
          asphyxia: "Asphyxie",
          incubator: "Incubateur",
          lung_problem: "Problème pulmonaire",
          pneumonia: "Pneumonie",
          preterm_delivery: "Accouchement prématuré",
          respiratory_distress: "Détresse respiratoire",
          None: "Aucun des mots ci-dessus n'a été mentionné"
        }
      },
      notenarr: {
        label:
          "Certaines des questions suivantes peuvent être répétitives ou sans rapport avec le répondant, mais elles sont très importantes dans le processus d'attribution des COD."
      },
      Id10104: {
        label: "(Id10104) Le bébé a-t-il déjà pleuré ?",
        guidance:
          "Pleurer est un signe de respiration. Si un bébé a pleuré à la naissance, cela indique qu’il était vivant à la naissance. Dans certains cas, le bébé peut ne pas pleurer mais il peut quand même y avoir un effort respiratoire visible, mais cela peut être difficile à observer. D’où le recours au cri de naissance, pour signifier la respiration, et donc la vie. Il y a une question distincte sur la respiration plus loin dans cette section. Cette question ne concerne que les pleurs. Il s’agit d’une question filtre importante, car une réponse négative indiquera une mortinatalité. La mortinaissance fait référence aux bébés nés sans signe de vie à 28 semaines de gestation ou après. La mort fœtale avant 28 semaines est considérée comme un avortement ou une fausse couche. Si « NON/NSP/Réf », passez à Id10377. Si « OUI », passez à la question suivante.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10105: {
        label:
          "(Id10105) Le bébé a-t-il pleuré immédiatement après la naissance, même si ce n'est qu'un petit peu ?",
        guidance:
          "Le moment du premier cri indique si la santé du bébé a été affectée par les événements survenus pendant la grossesse, le travail ou l’accouchement. Sondez soigneusement si le bébé a pleuré immédiatement après la naissance et, si c'est le cas, enregistrez la réponse comme « OUI ». Dans certains cas, il peut y avoir un certain délai (de une à plusieurs minutes) entre la naissance et le premier cri. Dans un tel cas, enregistrez la réponse comme « NON » et passez à la question suivante.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10106: {
        label:
          "(Id10106) Combien de minutes après la naissance le bébé a-t-il pleuré pour la première fois ?",
        hint: "Si l'enquêté est incapable de répondre, posez la question : Le bébé a-t-il pleuré pour la première fois dans les 5 minutes (l'enquêteur doit saisir 4 minutes) ou après plus de 5 minutes (l'enquêteur doit saisir 6 minutes) ? Pour je ne sais pas, entrez « 99 ». Pour refusé, entrez « 88 ». Si la personne interrogée dit que le bébé n'a jamais pleuré, revenez en arrière et entrez « Non » à la réponse « Le bébé a-t-il déjà pleuré ?",
        guidance:
          "Cette question est pertinente pour les deux réponses potentielles à la question précédente. Si la réponse à Id10105 était « OUI », alors cette question vise à confirmer le timing. Si le bébé a pleuré immédiatement, enregistrez « 0 » (zéro) minute. Cependant, si les pleurs ont été retardés, le temps écoulé entre la naissance et le premier cri est un indicateur utile pour évaluer si le bébé est décédé à la suite d'événements survenus pendant le travail ou l'accouchement. Sondez attentivement pour connaître l'heure et enregistrez-la en minutes. Une réponse valide dure entre 0 et 60 minutes. Si l'enquêté ne se souvient pas de l'intervalle de temps exact entre la naissance et le premier cri, invitez et enregistrez en fonction de ce qui est médicalement pertinent à saisir : si le bébé a pleuré environ dans les 5 minutes (l'enquêteur doit saisir 4 minutes) ; ou si bébé a pleuré environ après plus de 5 minutes (l'enquêteur doit saisir 6 minutes). Pour « ne sait pas », inscrivez « 99 ». Pour « refusé de répondre », inscrivez « 88 ». Si la personne interrogée déclare que le bébé n'a jamais pleuré, revenez à Id10104 et entrez la bonne réponse.",
        constraintMessage:
          "Entrez un nombre entre 1 et 60. Si le répondant dit que le bébé n'a jamais pleuré, revenez en arrière et inscrivez « Non », le bébé n'a jamais pleuré."
      },
      Id10107: {
        label: "(Id10107) Le bébé a-t-il cessé de pleurer ?",
        guidance:
          "Un bébé qui a pleuré à la naissance peut devenir faible et cesser de pleurer plus tard. Il s'agit d'un indicateur de certaines causes de décès néonatals. Sondez attentivement pour obtenir la vraie réponse.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10377: {
        label: "(Id10377) Le bébé a-t-il arrêté de bouger dans l'utérus ?",
        guidance:
          "Des mouvements réduits conduisant à une absence totale de mouvement, en particulier dans les jours ou les heures précédant l'accouchement, peuvent être le signe que le décès est survenu avant l'accouchement. Il s’agit au minimum d’un signe avant-coureur d’un problème de santé du fœtus. Les mères sont généralement conscientes de ces changements et peuvent se souvenir et signaler ce signe. Si la réponse est « NON/NSP/Réf », passez à Id10109.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10376: {
        label: "(Id10376) Le bébé a-t-il arrêté de bouger avant ou après le début du travail ?",
        guidance:
          "Cette question vise à confirmer le bien-être du fœtus pendant la période précédant l'accouchement. L’absence de mouvements suggère la possibilité que le bébé soit mort-né. Notez que cette question n’est pas obligatoire pour le logiciel d’analyse automatisée, mais elle sert de contrôle de cohérence interne.",
        choices: {
          before: "Avant",
          after: "Après",
          dk: "Je ne sais pas",
          ref: "A refusé de répondre"
        }
      },
      Id10109: {
        label: "(Id10109) Le bébé a-t-il déjà bougé après l'accouchement ?",
        guidance:
          "Semblable à la question sur le premier cri après la naissance, cette question est également très importante pour comprendre si l'enfant était mort-né ou vivant à la naissance. Sondez attentivement pour savoir si la mère a remarqué un mouvement du bébé après la naissance, en termes de mouvement des membres ou de la tête. Les mouvements liés à la respiration sont abordés dans la question suivante.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10110: {
        label: "(Id10110) Le bébé a-t-il déjà respiré ?",
        guidance:
          "Si la réponse à cette question est « OUI », cela confirme qu'il s'agit d'une naissance vivante. Comme mentionné précédemment, même si le bébé n'a pas pleuré à la naissance, l'accoucheuse ou la mère peut avoir remarqué un effort respiratoire. Cette question permet de comprendre si le nourrisson était mort-né ou vivant au moment de la naissance. Dans certains cas, il peut y avoir une certaine hésitation ou confusion de la part du répondant, dans la réponse à la question précédente. Cette question permet également de confirmer la présence d'un effort respiratoire, qui peut avoir été observé sous forme de mouvement de la paroi thoracique, des muscles du cou ou des narines. Ce sont des signes subtils. Un léger effort respiratoire est un signe de vie et fait la distinction entre un enfant vivant et un enfant mort-né. Si la réponse est « NON », il s’agit d’une réponse négative importante, qui pourrait conduire au diagnostic de mortinatalité. Par conséquent, toute réponse négative « NSP/Réf » doit être clarifiée et confirmée. Si « NON/NSP/Réf », passez à Id10114.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10111: {
        label: "(Id10111) Le bébé a-t-il respiré immédiatement après la naissance, même un peu ?",
        guidance:
          "Cette question permet de confirmer une réponse positive à la question précédente. Sondez attentivement pour obtenir la vraie réponse afin de faire cette distinction importante, et notez « OUI » si le bébé a respiré immédiatement après la naissance. En revanche, s’il y a un certain retard dans le début de la respiration, cela constitue un indicateur important concernant la cause potentielle du décès. Dans ce cas, notez la réponse « NON » et passez à la question suivante.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10112: {
        label: "(Id10112) Le bébé avait-il un problème respiratoire ?",
        guidance:
          "Cette question précise s'il y avait un problème notable concernant la respiration du bébé. La reconnaissance d'un problème respiratoire à la naissance est un indicateur important de conditions telles que l'asphyxie à la naissance.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10113: {
        label: "(Id10113) Le bébé a-t-il reçu une aide pour respirer à la naissance ?",
        guidance:
          "Le fait d’accorder une attention particulière à l’assistance respiratoire à la naissance indique qu’il existe un grave problème de santé du nouveau-né. L'assistance peut prendre la forme d'une stimulation/frottement du dos/des fesses, d'une compression thoracique ou d'une réanimation orale. Le répondant s'en souviendrait facilement et devrait être confirmé en cas de réponse positive. Une aide à la respiration aurait pu être fournie aussi bien pour les mortinaissances que pour les naissances vivantes présentant une respiration retardée/difficile, la réponse doit donc être prise en conjonction avec les réponses aux questions précédentes.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10114: {
        label: "(Id10114) Si le bébé n'a montré aucun signe de vie, est-il mort-né ?",
        hint: "Cette question sert à déterminer enfin si le bébé est né vivant ou mort.",
        guidance:
          "Cette question sert à déterminer enfin si le bébé est né vivant ou mort. Cette question ne doit être posée que si les réponses à Id10104 ; Id10109 ; et Id10110 sont n'importe quelle combinaison de \"NO/DK/Ref\". Une réponse « OUI » à cette question indiquerait que le bébé est mort-né. Dans ce cas, la réponse « OUI » devra être suivie des questions Id10115 et Id10116 ; et les instructions suivantes après Id10116. D'un autre côté, il peut y avoir une possibilité que malgré la nature des réponses aux questions précédentes, le répondant puisse dire « NON » (c'est-à-dire que le bébé n'est pas mort-né), dans ce cas, passer à la question suivante, c'est-à-dire Id10115.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10115: {
        label:
          "(Id10115) Y a-t-il eu des contusions ou des signes de blessures sur le corps du bébé après la naissance ?",
        guidance:
          "Une blessure à la naissance désigne une blessure survenue pendant la naissance, telle qu'une grosse ecchymose, un gonflement de la tête ou une fracture pouvant entraîner la mort de l'enfant. Après avoir demandé et enregistré la réponse à Id10115, appliquez les instructions suivantes, qui sont basées sur la réponse à Id10114. Si la réponse à Id10114 était « OUI » (c'est-à-dire enfant mort-né) ; puis passez à Id10116. Si la réponse à Id10114 était « NON/NSP/Réf » (c'est-à-dire né vivant) ; puis passez à Id10077",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10116: {
        label: "(Id10116) Le corps du bébé était-il mou, décoloré et la peau se décollait-elle ?",
        hint: "Macéré signifie que le corps était pulpeux. Cela indique que le bébé est mort à l'intérieur de la mère depuis un certain temps.",
        guidance:
          "Posez cette question uniquement si la réponse à Id10114 était « OUI », c'est-à-dire qu'il s'agissait d'une mortinatalité. Dans cette question, nous cherchons à évaluer l’intégrité de la peau d’un bébé mort-né. Parfois, le terme « macéré » est utilisé pour décrire la peau des bébés mort-nés. Lorsque macéré est utilisé pour décrire la peau, cela signifie que la peau, parfois décolorée, a pelé ou est en train de peler. Macéré signifie que le corps était pulpeux. Cela indique que le bébé est mort à l'intérieur de la mère ou depuis un certain temps. Si le terme macéré n'est pas utilisé, écoutez une description similaire de l'intégrité de la peau – desquamation, pulpeuse, décolorée, etc. Après Id10116, s'il s'agissait d'une mortinatalité, passez à Id10354.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      note_s_s: {
        label:
          "Expliquez au répondant que la section suivante contient une série de questions visant à savoir si un diagnostic d'un professionnel de la santé a été obtenu pour un certain nombre de maladies. Précisez que le but de cette série est le diagnostic médical de maladies spécifiques, et non les signes et symptômes ou la cause perçue du décès par le répondant."
      },
      Id10125: {
        label: "(Id10125) Y a-t-il eu un diagnostic de tuberculose par un professionnel de la santé ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10126: {
        label: "(Id10126) Un test VIH a-t-il déjà été positif ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si la personne décédée a déjà subi un test de dépistage du VIH et, si oui, si le test s'est déjà révélé positif.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10127: {
        label: "(Id10127) Y a-t-il eu un diagnostic de SIDA par un professionnel de la santé ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si le défunt a déjà reçu un diagnostic de SIDA, la dernière maladie liée au VIH qui entraîne la mort. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10128: {
        label:
          "(Id10128) A-t-il récemment subi un test positif pour le paludisme par un professionnel de la santé ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si un test de paludisme (bandelette ou prise de sang) a été effectué pendant la maladie qui a entraîné le décès et, si « oui », si le test était positif. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie. Si la réponse à cette question est « OUI », passez à Id10482.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10129: {
        label:
          "(Id10129) A-t-il récemment subi un test négatif de dépistage du paludisme par un professionnel de la santé ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si un test de paludisme (bandelette ou prise de sang) a été effectué pendant la maladie qui a conduit au décès et si « oui », il était négatif. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10482: {
        label: "(Id10482) Y a-t-il eu un diagnostic de COVID-19 par un professionnel de la santé ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si la personne décédée a déjà reçu un diagnostic de COVID-19. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10483: {
        label: "(Id10483) A-t-elle récemment subi un test de dépistage du COVID-19 ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si un test de dépistage de la COVID-19 (prélèvement nasal/gorge ou bandelette réactive ; tests viraux rapides ou tests de laboratoire) a été effectué pendant la maladie qui a entraîné le décès. A noter que les tests rapides sont réalisés ou interprétés par un professionnel de santé dans un établissement de santé. Les tests de laboratoire comprennent la RT-PCR et d'autres types de tests d'amplification des acides nucléiques (NAATS). Si la réponse à cette question est « NON », passez à Id10130.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10484: {
        label: "(Id10484) Quel a été le résultat ?",
        hint: "Demander le résultat du test le plus récent au cas où le défunt aurait subi plus d'un test",
        guidance:
          "Si la personne décédée a subi un test de dépistage du COVID-19, demandez-lui doucement quel a été le résultat. Si une personne a été testée plus d'une fois au cours de sa dernière maladie, vérifiez si le DERNIER test était « positif », « négatif » ou « incertain ».",
        choices: {
          positive: "Positif",
          negative: "Négatif",
          unclear: "Peu clair",
          dk: "Je ne sais pas",
          ref: "A refusé de répondre"
        }
      },
      Id10130: {
        label: "(Id10130) Y a-t-il eu un diagnostic de dengue par un professionnel de la santé ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si un diagnostic de dengue a été posé pendant la maladie qui a entraîné le décès. Il existe peut-être un terme local pour désigner la dengue. S'il y en a un, assurez-vous qu'il est mentionné dans le questionnaire traduit et utilisez ce terme pour poser des questions sur la dengue. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10131: {
        label: "(Id10131) Y a-t-il eu un diagnostic de rougeole par un professionnel de la santé ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si un diagnostic de rougeole a été posé pendant la maladie qui a entraîné le décès. Il existe peut-être un terme local pour désigner la rougeole. S'il y en a un, assurez-vous qu'il est mentionné dans le questionnaire traduit et utilisez ce terme pour poser des questions sur la rougeole. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10132: {
        label:
          "(Id10132) Y a-t-il eu un diagnostic d'hypertension artérielle par un professionnel de la santé ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si la personne décédée a déjà reçu un diagnostic d'hypertension artérielle de la part d'un médecin ou de tout autre agent de santé. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie. Il peut exister un terme local pour désigner l'hypertension. S'il y en a un, assurez-vous qu'il est mentionné dans le questionnaire traduit et utilisez ce terme pour approfondir.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10133: {
        label: "(Id10133) Un professionnel de la santé a-t-il diagnostiqué une maladie cardiaque ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si la personne décédée a déjà reçu un diagnostic de maladie cardiaque par un médecin ou tout autre agent de santé. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10134: {
        label: "(Id10134) Un professionnel de la santé a-t-il diagnostiqué un diabète ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si la personne décédée a reçu un diagnostic de diabète par un médecin ou tout autre agent de santé. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie. Il existe peut-être un terme local pour désigner le diabète. S'il y en a un, assurez-vous qu'il est mentionné dans le questionnaire traduit et utilisez le terme local pour approfondir.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10135: {
        label: "(Id10135) Y a-t-il eu un diagnostic d'asthme par un professionnel de la santé ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si la personne décédée a reçu un diagnostic d'asthme d'un médecin ou de tout autre agent de santé. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie. Il peut exister un terme local pour désigner l'asthme. S'il y en a un, assurez-vous qu'il est mentionné dans le questionnaire traduit et utilisez le terme local pour approfondir. Vous devrez peut-être démontrer à quel point un patient asthmatique aura du mal à respirer.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10136: {
        label: "(Id10136) Y a-t-il eu un diagnostic d'épilepsie par un professionnel de la santé ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si la personne décédée a reçu un diagnostic d'épilepsie d'un médecin ou de tout autre agent de santé. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie. Il existe peut-être un terme local pour désigner l'épilepsie. S'il y en a un, assurez-vous qu'il est mentionné dans le questionnaire traduit et utilisez le terme local pour approfondir. Vous devrez peut-être démontrer un épisode d'épilepsie.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10137: {
        label: "(Id10137) Y a-t-il eu un diagnostic de cancer par un professionnel de la santé ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si la personne décédée a déjà reçu un diagnostic de cancer de la part d'un médecin ou de tout autre agent de santé. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie. Il existe peut-être un terme local pour désigner le cancer. S'il y en a un, assurez-vous qu'il est mentionné dans le questionnaire traduit et utilisez le terme local pour approfondir.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10138: {
        label:
          "(Id10138) Un professionnel de la santé a-t-il diagnostiqué une maladie pulmonaire obstructive chronique (MPOC) ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si la personne décédée a reçu un diagnostic de BPCO par un médecin ou tout autre agent de santé. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie. Les personnes atteintes de BPCO ont de fréquentes périodes d'essoufflement ainsi que des accès de toux et d'expectorations, nécessitant souvent des soins médicaux pour un soulagement et un traitement.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10139: {
        label: "(Id10139) Un professionnel de la santé a-t-il diagnostiqué une démence ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si la personne décédée a déjà reçu un diagnostic de démence de la part d'un médecin ou de tout autre agent de santé. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie. Vous devrez peut-être connaître le terme local désignant la démence. Il s’agit d’une condition dans laquelle la personne devient plus oublieuse, ce qui se produit généralement chez les personnes âgées. S'il existe un terme local, assurez-vous qu'il est mentionné dans le questionnaire traduit et utilisez le terme local pour approfondir.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10140: {
        label: "(Id10140) Un professionnel de la santé a-t-il diagnostiqué une dépression ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si la personne décédée a déjà reçu un diagnostic de dépression de la part d'un médecin ou de tout autre agent de santé. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie. Vous devrez peut-être trouver le terme local pour désigner la dépression. Il s'agit d'une condition dans laquelle la personne devient plus retirée de sa famille et de sa communauté, isolée, moins communicative et malheureuse. S'il existe un terme local pour désigner la dépression, assurez-vous qu'il est mentionné dans le questionnaire traduit et utilisez le terme local pour approfondir.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10141: {
        label: "(Id10141) Un professionnel de la santé a-t-il diagnostiqué un accident vasculaire cérébral ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si un médecin ou tout autre agent de santé a diagnostiqué un accident vasculaire cérébral chez la personne décédée. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie. Il peut y avoir un terme local pour désigner un accident vasculaire cérébral. Il s’agit d’une condition dans laquelle la personne perd soudainement connaissance et/ou présente une paralysie d’un côté du corps. S'il existe un terme local pour désigner l'AVC, assurez-vous qu'il est mentionné dans le questionnaire traduit et utilisez le terme local pour approfondir.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10142: {
        label: "(Id10142) Y a-t-il eu un diagnostic de drépanocytose par un professionnel de la santé ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si la personne décédée a déjà reçu un diagnostic de drépanocytose par un médecin ou tout autre agent de santé. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie. Il existe peut-être un terme local pour désigner la drépanocytose. Il s’agit d’une condition dans laquelle la personne présente une fluidification du sang et tombe malade à plusieurs reprises et est diagnostiquée en examinant le sang. S'il existe un terme local, assurez-vous qu'il est mentionné dans le questionnaire traduit et utilisez le terme local pour approfondir.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10143: {
        label: "(Id10143) Un professionnel de la santé a-t-il diagnostiqué une maladie rénale ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si la personne décédée a reçu un diagnostic de maladie rénale par un médecin ou tout autre agent de santé récemment ou au cours de la dernière maladie. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie. Il peut exister un terme local pour désigner une maladie rénale. S'il y en a un, assurez-vous qu'il est mentionné dans le questionnaire traduit et utilisez le terme local pour approfondir.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10144: {
        label: "(Id10144) Un professionnel de la santé a-t-il diagnostiqué une maladie du foie ?",
        hint: "Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie.",
        guidance:
          "Demandez si un médecin ou tout autre agent de santé a diagnostiqué une maladie du foie chez la personne décédée récemment ou au cours de la dernière maladie. Rappelez à l'enquêté que nous demandons le diagnostic évalué par un médecin, un agent de santé ou un autre professionnel de la santé lors de la dernière maladie. Il peut exister un terme local pour désigner une maladie du foie. S'il y en a un, assurez-vous qu'il est mentionné dans le questionnaire traduit et utilisez le terme local pour approfondir.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      nmh: {
        label:
          "Sauf indication contraire, les questions suivantes sur les signes, les symptômes, le traitement et les circonstances se rapportent spécifiquement à la maladie et à la période de maladie qui a entraîné le décès."
      },
      Id10077: {
        label: "(Id10077) A-t-il subi une blessure ou un accident ayant entraîné sa mort ?",
        guidance:
          "Il s'agit d'une question d'ouverture pour vérifier si le décès était associé à une blessure ou à un accident. Si la réponse est « OUI », passez aux questions suivantes. Ces questions sont généralement simples et faciles à comprendre, avec peu de risque d'erreur dans la réponse, sauf en cas de stigmatisation ou d'appréhension d'une implication dans la police ou une autre administration. Nouveau-né : Si la réponse est « NON », passez à Id10351. Cependant, si la réponse est « NSP/Réf », l'enquêteur doit approfondir la question et passer aux questions suivantes. Enfants : Si la réponse est « NON », passez au Id10408. Cependant, si la réponse est « NSP/Réf », l'enquêteur doit approfondir la question et passer aux questions suivantes. Adulte : Si la réponse est « NON », passez à Id10120_unit. Cependant, si la réponse est « NSP/Réf », l'enquêteur doit approfondir la question et continuer avec les questions suivantes à Id10079.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10077_a: {
        label: "(Id10077_a) Combien de temps après la blessure ou l'accident est-il décédé ?",
        hint: "Déterminez si la personne décédée est décédée dans les 7 jours ou plus suivant l'accident ou la blessure qui a entraîné la mort. Ceci est important car cela déterminera la durée de l’entretien VA. Si dans les 7 jours, le défunt est probablement décédé des suites de l'accident ou de la blessure et seules les questions maternelles seront posées en plus de la section sur les blessures. Si plus de 7 jours, l'entretien VA complet sera mené.",
        choices: {
          less: "inférieur ou égal à 7 jours",
          more: "plus de 7 jours",
          dk: "Je ne sais pas",
          ref: "A refusé de répondre"
        }
      },
      Id10077_b: {
        label:
          "(Id10077_b) [L'enquêteur clique sur « OK » pour confirmer la réponse : Elle/est décédée à moins ou égale à 7 jours après l'accident]",
        guidance:
          "Déterminez si le défunt est décédé dans les 7 jours ou plus suivant l'accident ou la blessure qui a entraîné le décès. Ceci est important car cela déterminera la durée de l’entretien VA. Si dans les 7 jours, le défunt est probablement décédé des suites de l'accident ou de la blessure et seules quelques questions maternelles seront posées en plus de la section sur les blessures. Si plus de 7 jours, l'entretien VA complet sera mené."
      },
      Id10079: {
        label: "(Id10079) Était-ce un accident de transport routier ?",
        guidance:
          "Les accidents dus au transport routier sont la cause la plus fréquente de décès par traumatisme dans les pays en développement. Il n'est pas nécessaire d'avoir été à bord d'un véhicule pour avoir subi un accident de la route, par exemple en cas de décès de piétons. Si la réponse à Id10079 est « OUI », les questions Id10082 à Id10097 doivent être ignorées. Si la réponse est « NON/NSP/Réf », passez au Id10082.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10082: {
        label: "(Id10082) S'agit-il d'une blessure liée au transport non routier ?",
        hint: "Les blessures liées au transport non routier comprennent celles impliquant le transport aérien (par exemple avion), ferroviaire (par exemple train), maritime ou fluvial (par exemple bateau, canoë).",
        guidance:
          "Renseignez-vous et enregistrez si le décès est dû à une blessure survenue lors d'un transport autre que sur la route. Il s’agit notamment des blessures mortelles liées au transport aérien (par exemple avion), ferroviaire (par exemple train), maritime ou fluvial (par exemple bateau, canoë). Si « OUI », indiquez la nature de l'accident et les blessures subies dans la partie texte libre du questionnaire. Si la réponse à Id10082 est « OUI », les questions Id10083 à Id10097 doivent être ignorées. Si la réponse est « NON/NSP/Réf », passez au Id10083.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10083: {
        label: "(Id10083) A-t-il été blessé lors d'une chute ?",
        hint: "Cela inclut les accidents et les cas où l’on ne sait pas s’il s’agit d’un accident ou s’il y a eu violence intentionnelle.",
        guidance:
          "Si la réponse est « OUI », enregistrez les parties du corps qui ont été blessées dans la section narrative du questionnaire. Cela inclut les accidents et les cas où l'on ne sait pas s'il s'agit d'un accident ou s'il y a eu violence intentionnelle. Si la réponse à Id10083 est « OUI », les questions Id10084 à Id10097 doivent être ignorées. Si la réponse est « NON/NSP/Réf », passez au Id10084.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10084: {
        label: "(Id10084) Y a-t-il eu un empoisonnement ?",
        hint: "Cela inclut les accidents et les cas où l’on ne sait pas s’il s’agit d’un accident ou s’il y a eu violence intentionnelle.",
        guidance:
          "Si le décès est dû à un empoisonnement aux pesticides, au kérosène ou à tout autre produit chimique, inscrivez « OUI » ici et notez la nature du poison dans la section narrative. Cela inclut les accidents et les cas où l’on ne sait pas s’il s’agit d’un accident ou s’il y a eu violence intentionnelle. L'empoisonnement par morsure de serpent ou piqûre d'animal, etc. ne doit pas être inclus ici. Si la réponse à Id10084 est « OUI », les questions Id10085 à Id10097 doivent être ignorées. Si la réponse est « NON/NSP/Réf », passez au Id10085.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10085: {
        label: "(Id10085) Est-il mort noyé ?",
        hint: "Cela inclut les accidents et les cas où l’on ne sait pas s’il s’agit d’un accident ou s’il y a eu violence intentionnelle.",
        guidance:
          "Si la réponse est « OUI », indiquez le lieu où la noyade s'est produite – rivière/lac/mer/piscine – dans la partie narrative du questionnaire. Cela inclut les accidents et les cas où l'on ne sait pas s'il s'agit d'un accident ou s'il y a eu violence intentionnelle. Si la réponse à Id10085 est « OUI », les questions Id10086 à Id10097 doivent être ignorées. Si la réponse est « NON/NSP/Réf », passez au Id10086.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10086: {
        label:
          "(Id10086) A-t-il été blessé par une morsure ou une piqûre venimeuse d'un animal ou d'un insecte ?",
        hint: "Cela inclut les accidents et les cas où l’on ne sait pas s’il s’agit d’un accident ou s’il y a eu violence intentionnelle.",
        guidance:
          "Enregistrez « OUI » si la blessure est due à une morsure de serpent ou à tout autre insecte venimeux. Cela inclut les accidents et les cas où l’on ne sait pas s’il s’agit d’un accident ou s’il y a eu violence intentionnelle. Si « OUI », passez à Id10088.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10087: {
        label: "(Id10087) A-t-il été blessé par un animal ou un insecte (non venimeux) ?",
        guidance:
          "Enregistrez « OUI » en cas de morsure de chien ou de blessures causées par une attaque par un autre animal et notez le détail dans la réponse à la question suivante. Si « NON/NSP/Réf », passez à Id10089.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10088: {
        label: "(Id10088) Quel était l'animal/l'insecte ?",
        guidance:
          "Sélectionnez un chien, un serpent, un insecte, un scorpion ou autre. Si vous ne le savez pas, sélectionnez « NSP ».",
        choices: {
          dog: "Chien",
          snake: "serpent",
          insect_or_scorpion: "insecte ou scorpion",
          other: "autres",
          DK: "Ne sait pas",
          Ref: "Refus de repondre"
        }
      },
      Id10089: {
        label: "(Id10089) A-t-il été blessé par des brûlures/un incendie ?",
        guidance:
          "Les brûlures entraînant la mort couvrent généralement de vastes parties du corps. Si la réponse est « OUI », alors enregistrez les parties du corps affectées par les brûlures dans la section narrative du questionnaire. Si la réponse à Id10089 est « OUI », les questions Id10091–Id10097 doivent être ignorées. Si la réponse est « NON/NSP/Réf », passez au Id10091.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10091: {
        label: "(Id10091) A-t-il été blessé par une arme à feu ?",
        guidance:
          "Utilisez le terme local pour désigner les armes à feu et enregistrez la réponse. Si la réponse à Id10091 est « OUI », les questions Id10092 à Id10097 doivent être ignorées. Si la réponse est « NON/NSP/Réf », passez au Id10092.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10092: {
        label: "(Id10092) A-t-il été poignardé, coupé ou percé ?",
        guidance:
          "L’utilisation d’instruments tranchants tels qu’un couteau ou une épée doit être enregistrée ici. Si la réponse à Id10092 est « OUI », les questions Id10093 à Id10097 doivent être ignorées. Si la réponse est « NON/NSP/Réf », passez au Id10093.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10093: {
        label: "(Id10093) A-t-il été étranglé ?",
        guidance:
          "Utilisez le terme local pour désigner l'étouffement du cou par la force, que ce soit avec la main, une corde ou un autre objet. Si la réponse à Id10093 est « OUI », les questions Id10094 à Id10097 doivent être ignorées. Si la réponse est « NON/NSP/Réf », passez au Id10096.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10096: {
        label: "(Id10096) A-t-elle été électrocutée ?",
        hint: "Cela inclut les accidents et les cas où l’on ne sait pas s’il s’agit d’un accident ou s’il y a eu violence intentionnelle.",
        guidance:
          "Si le décès est dû à un choc électrique, inscrivez « OUI » ici. Cela inclut les accidents et les cas où l’on ne sait pas s’il s’agit d’un accident ou s’il y a eu violence intentionnelle. Si la réponse à Id10096 est « OUI », les questions Id10094 à Id10097 doivent être ignorées. Si la réponse est « NON/NSP/Réf », passez au Id10094.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10094: {
        label: "(Id10094) A-t-il été blessé par un objet contondant ?",
        hint: "Un traumatisme contondant est une blessure non pénétrante causée par un objet.",
        guidance:
          "Blessure causée par une force contondante telle qu'un bâton ou un objet lourd, qui peut ne pas causer de blessure externe directe mais peut être suffisamment grave pour provoquer des fractures, une hémorragie interne et la mort. Expliquez la signification d’une force contondante et enregistrez la réponse en conséquence.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10095: {
        label: "(Id10095) A-t-il été blessé par une force de la nature ?",
        hint: "Les forces de la nature peuvent inclure la foudre, les inondations, les tremblements de terre, les tsunamis, les feux de brousse, les éruptions volcaniques, etc.",
        guidance:
          "Les forces de la nature comprennent la foudre, les inondations, les tremblements de terre, les tsunamis, les feux de brousse, les éruptions volcaniques, etc. Si la réponse est « OUI », alors enregistrez la force de la nature dans la section narrative du questionnaire. Si la réponse est « OUI », passez à Id10100.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10097: {
        label: "(Id10097) A-t-il subi une autre blessure ?",
        guidance:
          "Si la blessure s'est produite dans des circonstances qui n'entrent pas dans les catégories ci-dessus (par exemple pendaison, explosion d'une mine terrestre, etc.), enregistrez la réponse en conséquence dans la section narrative.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10098: {
        label: "(Id10098) La blessure était-elle accidentelle ?",
        guidance:
          "Cette question permet de déterminer si la blessure était involontaire. Si « OUI », allez à Id10351.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10099: {
        label: "(Id10099) La blessure a-t-elle été auto-infligée ?",
        guidance:
          "C’est une question sensible, compte tenu de l’événement personnel traumatisant. Assurez-vous que cette question est posée avec empathie et laissez suffisamment de temps à la personne interrogée pour y répondre. Il s'agit d'une opinion subjective du répondant. Si possible, essayez de corroborer les preuves avec d’autres informations locales et notez des notes dans la partie narrative du questionnaire. Si « OUI », allez à Id10120_unit.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10100: {
        label: "(Id10100) La blessure a-t-elle été intentionnellement infligée par quelqu'un d'autre ?",
        guidance:
          "Demandez si la blessure a été causée par un acte de violence soit directement par une autre personne, soit par une circonstance créée intentionnellement par une autre personne (par exemple, un acte de terrorisme).",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10351: {
        label: "(Id10351) Quel âge avait le bébé lorsque la maladie mortelle a commencé ?",
        hint: "Le nombre maximum de jours pour les nouveau-nés est de 27 jours. La réponse pourrait être donnée dans une autre unité, mais pour les jours d'utilisation de la saisie des données. Moins de 24 heures = 0 jour ; 1 semaine = 7 jours. Entrez « 99 » pour « ne sait pas ». Entrez « 88 » pour « refuser ».",
        guidance:
          "Cette question est posée pour déterminer l'âge en jours au début de la maladie. Dans la plupart des cas de décès néonatal précoce, cela se produirait dès le jour de la naissance, le jour zéro. Vous ne devriez répondre que dans quelques jours. Le nombre maximum de jours pour les nouveau-nés est de 27 jours. Moins de 24 heures = 0 jour. Utilisez 1 semaine = 7 jours pour déterminer le nombre de jours. Pour je ne sais pas, entrez « 99 ». Pour refusé, inscrivez « 88 ». La réponse ne doit pas dépasser l’âge du nouveau-né au moment du décès.",
        constraintMessage: "Veuillez saisir une valeur inférieure à l'âge en jours au décès."
      },
      Id10408: {
        label:
          "(Id10408) Avant la maladie qui a entraîné le décès, le bébé/l'enfant grandissait-il normalement ?",
        guidance:
          "La question est de connaître une période de santé normale où il y a croissance/prise de poids avant l'apparition de la maladie terminale.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10120_0: {
        label: "(Id10120_0) Pendant combien de jours a-t-il été malade avant de mourir ?",
        hint: "Si le répondant est incapable de répondre, posez la question : A-t-il été malade pendant moins d'une semaine - l'intervieweur doit saisir 6 jours ; 1 à 2 semaines - l'enquêteur doit saisir 13 jours ; 2 à 3 semaines - l'intervieweur doit saisir 20 jours ;  3 à 4 semaines – l'intervieweur doit saisir 27 jours.",
        guidance:
          "Demandez combien de jours il a été malade pendant la maladie qui a conduit au décès. Si moins de 24 heures, entrez « 0 ». Une entrée valide est inférieure à l’âge du nouveau-né au décès. Si le répondant ne peut pas se rappeler exactement combien de jours la personne décédée était malade avant son décès, demandez-lui et enregistrez-le en fonction de ce qui est médicalement pertinent à saisir. Si le défunt était malade :\n● moins d'une semaine - l'enquêteur doit saisir 6 jours ;\n● 1 à 2 semaines - l'enquêteur doit saisir 13 jours ;\n● 2 à 3 semaines - l'enquêteur doit saisir 20 jours ;\n● 3 à 4 semaines – l'enquêteur doit saisir 27 jours.\nPour je ne sais pas, entrez « 99 ». Pour refus de réponse, entrez « 88 ».",
        constraintMessage: "Veuillez saisir une valeur inférieure à l'âge néonatal en jours au décès."
      },
      id10120_unit: {
        label: "(id10120_unit) Pendant combien de temps a-t-il été malade avant de mourir ?",
        hint: "Si le répondant est incapable de répondre, posez la question : A-t-il été malade pendant moins de 3 semaines (l'enquêteur a indiqué 14 jours) ; ou plus de trois semaines (l'enquêteur doit saisir 1 mois) avant le décès ?",
        guidance:
          "Sélectionnez la meilleure unité en fonction de la réponse – jours, mois ou années. Si moins de 24 heures, sélectionnez les jours et entrez « 0 ». Si la réponse a dépassé 30 jours, demandez au répondant de déclarer en mois ou en années. Si la réponse était supérieure à 11 mois, demandez au répondant de déclarer en années. Une réponse valide est inférieure à l’âge de l’enfant au décès. Si le répondant ne se souvient pas exactement de la durée de la maladie, demandez-lui et notez-le en fonction de ce qui est médicalement pertinent à saisir :\n● si le défunt était malade depuis moins de 3 semaines - l'enquêteur doit saisir 14 jours ;\n● si le défunt était malade depuis plus de 3 semaines - l'enquêteur doit saisir 1 mois.",
        choices: {
          days: "Jour",
          months: "mois",
          years: "année",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10121: {
        label: "(Id10121) Mois",
        constraintMessage:
          "Si la réponse a été supérieure à 11 mois, demandez au répondant de déclarer le délai en années. Veuillez également vérifier que la valeur saisie est inférieure à l'âge du défunt."
      },
      Id10122: {
        label: "(Id10122) Années",
        constraintMessage: "La durée saisie dépasse l'âge au décès."
      },
      Id10120_1: {
        label: "(Id10120_1) Jours",
        hint: "Moins de 24 heures = 0 jour.",
        constraintMessage:
          "Si la réponse a été supérieure à 30 jours, demandez au répondant de déclarer le temps passé dans une autre unité."
      },
      Id10120: {
        label: "(Id10120) Nombre calculé de jours de maladie"
      },
      Id10123: {
        label: "(Id10123) Est-il mort subitement ?",
        hint: "Soudainement fait référence à la mort dans les 24 heures après avoir été en bonne santé.",
        guidance:
          "Demandez si la personne décédée est décédée subitement dans les 24 heures après avoir été en bonne santé. Dans certains cas, une personne peut souffrir d’une maladie aiguë, puis sembler se rétablir pendant un certain temps avant de mourir subitement. Ces cas peuvent toujours être considérés comme des réponses oui à cette question. C’est à ce moment-là qu’on pense qu’une personne se remet d’une maladie et qu’elle meurt subitement.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10147: {
        label: "(Id10147) Avait-il de la fièvre ?",
        hint: "La fièvre est un terme utilisé lorsque le corps est anormalement chaud ou chaud au toucher et/ou lorsqu'un thermomètre enregistre une température anormalement élevée.",
        guidance:
          "La fièvre est un terme utilisé lorsque le corps est anormalement chaud ou chaud au toucher et/ou lorsqu'un thermomètre enregistre une température anormalement élevée. La fièvre est un symptôme courant des infections et est souvent associée à d’autres symptômes. La fièvre est un signe subtil chez les nouveau-nés et peut ne pas être remarquée par la mère ou les proches. La plupart des communautés/langues ont un terme local pour désigner la fièvre, qui doit être inclus dans la version traduite du questionnaire dans la langue locale. Si la réponse est « NON/NSP/Réf », passez à Id10153.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10148_a: {
        label: "(Id10148_a) Combien de jours la fièvre a-t-elle duré ?",
        hint: "Si moins de 1 jour ou 24 heures, entrez 0 jour. Utilisez 1 semaine = 7 jours pour déterminer le nombre de jours. Pour je ne sais pas, entrez « 99 ». Pour refusé, entrez « 88 ».",
        guidance:
          "Dans la plupart des infections aiguës, la fièvre est présente pendant au moins 1 à 2 jours au cours de la période menant au décès. Dans certaines infections chroniques, la fièvre peut être présente pendant une durée plus longue. L’obtention de la durée approximative est utile pour poser le diagnostic de l’infection spécifique. Si moins de 1 jour ou 24 heures, entrez « 0 ». Utilisez 1 semaine = 7 jours pour déterminer le nombre de jours. Pour je ne sais pas, entrez « 99 ». Pour refusé, inscrivez « 88 ».",
        constraintMessage: "Veuillez saisir une valeur inférieure à l'âge néonatal en jours au décès."
      },
      Id10148_units: {
        label: "(Id10148_units) Combien de temps la fièvre a-t-elle duré ?",
        hint: "Si le répondant est incapable de répondre, posez la question : La fièvre a-t-elle duré moins d'une semaine (l'intervieweur doit saisir 6 jours) ; moins de deux semaines (l'enquêteur doit saisir 13 jours) ; ou plus de 2 semaines (l'intervieweur doit saisir 15 jours) ? Entrez 1 unité seulement : 0-30 jours ou 1-60 mois. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        choices: {
          days: "Jour",
          months: "mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10148_b: {
        label: "(Id10148_b) [Entrez la durée de la fièvre en jours] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a été supérieure à 30 jours, demandez au répondant de déclarer le délai en mois."
      },
      Id10148_c: {
        label: "(Id10148_c) [Entrez la durée de la fièvre en mois] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse était supérieure à 60 mois, confirmez la réponse et inscrivez 60."
      },
      Id10148: {
        label: "(Id10148) Combien de jours la fièvre a-t-elle duré ?"
      },
      Id10149: {
        label: "(Id10149) La fièvre a-t-elle persisté jusqu'au décès ?",
        guidance:
          "Dans le cas de fièvres de plus longue durée, il est important de savoir si la fièvre faisait également partie de la période terminale de la maladie précédant le décès.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10150: {
        label: "(Id10150) Quelle était l'intensité de la fièvre ?",
        guidance:
          "La gravité fait référence au degré de fièvre, qui peut être assez élevé dans certaines conditions, lorsque le corps est très chaud. Dans de nombreux cas, il peut être difficile pour le répondant de définir la gravité de la fièvre, et donc d'enregistrer le degré de gravité perçu et signalé par le répondant. Sélectionnez la réponse appropriée.",
        choices: {
          mild: "Légère",
          severe: "grave",
          DK: "Ne sait pas",
          Ref: "Refus de repondre"
        }
      },
      Id10151: {
        label: "(Id10151) Quel était le type de fièvre ?",
        guidance:
          "Certaines infections produisent des schémas caractéristiques de fièvre – continue ou intermittente ; ou fièvre seulement la nuit. Si la question n'est pas directement comprise, mentionnez ces différents schémas et demandez si la fièvre a suivi l'un de ces schémas, puis enregistrez la réponse en conséquence.",
        choices: {
          continuous: "Continue",
          on_and_off: "Des hauts et des bas",
          nightly: "Seul la nuit",
          DK: "Ne sait pas",
          Ref: "Refus de repondre"
        }
      },
      Id10153: {
        label: "(Id10153) Est-ce qu'il a toussé ?",
        guidance:
          "La toux est un symptôme courant et un signe très important d’infections et d’autres affections du système respiratoire. Des affections respiratoires telles que la pneumonie sont parfois présentes au cours des stades terminaux d'autres maladies, en particulier chez les personnes âgées, d'où une réponse positive à cette question. Posez cette question avec soin et vérifiez une réponse négative, car cela entraînerait l'omission de toutes les autres questions sur la toux. En cas de réponse positive à la toux, il convient de suivre attentivement les questions suivantes caractérisant la toux. Pour les nénonates : cette question est posée car la toux peut être le signe d'une infection pulmonaire ou d'un autre problème de santé lié à la gorge ou à la poitrine. Bien que la toux ne soit pas un signe évident de maladie chez le nouveau-né, la mère peut s'en souvenir et constitue un signe diagnostique utile.  Si « NON/NSP/Réf », passez à Id10159.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10154_units: {
        label: "(Id10154_units) Depuis combien de temps a-t-il toussé ?",
        hint: "Si le répondant est incapable de répondre, posez la question : La toux a-t-elle duré moins de 3 semaines (l'intervieweur doit saisir 20 jours) ; ou au moins 3 semaines (l'enquêteur doit saisir 22 jours) ? Entrez 1 unité seulement : 0-30 jours ou 1-60 mois. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        guidance:
          "La durée de la toux aide à déterminer si la maladie respiratoire était la principale maladie ayant entraîné la mort, lorsque la toux est présente avec des symptômes relatifs à d'autres systèmes corporels. Dans certains cas, des épisodes de toux fréquents et récurrents peuvent survenir sur plusieurs années. Si nécessaire, l'enquêteur doit clarifier ce point avec le répondant. Sondez soigneusement et si nécessaire revérifiez pour garantir une réponse précise à la durée de la toux pendant la période menant au décès. Sélectionnez la meilleure unité en fonction de la réponse – jours ou mois. Une réponse valide se situe entre 0 et 30 jours ou entre 1 et 60 mois. Pour moins d'un jour ou 24 heures, saisissez « 0 » jour. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 60 mois. Si la réponse donnée est supérieure à 60 mois, confirmez la réponse et entrez « 60 ». Si le répondant ne se souvient pas exactement de la durée de la toux, demandez-le et enregistrez-le en fonction de ce qui est médicalement pertinent à saisir. Si la toux dure :\n● moins de 3 semaines - l'enquêteur doit saisir 20 jours ;\n● au moins 3 semaines – l'enquêteur doit saisir 22 jours.",
        choices: {
          days: "Jour",
          months: "mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10154_a: {
        label: "(Id10154_a) [Entrez combien de temps il a toussé en jours] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a été supérieure à 30 jours, demandez au répondant de déclarer le délai en mois."
      },
      Id10154_b: {
        label: "(Id10154_b) [Entrez combien de temps il a toussé en mois] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse était supérieure à 60 mois, confirmez la réponse et inscrivez 60."
      },
      Id10154: {
        label: "(Id10154) Pendant combien de jours a-t-il toussé ?"
      },
      Id10155: {
        label: "(Id10155) La toux était-elle productive, avec des crachats ?",
        guidance:
          "Souvent, une personne peut simplement avoir une toux sèche. Lorsqu'une personne souffre de maladies comme la pneumonie ou la tuberculose, une crise de toux peut se terminer par le crachat de certaines sécrétions produites par les tubes respiratoires dans la poitrine, appelées mucosités (expectorations). Les sécrétions peuvent être un liquide clair ou blanchâtre, ou colorées (pus), ou même du sang (voir Id10157). Il existe souvent un terme local pour désigner les mucosités, qu'il convient d'utiliser pour sonder.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10156: {
        label: "(Id10156) La toux était-elle très sévère ?",
        guidance:
          "La gravité de la toux fait référence à son importance parmi les symptômes présents chez le défunt. Il est souvent difficile de définir la gravité. Cependant, on pourrait évaluer la gravité de la toux en se demandant s'il y avait des accès de toux prolongés, ou si la toux était aggravée par la position allongée ou l'effort physique, et/ou si elle affectait le sommeil.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10157: {
        label: "(Id10157) Est-ce qu'il a craché du sang ?",
        guidance:
          "Un enfant atteint de pneumonie peut produire des traînées de sang dans les crachats. Cela peut également se produire dans le cas de la tuberculose et du cancer du poumon, mais ces affections sont relativement rares chez les enfants. La présence de sang dans les crachats est un signe facilement reconnaissable et quelque chose dont les personnes interrogées se souviendront probablement, comme le leur a dit le défunt ou dont il a été témoin. Ce signe déclenche souvent également une tentative de recours à des soins de santé et est donc généralement mémorisé par les proches.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10158: {
        label: "(Id10158) Est-ce qu'il a émis une coqueluche en toussant ?",
        guidance:
          "Dans certains cas, l’enfant peut émettre une coqueluche forte en inspirant avant une quinte de toux. Il s'agit d'un son caractéristique dont le répondant peut se souvenir, en particulier lorsque la toux est qualifiée de sévère.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10159: {
        label: "(Id10159) Avait-il des difficultés à respirer ou un essoufflement ?",
        hint: "Les difficultés respiratoires sont un élément important qui facilite l’identification de la cause du décès et peuvent se manifester par des difficultés à respirer ou une sensation d’essoufflement.",
        guidance:
          "Les difficultés respiratoires sont une caractéristique importante qui facilite l'identification de la cause du décès et peuvent être observées sous la forme d'une respiration anormalement bruyante, comme si elle était créée par une sorte d'obstruction des voies respiratoires (trachée). L'essoufflement est défini comme la prise de respirations profondes, ou la sensation ou l'observation d'un effort excessif ou supplémentaire pour respirer. Une courte période d'essoufflement peut survenir en association avec une pneumonie dans le cadre de la maladie terminale chez les nouveau-nés. Si le défunt avait des difficultés respiratoires et/ou un essoufflement, inscrivez « Oui ». Si la réponse est « NON/NSP/Réf », passez à Id10166.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10161_0: {
        label:
          "(Id10161_0) Pendant combien de jours la difficulté respiratoire ou l’essoufflement a-t-il duré ?",
        hint: "Si moins de 1 jour ou 24 heures, entrez 0 jour. Utilisez 1 semaine = 7 jours pour déterminer le nombre de jours. Pour je ne sais pas, entrez « 99 ». Pour refusé, entrez « 88 ».",
        guidance:
          "La durée de la difficulté respiratoire ou de l’essoufflement peut aider à comprendre la gravité de la maladie et sa relation avec la cause du décès. Enregistrez le nombre de jours pendant lesquels l’enfant a eu des difficultés à respirer ou était essoufflé. Si cela a été observé seulement moins de 1 jour = 0 jour. La réponse à la durée des difficultés respiratoires peut aller de 0 à 30 jours. Utilisez 1 semaine = 7 jours pour déterminer le nombre de jours. Pour je ne sais pas, entrez « 99 ». Pour refusé, inscrivez « 88 ».",
        constraintMessage: "Veuillez saisir une valeur inférieure à l'âge néonatal en jours au décès."
      },
      id10161_unit: {
        label: "(Id10161_unit) Combien de temps a duré la difficulté à respirer ou l'essoufflement ?",
        hint: "Si le répondant est incapable de répondre, demandez : La difficulté respiratoire ou l'essoufflement a-t-il duré moins de 3 jours (l'enquêteur doit inscrire 2 jours) ou pendant au moins 3 jours (l'enquêteur doit inscrire 4 jours) ?",
        guidance:
          "La durée de la difficulté respiratoire ou de l’essoufflement peut aider à comprendre la gravité de la maladie et sa relation avec la cause du décès. Chez les jeunes enfants asthmatiques, les difficultés respiratoires se manifestent sous forme d’épisodes spécifiques durant quelques jours au maximum. En cas de difficultés respiratoires accompagnées de pneumonie, elles peuvent être présentes pendant quelques jours jusqu'à 1 à 2 semaines, au cours de la maladie. Chez les très jeunes enfants (nouveau-nés et nourrissons). la difficulté peut n'être présente que pendant plusieurs heures ou jusqu'à 2 à 3 jours. Par conséquent, en fonction de l’âge et de l’état probable, la réponse sur la durée des difficultés respiratoires peut varier. Habituellement, les antécédents d’essoufflement associés aux cardiopathies congénitales durent plusieurs semaines. Cependant, les épisodes d’essoufflement liés à l’asthme ne durent généralement que quelques jours, lors du dernier épisode précédant le décès. En cas d'essoufflement chez les enfants atteints de pneumonie, cela peut également durer quelques jours seulement. Sélectionnez la meilleure unité en fonction de la réponse – jours, mois ou années. Si moins de 24 heures, sélectionnez les jours et entrez « 0 ». Si la réponse a dépassé 30 jours, demandez au répondant de déclarer en mois ou en années. Si la réponse était supérieure à 11 mois, demandez au répondant de déclarer en années. Une réponse valide est inférieure à l’âge au décès. Si le répondant ne se souvient pas exactement de la durée de la difficulté respiratoire ou de l’essoufflement, demandez-le et enregistrez-le en fonction de ce qui est médicalement pertinent à saisir. Si la difficulté à respirer ou l’essoufflement persiste : \n● moins de 3 jours - l'enquêteur doit saisir 2 jours ; \n● au moins 3 jours – l'enquêteur doit saisir 4 jours.",
        choices: {
          days: "Jour",
          months: "mois",
          years: "année",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10161_1: {
        label: "(Id10161_1) [Entrez la durée en jours de la respiration difficile ou de l'essoufflement] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a été supérieure à 30 jours, demandez au répondant de déclarer le temps passé dans une autre unité."
      },
      Id10162: {
        label: "(Id10162) [Entrez la durée en mois de la difficulté à respirer ou de l'essoufflement] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "Si la réponse a été supérieure à 11 mois, demandez au répondant de déclarer le délai en années."
      },
      Id10163: {
        label: "(Id10163) [Entrez la durée en années de la difficulté à respirer ou de l'essoufflement] :",
        hint: "Entrez le nombre d'années de moins que l'âge au décès.",
        constraintMessage: "La durée saisie dépasse l'âge au décès."
      },
      Id10161: {
        label: "(Id10161) Nombre calculé de jours de maladie"
      },
      Id10165: {
        label: "(Id10165) La difficulté à respirer était-elle continue ou intermittente ?",
        guidance:
          "Comme décrit ci-dessus, les difficultés respiratoires provoquant une respiration sifflante dans l'asthme apparaissent et disparaissent au fil des mois et des années et constituent une caractéristique importante. La respiration difficile et bruyante associée à la pneumonie infantile peut être continue pendant la maladie. Dans la pneumonie néonatale et infantile, une respiration bruyante ne se produit qu'en continu à chaque respiration, pendant la maladie en phase terminale, pendant seulement quelques heures jusqu'à 2 à 3 jours avant le décès. Précisez si la difficulté à respirer au cours de la dernière maladie était continue ou intermittente.",
        choices: {
          continuous: "Continue",
          on_and_off: "Des hauts et des bas",
          DK: "Ne sait pas",
          Ref: "Refus de repondre"
        }
      },
      Id10170: {
        label:
          "(Id10170) Était-il incapable d'effectuer ses tâches quotidiennes à cause d'un essoufflement ?",
        hint: "Une personne souffrant d’essoufflement sévère aura du mal à accomplir ses tâches quotidiennes, comme marcher sur de courtes distances ou prendre un bain, et aura besoin de l’aide de quelqu’un.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10171: {
        label: "(Id10171) Était-il essoufflé en position couchée ?",
        guidance:
          "Aux stades avancés de l’insuffisance cardiaque, ou BPCO, l’essoufflement survient même en position couchée et interfère souvent avec le sommeil. Dans de nombreux cas, la personne dort dans une position calée avec plusieurs oreillers pour soutenir le dos et le cou. Demandez si le défunt était essoufflé alors qu'il était allongé à plat pendant la dernière maladie et notez la réponse.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10166: {
        label: "(Id10166) Avait-il une respiration rapide ?",
        guidance:
          "Une respiration rapide accompagne généralement la fièvre et constitue l'un des signes de pneumonie chez les nouveau-nés et les enfants. Il s’agit d’un signe subtil qui peut ne pas être remarqué indépendamment d’un essoufflement ou d’une respiration bruyante. Il s’agit généralement d’une observation subjective du répondant, alors enregistrez la réponse telle qu’elle a été dite, sans approfondir davantage. Nouveau-nés et enfants si la réponse est « NON/NSP/Réf », passez à Id10172. Pour ADULTES UNIQUEMENT - si « NON/NSP/Réf » passe à Id10173_a",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10167_a: {
        label: "(Id10167_a) Pendant combien de jours la respiration rapide a-t-elle duré ?",
        hint: "Si moins de 1 jour ou 24 heures, entrez 0 jour. Utilisez 1 semaine = 7 jours pour déterminer le nombre de jours. Pour je ne sais pas, entrez « 99 ». Pour refusé, entrez « 88 ».",
        guidance:
          "La durée d'une respiration rapide indique la gravité de la maladie mais constitue un signe difficile à reconnaître et à mémoriser. Si moins de 1 jour ou 24 heures, entrez « 0 ». Une durée de validité ne peut être supérieure à l'âge en jours du défunt. Utilisez 1 semaine = 7 jours pour déterminer le nombre de jours. Pour je ne sais pas, entrez « 99 ». Pour refusé, inscrivez « 88 ».",
        constraintMessage: "Veuillez saisir une valeur inférieure à l'âge néonatal en jours au décès."
      },
      Id10167_units: {
        label: "(Id10167_units) Combien de temps a duré la respiration rapide ?",
        hint: "Si le répondant est incapable de répondre, posez la question : La difficulté respiratoire a-t-elle duré moins de 2 semaines (l'enquêteur doit inscrire 13 jours) ou pendant au moins 2 semaines (l'enquêteur doit inscrire 15 jours) ?",
        guidance:
          "Habituellement, la durée de la respiration rapide en cas de pneumonie sera similaire à la durée de la maladie finale. Si le répondant déclare une durée de respiration rapide plus longue au questionnaire VA 2022 de l'OMS pour le décès d'un enfant âgé de moins de 4 semaines à 11 ans que la maladie finale, précisez que vous posez des questions sur la respiration rapide pendant la maladie finale. Sélectionnez la meilleure unité en fonction de la réponse – jours ou mois. Une réponse valide se situe entre 0 et 30 jours ou entre 1 et 60 mois. Pour moins d'un jour ou 24 heures, saisissez « 0 » jour. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 60 mois. Si la réponse donnée était supérieure à 60 mois, confirmez la réponse et inscrivez « 60 ». Si la personne interrogée ne se souvient pas exactement de la durée de la respiration rapide, demandez-la et notez-la en fonction de ce qui est médicalement pertinent à saisir. Si la respiration rapide a duré :\n● moins de 2 semaines - l'enquêteur doit saisir 13 jours ;\n● au moins semaines – l'enquêteur doit saisir 15 jours.",
        choices: {
          days: "Jour",
          months: "mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10167_b: {
        label: "(Id10167_b) [Entrez la durée de la respiration rapide en jours] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a été supérieure à 30 jours, demandez au répondant de déclarer le délai en mois."
      },
      Id10167_c: {
        label: "(Id10167_c) [Entrez la durée de la respiration rapide en mois] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse était supérieure à 60 mois, confirmez la réponse et inscrivez 60."
      },
      Id10167: {
        label: "(Id10167) Combien de temps a duré la respiration rapide ?"
      },
      Id10172: {
        label:
          "(Id10172) Avez-vous vu la partie inférieure de la paroi thoracique/les côtes être tirées vers l'intérieur lorsque l'enfant inspirait (tirage thoracique) ?",
        hint: "Demandez uniquement pour les enfants de moins de 12 ans. Montrer des photos si disponibles.",
        guidance:
          "Habituellement, les parois thoraciques s'élèvent et se dilatent pendant l'inspiration. En cas d'obstruction des voies respiratoires ou de maladie pulmonaire grave, il y a un renversement, la paroi thoracique inférieure (en particulier les espaces entre les côtes) étant tirée vers l'intérieur lors de l'inspiration. Cela peut être remarqué par une personne qui s'occupe de près du nouveau-né/de l'enfant malade. Certaines communautés ont un terme local pour ce signe. Si tel est le cas, incluez ce terme dans la version traduite localement du questionnaire.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10173_nc: {
        label: "(Id10173_nc) Sa respiration ressemblait-elle à l'un des éléments suivants :",
        guidance:
          "Les enquêteurs VA doivent être conscients et être capables de décrire et/ou de démontrer ces exemples de difficultés respiratoires qui produisent des sons anormaux, et d'enregistrer la réponse en conséquence. Ceux-ci incluent un sifflement (communément appelé respiration sifflante). D'autres sons anormaux produits lors d'une respiration difficile chez les nouveau-nés atteints d'une maladie respiratoire sont le stridor (bruyant lors de l'inspiration) et les grognements (bruyants lors de l'expiration). Utilisez des fichiers audio si disponibles. Démontrez les trois différents types de respiration et demandez-lui s'il en a eu. Cochez la case correspondante.",
        constraintMessage:
          "Il n'est pas possible de sélectionner « Ne sait pas », « Refuser » ou « Non » avec d'autres options. Veuillez revenir en arrière et corriger la sélection.",
        choices: {
          stridor: "Stridor",
          grunting: "Grognement",
          wheezing: "une respiration sifflante",
          no: "Aucune des réponses ci-dessus",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10173_a: {
        label: "(Id10173_a) Avait-il une respiration sifflante ?",
        guidance:
          "La respiration sifflante est un sifflement qui provient de la poitrine lors de l'expiration. L'intervieweur VA doit être formé pour démontrer une respiration sifflante au répondant. Lire le fichier audio si disponible.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10173: {
        label:
          "(Id10173) Durant la maladie qui a conduit au décès, sa respiration ressemblait-elle à l'un des sons suivants :"
      },
      Id10174: {
        label: "(Id10174) Avait-il des douleurs à la poitrine ?",
        guidance:
          "La douleur thoracique a de nombreuses causes possibles qui se répartissent en deux grandes catégories : les causes cardiaques et non cardiaques. Cette question vise à identifier si des douleurs thoraciques sont survenues au cours de la maladie précédant le décès, et à identifier les douleurs thoraciques cardiaques liées à une crise cardiaque. La douleur thoracique cardiaque apparaît soudainement, est souvent très sévère, dure environ 30 minutes à une heure et ne disparaît généralement qu'avec des soins médicaux. En revanche, les douleurs thoraciques non cardiaques sont moins sévères et sont généralement aggravées par la respiration ou la toux ; et dure plusieurs jours. Si nécessaire, clarifiez ce que l’on entend par douleur thoracique selon les types ci-dessus et enregistrez la réponse en conséquence. Si « NON/NSP/Réf », passez à Id10181.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10175: {
        label: "(Id10175) La douleur thoracique était-elle intense ?",
        guidance:
          "La gravité de la douleur thoracique peut être jugée à partir des descriptions d’une lourdeur ou d’une oppression extrême au centre de la poitrine, écrasant complètement toutes les fonctions et activités de l’individu, accompagnées de transpiration et éventuellement d’un collapsus. Des douleurs thoraciques moins sévères sont associées à des mouvements respiratoires ou à une sensibilité locale de la paroi thoracique et sont souvent des douleurs thoraciques non cardiaques. Ceci est généralement toléré et porté à l'attention des soignants au fil du temps ; contrairement à la douleur cardiaque thoracique qui a des effets graves et dramatiques.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10176: {
        label: "(Id10176) Combien de jours avant le décès a-t-il ressenti des douleurs thoraciques ?",
        hint: "Si le répondant est incapable de répondre, posez la question : Est-ce qu'elle a eu du maquillage sur la poitrine pendant moins de 3 jours avant le décès (l'enquêteur doit saisir 2 jours) ou pendant au moins plus de 3 jours avant le décès (l'enquêteur doit saisir 4 jours) ? Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours. Pour je ne sais pas, entrez « 99 ». Pour refusé, entrez « 88 ».",
        guidance:
          "La douleur thoracique associée à une maladie cardiaque est généralement d’apparition soudaine et de courte durée. Cela survient souvent dans les 24 heures précédant le décès. Cependant, il peut y avoir eu des épisodes antérieurs de douleurs thoraciques aiguës et soudaines, ou de douleurs thoraciques chroniques sous traitement médicamenteux, qui peuvent apparaître lors de l'exercice. S'il y a eu plusieurs épisodes, enregistrez la durée depuis le dernier épisode de douleur thoracique sévère avant le décès. En revanche, la douleur associée à une maladie thoracique telle qu'une pneumonie peut être présente depuis plusieurs jours, elle est associée à la respiration et n'est pas très grave. Enregistrez la réponse en nombre de jours ; si moins de 1 jour ou 24 heures, entrez 0 jour. Utilisez 1 semaine = 7 jours pour déterminer le nombre de jours. Si le répondant ne se souvient pas exactement de la durée de la douleur thoracique, invitez-le et notez-le en fonction de ce qui est médicalement pertinent à saisir. Si la douleur thoracique persiste : \n● moins de 3 jours avant le décès - l'enquêteur doit saisir 2 jours ; \n● au moins plus de 3 jours avant le décès – l'enquêteur doit saisir 4 jours. \nPour je ne sais pas, entrez \"99\". Pour refusé, entrez « 88 ». Une réponse valide est entre 0 et 99. Si la réponse est de 88 jours, inscrivez plutôt « 87 » afin que la réponse ne soit pas automatiquement codée comme refus de réponse.",
        constraintMessage:
          "Veuillez saisir une valeur comprise entre 0 et 99. Si la réponse a été supérieure à 98 jours, confirmez la réponse et saisissez 98."
      },
      Id10178_unit: {
        label: "(Id10178_unit) Combien de temps la douleur thoracique a-t-elle duré ?",
        hint: "Arrondissez la réponse donnée par le répondant si nécessaire (par exemple, si la douleur thoracique a duré 2 heures 30 minutes ; inscrivez 3 heures). Si le répondant est incapable de répondre, demandez : La douleur thoracique a-t-elle duré moins d'une heure (l'intervieweur doit saisir 0 heure), 1 à 4 heures (l'intervieweur doit saisir 4 heures), 5 à 23 heures (l'intervieweur doit saisir 23 heures).",
        guidance:
          "Parfois, la douleur thoracique entraîne une perte de conscience et la mort, peu de temps après l’apparition de la douleur thoracique. Une douleur thoracique aiguë d’origine cardiaque peut durer environ 2 à 3 heures. La durée de la douleur thoracique est donc importante pour établir le diagnostic. Sélectionnez la meilleure unité en fonction de la réponse - heures ou jours. Une réponse valide se situe entre 1 et 23 heures, ou jours de moins que la réponse pour Id10176 : combien de jours avant le décès a-t-il ressenti des douleurs thoraciques. Utiliser 1 semaine = 7 jours. Notez que cette question n'est pas utilisée par le logiciel d'analyse automatisée, mais elle est importante pour l'examen par le médecin. Si le répondant ne se souvient pas exactement de la durée de la douleur thoracique, invitez-le et notez-le en fonction de ce qui est médicalement pertinent à saisir. Si la douleur thoracique a duré :\n● 0-1 heure – entrez 0 heure ;\n● 1-4 heures – entrez 4 heures ;\n● 5-23 heures – saisissez 23 heures.",
        choices: {
          hours: "Heures",
          days: "Jour",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10179: {
        label: "(Id10179) [Entrez la durée de la douleur thoracique en heures] :",
        hint: "Entrez 0-23 heures.",
        constraintMessage:
          "Si la réponse a été supérieure à 23 heures, demandez au répondant de déclarer le temps en jours."
      },
      Id10179_1: {
        label: "(Id10179_1) [Entrez la durée en jours de la douleur thoracique] :",
        hint: "Entrez 0 à 30 jours. 1 semaine = 7 jours.",
        constraintMessage: "La réponse doit être inférieure à la réponse pour ID10176."
      },
      Id10181: {
        label: "(Id10181) Avait-il la diarrhée ?",
        hint: "Demandez au répondant quelle est sa compréhension de ce qu'est la diarrhée (avoir des selles molles ou liquides plus fréquentes que d'habitude) ; si ce n’est pas clair, expliquez au répondant ce qu’est la diarrhée. La diarrhée signifie avoir des selles molles ou liquides plus fréquentes que d’habitude.",
        guidance:
          "Demandez à la personne interrogée quelle est sa compréhension de ce qu'est la diarrhée (avoir des selles molles ou liquides plus fréquentes que d'habitude) ; Si la réponse n'est pas claire ou est erronée, expliquez au répondant que la diarrhée est le passage fréquent de selles molles ou liquides, avec ou sans sang. Il peut y avoir des termes locaux pour le décrire, si c'est le cas, incluez-les dans la version locale traduite du questionnaire. Si « NON/NSP/Réf », passez à Id10186.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10182_units: {
        label: "(Id10182_units) Depuis combien de temps a-t-il eu la diarrhée ?",
        hint: "Si le répondant est incapable de répondre, posez la question : La diarrhée a-t-elle duré moins de 2 semaines (l'enquêteur doit saisir 13 jours) ? entre deux et quatre semaines (l'enquêteur doit saisir 15 jours) ; ou pendant plus de 4 semaines (l'enquêteur doit saisir 29 jours) ?",
        guidance:
          "Cette question est posée si la personne décédée a déclaré avoir la diarrhée. Cela peut se produire sur des périodes de temps variables ; par ex. dans des conditions telles que le VIH/SIDA, la malnutrition chronique ; ou de la maladie coeliaque, la personne affectée peut souffrir de diarrhée pendant des périodes prolongées s'étendant sur des semaines ou des mois. En revanche, il peut s’agir d’un épisode de diarrhée précédant immédiatement le décès. Sélectionnez la meilleure unité en fonction de la réponse – jours ou mois. Une réponse valide se situe entre 0 et 30 jours ou entre 1 et 60 mois. Pour moins d'un jour ou 24 heures, saisissez « 0 » jour. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 60 mois. Si la réponse donnée était supérieure à 60 mois, confirmez la réponse et inscrivez « 60 ». Si la personne interrogée ne se souvient pas exactement de la durée de la diarrhée, demandez-la et notez-la en fonction de ce qui est médicalement pertinent à saisir. Si la diarrhée dure : \n● moins de 2 semaines - l'enquêteur doit saisir 13 jours ;\n● 2 à 4 semaines – l'enquêteur doit saisir 15 jours ;\n● plus de 4 semaines – l'enquêteur doit saisir 29 jours.",
        choices: {
          days: "Jour",
          months: "mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10182_a: {
        label: "(Id10182_a) [Entrez combien de temps il a la diarrhée en jours] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a été supérieure à 30 jours, demandez au répondant de déclarer le délai en mois."
      },
      Id10182_b: {
        label: "(Id10182_b) [Entrez la durée pendant laquelle il a la diarrhée en mois] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse était supérieure à 60 mois, confirmez la réponse et inscrivez 60."
      },
      Id10182: {
        label: "(Id10182) Pendant combien de jours a-t-il eu la diarrhée ?"
      },
      Id10183: {
        label:
          "(Id10183) Combien de selles le bébé ou l'enfant a-t-il fait le jour où la diarrhée était la plus fréquente ?",
        hint: "Pour je ne sais pas, entrez « 99 ». Pour refusé, entrez « 88 ».",
        guidance:
          "Cette question enregistre la fréquence des diarrhées. Demandez au répondant le nombre maximum de fois où la personne décédée a eu la diarrhée au cours d'un jour quelconque de la période précédant immédiatement le décès et inscrivez ce nombre dans l'espace prévu. Une réponse valide est comprise entre 0 et 20. Si la réponse était supérieure à 20 selles, confirmez la réponse et inscrivez « 20 ». Pour je ne sais pas, entrez « 99 ». Pour refusé, inscrivez « 88 ».",
        constraintMessage:
          "Veuillez saisir une valeur comprise entre 1 et 20, 88, 99. Si la réponse est supérieure à 20, confirmez la réponse et saisissez 20."
      },
      Id10184_a: {
        label: "(Id10184_a) Combien de jours avant le décès la diarrhée a-t-elle commencé ?",
        hint: "Si le répondant est incapable de répondre, posez la question : La diarrhée a-t-elle commencé moins de 3 jours avant le décès (l'enquêteur doit saisir 2 jours), ou a-t-elle commencé au moins 3 jours avant le décès (l'enquêteur doit saisir 4 jours) ? Si moins de 1 jour ou 24 heures, entrez 0 jour. Utilisez 1 semaine = 7 jours pour déterminer le nombre de jours. Pour je ne sais pas, entrez « 99 ». Pour refusé, entrez « 88 ».",
        guidance:
          "Cette question est posée pour relier spécifiquement l'épisode de diarrhée au décès. En cas de diarrhée aiguë, notez le nombre de jours écoulés entre le début et le décès. En cas de diarrhée chronique, enregistrer la durée du dernier épisode. Si moins de 1 jour ou 24 heures, entrez « 0 » jour. Une durée de validité ne peut être supérieure à l'âge en jours du défunt. Utilisez 1 semaine = 7 jours pour déterminer le nombre de jours. Pour je ne sais pas, entrez « 99 ». Pour refusé, inscrivez « 88 ». Si la personne interrogée ne se souvient pas exactement du nombre de jours, demandez-la et notez-la en fonction de ce qui est médicalement pertinent à saisir. Si la diarrhée :\n● a commencé moins de 3 jours avant le décès - l'enquêteur doit saisir 2 jours ; \n● commencé au moins 3 jours avant le décès – l'enquêteur doit saisir 4 jours.",
        constraintMessage: "Veuillez saisir une valeur inférieure à l'âge néonatal en jours au décès."
      },
      Id10184_units: {
        label: "(Id10184_units) Combien de temps avant le décès la diarrhée a-t-elle commencé ?",
        hint: "Si le répondant est incapable de répondre, posez la question : La diarrhée a-t-elle commencé moins de 3 jours avant le décès (l'enquêteur doit saisir 2 jours), ou a-t-elle commencé au moins 3 jours avant le décès (l'enquêteur doit saisir 4 jours) ? Entrez 1 unité seulement : 0-30 jours ou 1-60 mois. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        guidance:
          "Cette question est posée pour relier spécifiquement l'épisode de diarrhée au décès. En cas de diarrhée aiguë (quelques jours seulement), notez le nombre de jours écoulés entre le début et le décès. En cas de diarrhée chronique (épisodes récurrents sur plusieurs semaines), noter la durée du dernier épisode. Sélectionnez la meilleure unité en fonction de la réponse – jours ou mois. Une réponse valide se situe entre 0 et 30 jours ou entre 1 et 60 mois. Pour moins d'un jour ou 24 heures, saisissez « 0 » jour. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 60 mois. Si la réponse donnée était supérieure à 60 mois, confirmez la réponse et inscrivez « 60 ». Si la personne interrogée ne se souvient pas exactement du nombre de jours, demandez-la et notez-la en fonction de ce qui est médicalement pertinent à saisir. Si la diarrhée a commencé :\n● moins de 3 jours avant le décès - l'enquêteur doit saisir 2 jours ; \n● commencé au moins 3 jours avant le décès – l'enquêteur doit saisir 4 jours.",
        choices: {
          days: "Jour",
          months: "mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10184_b: {
        label: "(Id10184_b) [Entrez combien de temps avant le décès la diarrhée a commencé en jours] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a été supérieure à 30 jours, demandez au répondant de déclarer le délai en mois."
      },
      Id10184_c: {
        label: "(Id10184_c) [Entrez combien de temps avant le décès la diarrhée a commencé en mois] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse était supérieure à 60 mois, confirmez la réponse et inscrivez 60."
      },
      Id10185: {
        label: "(Id10185) La diarrhée a-t-elle continué jusqu'au décès ?",
        guidance:
          "Une réponse positive à cette question constitue une base solide pour considérer la diarrhée parmi les causes potentielles de décès. Cependant, dans certains cas, la personne décédée peut avoir perdu connaissance et ne pas avoir consommé de nourriture pendant un certain temps avant sa mort, de sorte que la diarrhée peut s'être arrêtée avant sa mort. Ensuite, la réponse à cette question devrait être prise en considération ainsi que les réponses à d'autres questions en ce qui concerne la formulation d'un diagnostic de diarrhée comme cause de décès.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10186: {
        label:
          "(Id10186) À un moment donné au cours de la dernière maladie, y a-t-il eu du sang dans les selles ?",
        guidance:
          "Cela peut être lié à la diarrhée, si elle est présente. Dans certaines infections, il peut y avoir du sang dans les selles, mais surtout chez les enfants et les adultes, mais rarement chez les nouveau-nés. Il est courant que cela soit observé par les soignants de nouveau-nés malades, le cas échéant.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10188: {
        label: "(Id10188) Est-ce qu'il a vomi ?",
        guidance:
          "Les vomissements sont un symptôme bien connu et commun aux maladies abdominales, mais peuvent survenir dans d'autres affections telles que la méningite, les infections des voies urinaires ou d'autres infections systémiques. Son association avec d'autres symptômes peut aider à identifier la cause du décès. Nouveau-nés : si « NON/NSP/Réf », passez à Id10275. Pour ADULTES et ENFANTS UNIQUEMENT - si « NON/NSP/Réf », passez à Id10194",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10190_units: {
        label: "(Id10190_units) Pendant combien de temps a-t-il vomi ?",
        hint: "Si le répondant est incapable de répondre, posez la question : A-t-elle vomi pendant moins de 3 jours (l'enquêteur doit saisir 2 jours) ou pendant plus de 3 jours (l'enquêteur doit saisir 4 jours) ? Entrez 1 unité seulement : 0-30 jours ou 1-60 mois. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        guidance:
          "Il est utile de connaître la période de temps pendant laquelle les épisodes de vomissements ont été présents, afin de comprendre la relation entre ce symptôme et une cause potentielle. Sélectionnez la meilleure unité en fonction de la réponse – jours ou mois. Une réponse valide se situe entre 0 et 30 jours ou entre 1 et 60 mois. Pour moins d'un jour ou 24 heures, saisissez « 0 » jour. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 60 mois. Si la réponse donnée était supérieure à 60 mois, confirmez la réponse et inscrivez « 60 ». Si la personne interrogée ne se souvient pas exactement du nombre de jours, demandez-la et notez-la en fonction de ce qui est médicalement pertinent à saisir. Si les vomissements durent :\n● pendant moins de 3 jours - l'enquêteur doit saisir 2 jours ;\n● pendant plus de 3 jours – l'enquêteur doit saisir 4 jours.",
        choices: {
          days: "Jour",
          months: "mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10190_a: {
        label: "(Id10190_a) [Entrez combien de temps avant la mort il a vomi en jours] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a été supérieure à 30 jours, demandez au répondant de déclarer le délai en mois."
      },
      Id10190_b: {
        label: "(Id10190_b) [Entrez combien de temps avant la mort il a vomi en mois] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse était supérieure à 60 mois, confirmez la réponse et inscrivez 60."
      },
      Id10189: {
        label: "(Id10189) A-t-il vomi au cours de la semaine précédant le décès ?",
        guidance:
          "Cette question est posée pour confirmer si le patient a eu un épisode de vomissements spécifiquement au cours de la semaine précédant le décès. Même si les vomissements n'étaient peut-être pas un symptôme important de la maladie ayant causé le décès, la présence d'un épisode de vomissements au cours de la semaine précédente pourrait compliquer ou exacerber la maladie.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10189_1: {
        label: "(Id10189_1) Est-ce qu'il/elle vomissait à chaque fois qu'il/elle mangeait et/ou buvait ?",
        guidance: "Cette question permet d'évaluer la gravité des vomissements.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10191: {
        label: "(Id10191) Y avait-il du sang dans le vomi ?",
        guidance:
          "Les vomissements de sang sont un signe important de maladie de l'estomac ou du foie et, s'ils étaient considérables, ils pourraient avoir précipité la mort. Le sang frais dans les vomissures est facilement reconnaissable et crée une prise de conscience et une inquiétude immédiates concernant la maladie. Il est important de bien distinguer les vomissements de sang (contenu de l’estomac) et la toux de sang (provenant de la poitrine) ; car cela est parfois confus parmi les répondants. Clarifiez avec le répondant et notez la réponse en conséquence.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10192: {
        label: "(Id10192) Le vomi était-il noir ?",
        hint: "Dans certains cas, il peut y avoir un léger saignement dans l’estomac qui s’accumule au fil du temps avant de déclencher des vomissements. Dans ces cas, le contenu du vomi n’apparaît pas aussi rouge vif : à mesure que le sang se mélange avec d’autres contenus de l’estomac, il change de couleur en une substance noirâtre et semi-solide qui peut ressembler à du marc de café.",
        guidance:
          "Dans certains cas, il peut y avoir un léger saignement dans l’estomac sur une période de plusieurs heures, avant de s’accumuler dans un volume suffisant pour déclencher des vomissements. Dans de tels cas, le contenu des vomissures n’apparaît pas aussi rouge vif, car le sang se mélange aux autres contenus de l’estomac et change de couleur pour devenir une substance semi-solide noirâtre. Il peut y avoir plus d’un épisode de vomissements de substance noirâtre – qui peuvent ressembler à du marc de café.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10194: {
        label: "(Id10194) Avait-il des douleurs abdominales ?",
        guidance:
          "La présence de douleurs abdominales peut donner une indication sur la nature de l’affection abdominale et pourrait également avoir conduit à une tentative de recours à des soins médicaux ou à un soulagement de la douleur. Dans certains cas, la douleur d’une crise cardiaque peut être ressentie ou décrite comme une douleur aiguë dans la partie supérieure de l’abdomen. En général, cette question porte sur la présence d’une apparition brutale de douleurs abdominales. Il existe peut-être un terme local pour le décrire. Assurez-vous que le terme local est inclus dans la version traduite du questionnaire et utilisez le terme local pour approfondir. Si la réponse est « NON/NSP/Réf », passez à Id10200.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10195: {
        label: "(Id10195) La douleur abdominale était-elle intense ?",
        guidance:
          "La gravité de la douleur peut aider à formuler le diagnostic. Une douleur intense entraînant un effondrement et nécessitant une assistance médicale serait enregistrée comme une réponse positive. Sondez attentivement et assurez-vous qu'une réponse négative n'est enregistrée que s'il y a eu une douleur passagère non spécifique. Toute réponse directe du répondant par « OUI », même sans réserve, doit être enregistrée comme telle et passer aux questions suivantes.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      id10196_unit: {
        label: "(id10196_unit) Depuis combien de temps a-t-il eu des douleurs abdominales ?",
        hint: "Si le répondant est incapable de répondre, posez la question : La douleur abdominale a-t-elle duré moins de 2 semaines (l'enquêteur doit inscrire 13 jours) ou pendant au moins 2 semaines (l'enquêteur doit inscrire 15 jours) ? Entrez 1 unité seulement : 0 à 23 heures, 1 à 30 jours ou 1 à 60 mois. 1 semaine = 7 jours.",
        guidance:
          "La relation temporelle entre le symptôme et l’événement du décès est importante pour déterminer la cause du décès. Sélectionnez la meilleure unité en fonction de la réponse – heures, jours ou mois. Une réponse valide se situe entre 0 et 23 heures, 1 à 30 jours ou 1 à 60 mois. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 60 mois. Si la réponse donnée était supérieure à 60 mois, confirmez la réponse et inscrivez « 60 ». Si le répondant ne se souvient pas de la durée de la douleur abdominale, invitez-le et notez-le en fonction de ce qui est médicalement pertinent à saisir. Si les douleurs abdominales durent :\n● depuis moins de 2 semaines - l'enquêteur doit saisir 13 jours ;\n● pendant au moins 2 semaines – l'enquêteur doit saisir 15 jours.",
        choices: {
          hours: "Heures",
          days: "Jour",
          months: "Mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10196: {
        label: "(Id10196) [Entrez combien de temps il a eu des douleurs abdominales en heures] :",
        hint: "Entrez 1 à 23 heures.",
        constraintMessage:
          "Si la réponse était supérieure à 23 heures, demandez au répondant d'indiquer le temps passé dans une autre unité."
      },
      Id10197_a: {
        label: "(Id10197_a) [Entrez combien de temps il a eu des douleurs abdominales en jours] :",
        hint: "Entrez 0 à 30 jours. 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a dépassé 30 jours, demandez au répondant d'indiquer le délai en mois."
      },
      Id10198: {
        label: "(Id10198) [Entrez combien de temps il a eu des douleurs abdominales en mois] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse est supérieure à 60, confirmez la réponse et entrez 60."
      },
      Id10197: {
        label: "(Id10197) Nombre calculé de jours avec douleurs abdominales"
      },
      Id10199: {
        label: "(Id10199) Où se trouvait la douleur abdominale ?",
        guidance:
          "Le site de la douleur abdominale aiguë est également un indice important, mais il s’agit plutôt d’une perception subjective de la part du défunt et peut ne pas être clairement communiquée au répondant. Il pourrait donc être difficile pour le répondant de se souvenir et de répondre avec précision à cette question. Montrez les quatre quadrants de l'abdomen (supérieur droit, supérieur gauche, inférieur droit, inférieur gauche) et demandez si le défunt a pointé du doigt cette zone lorsqu'il a ressenti de la douleur.",
        constraintMessage: 'Impossible de choisir "Partout" avec d\'autres choix',
        choices: {
          upper_right: "Abdomen supérieur droit",
          upper_left: "Abdomen supérieur gauche",
          lower_right: "Abdomen inférieur droit",
          lower_left: "Abdomen inférieur gauche",
          all_over: "Partout sur le ventre",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10200: {
        label: "(Id10200) Avait-il un abdomen plus proéminent que d'habitude ?",
        hint: "Un abdomen saillant plus que d’habitude se présente comme une expansion de tout l’abdomen. Un abdomen saillant est différent d’une masse abdominale qui se manifeste par un élargissement localisé de l’abdomen.",
        guidance:
          "Certaines maladies (le plus souvent une insuffisance hépatique) provoquent une accumulation de liquide dans l'abdomen, ce qui entraîne une augmentation de la taille de l'abdomen, le rendant inhabituellement proéminent et saillant. De plus, en cas d'occlusion intestinale, il peut y avoir une accumulation de gaz et d'autres contenus intestinaux, mais cela est très rare par rapport à l'accumulation de liquide. Cette augmentation de la taille de l’abdomen est souvent observée et rappelée par les proches des défunts. Si « NON/NSP/Réf », passez à Id10204.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10201_unit: {
        label:
          "(Id10201_unit) Pendant combien de temps avant sa mort avait-il un abdomen plus proéminent que d'habitude ?",
        hint: "Si le répondant n'est pas en mesure de répondre, posez la question : Avait-elle un abdomen saillant plus que d'habitude depuis moins de 2 semaines (l'enquêteur doit saisir 13 jours) ou pendant au moins 2 semaines (l'enquêteur doit saisir 15 jours) ? Entrez 1 unité seulement : 0-30 jours ou 1-60 mois. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        guidance:
          "La distension de l'abdomen due à une obstruction de l'intestin commence rapidement et dure quelques jours car la personne doit rechercher un traitement urgent pour survivre à cette maladie. Il est possible que la personne décédée ait consulté un médecin pour obtenir un soulagement, car cette affection pourrait être associée à un inconfort important, à un essoufflement et à une réduction de la mobilité. Sélectionnez la meilleure unité en fonction de la réponse – jours ou mois. Une réponse valide se situe entre 0 et 30 jours ou entre 1 et 60 mois. Pour moins d'un jour ou 24 heures, saisissez « 0 » jour. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 60 mois. Si la réponse donnée était supérieure à 60 mois, confirmez la réponse et inscrivez « 60 ». Si le répondant ne se souvient pas de la durée de l’abdomen saillant plus que d’habitude, demandez-le et enregistrez-le en fonction de ce qui est médicalement pertinent à capturer. Si l’abdomen saillant persiste :\n● depuis moins de 2 semaines - l'enquêteur doit saisir 13 jours ;\n● pendant au moins 2 semaines – l'enquêteur doit saisir 15 jours.",
        choices: {
          days: "Jour",
          months: "Mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10201_a: {
        label:
          "(Id10201_a) [Entrez combien de temps avant la mort il avait un abdomen plus saillant que d'habitude en jours] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a dépassé 30 jours, demandez au répondant d'indiquer le délai en mois."
      },
      Id10202: {
        label:
          "(Id10202) [Entrez combien de temps avant la mort il avait un abdomen plus saillant que d'habitude en mois] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse est supérieure à 60, confirmez la réponse et entrez 60."
      },
      Id10201: {
        label: "(Id10201) Nombre calculé de jours avec abdomen saillant"
      },
      Id10203: {
        label: "(Id10203) À quelle vitesse a-t-il développé un abdomen saillant ?",
        guidance:
          "L'apparition et la progression de ce signe suivent différents schémas dans différentes conditions ; en cas d'occlusion intestinale, elle serait relativement courte (quelques heures – 2/3 jours) ; mais elle est plus progressive dans d'autres affections plus courantes telles que l'insuffisance hépatique, les cancers et l'insuffisance cardiaque. Clarifiez et enregistrez la réponse.",
        choices: {
          rapidly: "Rapidement",
          slowly: "lentement",
          DK: "Ne sait pas",
          Ref: "Refus de repondre"
        }
      },
      Id10204: {
        label: "(Id10204) Avait-il une masse dans l'abdomen ?",
        hint: "La masse abdominale est un gonflement ou une hypertrophie localisée dans une zone de l’abdomen.",
        guidance:
          "La masse abdominale est un gonflement ou une hypertrophie localisée dans une zone de l’abdomen. Cela peut ne pas être perçu visiblement par les personnes interrogées et peut uniquement être rapporté par le défunt à ses proches, comme un sentiment de lourdeur ou d'inconfort. Souvent, il aurait pu y avoir une tentative de recours à des soins médicaux, qui pourraient être rappelés par les proches. Dans ce cas, il est possible qu'un diagnostic soit disponible dont le répondant pourrait se souvenir. S'il y a une réponse positive, sondez attentivement et n'oubliez pas de revenir sur cette question lors de l'enquête sur les dossiers médicaux dans la section 9, et enregistrez tous les détails pertinents sur l'accès aux soins de santé et les informations de diagnostic dans cette section. Si la réponse est « NON/NSP/Réf », passez à Id10207.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10205_unit: {
        label: "(Id10205_unit) Pendant combien de temps a-t-il eu une masse dans l'abdomen ?",
        hint: "Si le répondant est incapable de répondre, posez la question : Avait-elle une masse dans l'abdomen depuis moins de 2 semaines (l'enquêteur doit saisir 13 jours) ou pendant au moins 2 semaines (l'enquêteur doit saisir 15 jours) ? Entrez 1 unité seulement : 0-30 jours ou 1-60 mois. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        guidance:
          "La durée pendant laquelle la masse était présente pourrait aider à orienter le diagnostic. Sélectionnez la meilleure unité en fonction de la réponse – jours ou mois. Une réponse valide se situe entre 0 et 30 jours ou entre 1 et 60 mois. Pour moins d'un jour ou 24 heures, saisissez « 0 » jour. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 60 mois. Si la réponse donnée était supérieure à 60 mois, confirmez la réponse et inscrivez « 60 ». Si le répondant ne se souvient pas de la durée de la masse dans l’abdomen, demandez-le et notez-le en fonction de ce qui est médicalement pertinent à capturer. Si la masse dans l'abdomen a duré :\n● depuis moins de 2 semaines - l'enquêteur doit saisir 13 jours ;\n● pendant au moins 2 semaines – l'enquêteur doit saisir 15 jours.",
        choices: {
          days: "Jour",
          months: "Mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10205_a: {
        label: "(Id10205_a) [Entrez combien de temps il a eu une masse abdominale en jours] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a dépassé 30 jours, demandez au répondant d'indiquer le délai en mois."
      },
      Id10206: {
        label: "(Id10206) [Entrez combien de temps il a eu une masse abdominale en mois] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse est supérieure à 60, confirmez la réponse et entrez 60."
      },
      Id10205: {
        label: "(Id10205) Nombre calculé de jours avec une masse dans l'abdomen"
      },
      Id10207: {
        label: "(Id10207) Avait-il un fort mal de tête ?",
        guidance:
          "Les maux de tête sont un symptôme courant et relativement mineur. Il est important que l’enquêteur insiste sur le mot « grave » afin de relier le mal de tête à la cause potentielle du décès. Clarifiez l’importance de la gravité pour le répondant et enregistrez la réponse en conséquence. Des maux de tête sévères peuvent être signalés dans de nombreuses pathologies, notamment la méningite et le paludisme. Des maux de tête soudains et sévères suivis d’une perte de conscience sont parfois observés en cas de maladie cérébrovasculaire/accident vasculaire cérébral. Il existe peut-être un terme local pour le décrire. Assurez-vous que le terme local est inclus dans la version traduite du questionnaire et utilisez le terme local pour approfondir.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10208: {
        label: "(Id10208) Avait-il/elle une raideur ou une douleur à la nuque ?",
        guidance:
          "Une raideur de la nuque est généralement identifiée par l'incapacité de plier le cou vers l'avant pour toucher le menton avec la poitrine, ou par une difficulté à relever la tête de l'oreiller. C'est une caractéristique importante de la méningite (une infection cérébrale), en particulier chez les enfants. Ce signe peut ne pas être facilement observé ou rappelé par le répondant. Pour certains, une raideur de la nuque peut également être signalée comme une douleur au cou. Si nécessaire, clarifiez au répondant la description fournie ci-dessus et enregistrez la réponse. Si « NON/NSP/Réf », passez à Id10212.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10209_units: {
        label:
          "(Id10209_units) Combien de temps avant sa mort avait-il une raideur ou une douleur à la nuque ?",
        hint: "Si le répondant est incapable de répondre, posez la question : A-t-il eu une raideur ou une douleur à la nuque pendant moins d'une semaine (l'enquêteur doit saisir 6 jours) ou pendant au moins 1 semaine (l'enquêteur doit saisir 8 jours) ?  Entrez 1 unité seulement : 0-30 jours ou 1-60 mois. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        guidance:
          "Une raideur de la nuque est généralement identifiée par l'incapacité de plier le cou vers l'avant pour toucher le menton avec la poitrine, ou par une difficulté à relever la tête de l'oreiller. C'est une caractéristique importante de la méningite (une infection cérébrale), en particulier chez les enfants. Ce signe peut ne pas être facilement observé ou rappelé par le répondant. Pour certains, une raideur de la nuque peut également être signalée comme une douleur au cou. Si nécessaire, clarifiez au répondant la description fournie ci-dessus et enregistrez la réponse. Si « NON/NSP/Réf », passez à Id10212.",
        choices: {
          days: "Jour",
          months: "mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10209_a: {
        label:
          "(Id10209_a) [Entrez combien de temps avant le décès, en jours, avait-il eu une raideur ou une douleur à la nuque] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a dépassé 30 jours, demandez au répondant d'indiquer le délai en mois."
      },
      Id10209_b: {
        label:
          "(Id10209_b) [Entrez combien de temps avant le décès, en mois, avait-il eu une raideur ou une douleur à la nuque] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse est supérieure à 60, confirmez la réponse et entrez 60."
      },
      Id10209: {
        label: "(Id10209) Pendant combien de jours avant sa mort a-t-il eu la nuque raide ou douloureuse ?"
      },
      Id10212: {
        label: "(Id10212) Souffrait-il de confusion mentale ?",
        guidance:
          "La « confusion » implique une désorientation de la personne, du temps et de l’espace. Au cours de la maladie en phase terminale, la personne peut avoir des épisodes au cours desquels elle ne reconnaît pas les personnes ou ignore où elle se trouve (à l'hôpital ou à la maison) ; ou peut ne pas être conscient de l'heure, de la partie de la journée, du mois, etc. La « confusion » est parfois associée à un comportement agité ou agité périodique, sans raison évidente. Ce n’est pas la même chose que perdre connaissance. En fait, il n’y a aucune déficience de conscience associée. La « confusion » est un signe important de maladies chroniques provoquant la démence (par exemple la maladie d’Alzheimer ; les effets à long terme suite à une paralysie ; etc.). Cette question ne concerne qu’une confusion mentale de longue date durant plusieurs mois ou années. Clarifiez ces points avec le répondant et enregistrez la réponse en conséquence. Si « NON/NSP/Réf », passez à Id10214.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10213_units: {
        label: "(Id10213_units) Pendant combien de temps a-t-il souffert de confusion mentale ?",
        hint: "Si le répondant est incapable de répondre, posez la question : La confusion mentale a-t-elle duré moins de 3 mois (l'enquêteur doit inscrire 2 mois) ou pendant au moins 3 mois (l'enquêteur doit inscrire 4 mois) ? Entrez 1 unité seulement : 0-30 jours ou 1-60 mois. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        guidance:
          "La durée pendant laquelle la confusion était présente est importante pour le diagnostic. La réponse à cette question confirme la présence d’une confusion à long terme, comme le recherche cette question. Sélectionnez la meilleure unité en fonction de la réponse – jours ou mois. Une réponse valide se situe entre 0 et 30 jours ou entre 1 et 60 mois. Pour moins d'un jour ou 24 heures, saisissez « 0 » jour. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 60 mois. Si la réponse donnée est supérieure à 60 mois, confirmez la réponse et inscrivez « 60 ». Si le répondant ne se souvient pas de la durée de la confusion mentale, invitez-le et enregistrez-le en fonction de ce qui est médicalement pertinent à saisir. Si la confusion mentale persiste :\n● depuis moins de 3 mois - l'enquêteur doit saisir 2 mois ;\n● depuis au moins 3 mois – l'enquêteur doit saisir 4 mois.",
        choices: {
          days: "Jour",
          months: "mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10213_a: {
        label: "(Id10213_a) [Entrez combien de temps il a eu une confusion mentale en jours] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a dépassé 30 jours, demandez au répondant d'indiquer le délai en mois."
      },
      Id10213_b: {
        label: "(Id10213_b) [Entrez combien de temps il a eu une confusion mentale en mois] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse est supérieure à 60, confirmez la réponse et entrez 60."
      },
      Id10213: {
        label: "(Id10213) Pendant combien de mois a-t-il souffert de confusion mentale ?"
      },
      Id10214: {
        label: "(Id10214) Était-il inconscient ?",
        guidance:
          "L'inconscience signifie l'incapacité totale d'éveiller l'individu sans aucun mouvement autre que la respiration. L’individu ne répond même pas aux stimuli physiques, notamment à la douleur. La mort due à une maladie est généralement précédée d'une période de perte de conscience. Cette série de questions vise à identifier la perte de conscience comme un facteur spécifique important associé à la maladie menant à la mort, indiquant généralement une atteinte du cerveau. Il y a parfois une certaine hésitation ou incertitude sur cette question. Il existe peut-être un terme local pour décrire l'inconscience. Assurez-vous que le terme local est inclus dans la version traduite du questionnaire et utilisez le terme local pour approfondir. Si « NON/NSP/Réf », passez à Id10220.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10216_units: {
        label: "(Id10216_units) Combien de temps avant la mort l'inconscience a-t-elle commencé ?",
        hint: "Si le répondant est incapable de répondre, posez la question : L'inconscience a-t-elle commencé moins de 6 heures avant le décès (l'enquêteur doit inscrire 5 heures), a-t-elle commencé entre 6 et 23 heures (l'enquêteur doit inscrire 23 heures) ; ou a-t-il commencé au moins 24 heures avant le décès (l'enquêteur doit saisir 1 jour) ?  Entrez 1 unité seulement : 0-23 heures ou 1-99 jours. 1 semaine = 7 jours.",
        guidance:
          "Sélectionnez la meilleure unité en fonction de la réponse – heures ou jours. Une réponse valide prend entre 0 et 23 heures ou entre 1 et 99 jours. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 99 jours. Si la réponse donnée a duré plus de 99 jours, confirmez la réponse et inscrivez « 99 ». Si la personne interrogée ne peut pas se rappeler quand l’inconscience a commencé, invitez-la et enregistrez-la en fonction de ce qui est médicalement pertinent à saisir. Si l'inconscience a commencé : \n● moins de 6 heures avant le décès - l'enquêteur doit saisir 5 heures ;\n● entre 6 et 23 heures avant le décès – l'enquêteur doit saisir 23 heures ;\n● au moins 24 heures avant le décès – l'enquêteur doit saisir 1 jour.",
        choices: {
          hours: "Heures",
          days: "Jour",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10216_a: {
        label: "(Id10216_a) [Entrez combien de temps avant le décès l'inconscience a commencé en heures] ?",
        hint: 'La question doit être saisie en heures, mais la personne interrogée ne le sait peut-être pas exactement. Il peut donc être plus facile de demander « combien de temps », puis de convertir la durée en heures. (Moins d\'1 heure = "0").',
        guidance:
          "Sélectionnez la meilleure unité en fonction de la réponse – heures ou jours. Une réponse valide prend entre 0 et 23 heures ou entre 1 et 99 jours. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 99 jours. Si la réponse donnée a duré plus de 99 jours, confirmez la réponse et inscrivez « 99 ». Si la personne interrogée ne peut pas se rappeler quand l’inconscience a commencé, invitez-la et enregistrez-la en fonction de ce qui est médicalement pertinent à saisir. Si l'inconscience a commencé :\n● moins de 6 heures avant le décès - l'enquêteur doit saisir 5 heures ;\n● entre 6 et 23 heures avant le décès – l'enquêteur doit saisir 23 heures ;\n● au moins 24 heures avant le décès – l'enquêteur doit saisir 1 jour.",
        constraintMessage:
          "Si la réponse a été supérieure à 23 heures, demandez au répondant de déclarer le temps en jours."
      },
      Id10216_b: {
        label: "(Id10216_b) [Entrez combien de temps avant le décès l'inconscience a commencé en jours] ?",
        hint: "Si plus de 99, entrez 99.",
        constraintMessage:
          "La réponse probable est inférieure à 99 jours. Si la réponse a été supérieure à 99 jours, confirmez la réponse et entrez 99."
      },
      Id10216: {
        label: "(Id10216) Combien d'heures avant la mort l'inconscience a-t-elle commencé ?"
      },
      Id10217: {
        label:
          "(Id10217) La perte de conscience a-t-elle commencé soudainement, rapidement (au moins en une seule journée) ?",
        guidance:
          "La perte de conscience peut survenir soudainement en cas d'accident vasculaire cérébral (maladie cérébrovasculaire), ou survenir plus progressivement, de manière intermittente, sur une période de plusieurs heures/jours en cas de perte de conscience associée à des infections cérébrales ou à d'autres conditions. C'est généralement le cas des maladies infectieuses. Cette question vise à déterminer la perte de conscience soudaine en une journée maximum, ce qui se produit dans les maladies cérébrovasculaires, ce qui est rare chez les enfants. Clarifiez cet aspect avec le répondant, si nécessaire, et enregistrez la réponse.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10220: {
        label: "(Id10220) A-t-il eu des convulsions généralisées ?",
        hint: "Les convulsions sont des mouvements saccadés ou saccadés rapides de tout le corps (c'est-à-dire des deux bras et des deux jambes), qui s'atténuent fréquemment avec la perte de conscience. Le terme courant pour désigner les convulsions est crises, et il existe souvent un terme local pour de tels mouvements.",
        guidance:
          "Cette question fait référence aux convulsions qui affectent tout le corps, c'est-à-dire les deux bras et les deux jambes, avec des secousses considérables et qui disparaissent généralement dans l'inconscience. Dans d'autres formes, les convulsions n'affectent qu'un ou deux membres, ou parfois uniquement les globes oculaires/le visage/le serrement ou le claquement des dents, etc. Cette question se réfère uniquement aux convulsions affectant l'ensemble du corps, donc clarifiez cet aspect et enregistrez la réponse en conséquence. Les convulsions sont des contractions rapides ou des mouvements saccadés de parties de membres ou parfois de membres entiers, qui s'atténuent fréquemment avec la perte de conscience. Le terme courant pour désigner les convulsions est crises, et il existe souvent un terme local pour de tels mouvements. L'apparition de telles crises est révélatrice de certaines maladies, notamment l'épilepsie, et d'autres maladies qui provoquent des taux anormaux de produits chimiques dans le sang, provoquant des crises. Si nécessaire, démontrez les mouvements convulsifs des membres (et des globes oculaires) et enregistrez la réponse en conséquence. Si « NON/NSP/Réf », passez à Id10223.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10222: {
        label: "(Id10222) Est-il devenu inconscient immédiatement après la convulsion ?",
        guidance:
          "La perte de conscience survient généralement après une convulsion généralisée, donc une réponse positive confirmera la survenue et facilitera ainsi le diagnostic.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10275: {
        label:
          "(Id10275) Le bébé a-t-il eu des convulsions commençant au cours des premières 24 heures de sa vie ?",
        guidance:
          "Les questions Id10275 et Id10276 visent à confirmer le moment et à identifier l'apparition des convulsions immédiatement après la naissance, au cours du premier jour de vie, qui sont susceptibles d'être associées à certains troubles congénitaux du cerveau ou à d'autres anomalies chimiques dans le sang. Ne demandez que les défunts qui étaient",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10276: {
        label:
          "(Id10276) Le bébé a-t-il eu des convulsions commençant plus de 24 heures après la naissance ?",
        guidance:
          "Les convulsions survenant après le premier jour de vie pourraient être associées au tétanos néonatal. Ne demandez que les défunts qui étaient",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10223: {
        label: "(Id10223) Avait-il des problèmes d'urine ?",
        hint: "Les problèmes urinaires peuvent inclure des douleurs ou des difficultés à uriner, du sang dans les urines ou une incapacité à uriner.",
        guidance:
          "Expliquez au répondant que les problèmes urinaires font référence au fait d'uriner beaucoup ou pas du tout et à la présence de sang dans les urines. Il s'agit d'une question générale pour déterminer si le défunt a eu des problèmes de miction. Les principaux problèmes liés à la miction qui sont liés à des causes spécifiques de décès sont la difficulté à uriner, le fait d'uriner moins ou pas pendant une certaine période, l'augmentation de la fréquence des mictions et le passage du sang dans les urines. Demandez-lui s'il a eu l'un de ces problèmes. Si « NON/NSP/Réf », passez à Id10230.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10226: {
        label: "(Id10226) Au cours de sa dernière maladie, a-t-il déjà eu du sang dans les urines ?",
        guidance:
          "Le passage du sang dans les urines est une caractéristique majeure du cancer de la vessie ou du rein. Cela peut également se produire dans certaines infections parasitaires. Il y a un passage de sang franc (rouge) et serait facilement reconnu par le patient et signalé à ses proches, ce qui pourrait conduire à la recherche de soins de santé. Par conséquent, si ce symptôme était présent, il y a de fortes chances d’obtenir une réponse positive.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10224: {
        label: "(Id10224) A-t-il arrêté d'uriner ?",
        hint: "Cela signifie que la personne décédée a arrêté d’uriner et n’a plus uriné dans les 24 heures (ou plus) précédant le décès.",
        guidance:
          "Cela signifie que le défunt a arrêté d'uriner. Nous posons cette question parce que l’arrêt de la miction pendant plus d’un jour ou deux avant le décès peut être dû à un trouble ou à une insuffisance rénale. Plus rarement, il peut s'agir d'un symptôme d'obstruction du canal qui transporte l'urine de la vessie hors du corps, mais cela s'accompagne de douleurs abdominales sévères. Dans les maladies rénales, il y a généralement une période de maladie considérable avant l'apparition d'un arrêt de la miction. Clarifiez ce que l'on entend par arrêt de l'urine et enregistrez la réponse comme indiqué. REMARQUE : Il est possible qu'une personne ait à la fois uriné plus souvent que d'habitude ET arrêté d'uriner ; les deux conditions pourraient exister à différents moments de la maladie qui a conduit au décès.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10230: {
        label: "(Id10230) Avait-il un ulcère au pied ?",
        guidance:
          "Dans certaines pathologies, notamment chez les personnes âgées et chez les diabétiques, des ulcères chroniques et non cicatrisants apparaissent sur le pied. Ces ulcères ont tendance à devenir septiques (voir question suivante) et continuent souvent à grossir, avec de faibles chances de guérison. La présence de tels ulcères est un indice essentiel dans le diagnostic de ces affections. Cela revêt une importance considérable dans le cas des personnes diabétiques. Si « NON/NSP/Réf », passez à Id10227.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10231: {
        label: "(Id10231) L'ulcère du pied contenait-il du pus ?",
        guidance:
          "La présence de pus dans l’ulcère du pied qui ne guérit pas est un signe diagnostique important. Le pus est un liquide épais de couleur verte ou jaune qui s’accumule continuellement à la surface de l’ulcère.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10232_units: {
        label: "(Id10232_units) Depuis combien de temps l'ulcère du pied a-t-il eu du pus ?",
        hint: "Si le répondant est incapable de répondre, posez la question : L'ulcère du pied avait-il du pus depuis moins de 2 semaines (l'intervieweur doit saisir 13 jours) ou pendant au moins 2 semaines (l'intervieweur doit saisir 15 jours) ?",
        guidance:
          "La durée pendant laquelle l'ulcère infecté était présent sur le pied indique la gravité de la maladie et sa contribution potentielle parmi les facteurs causant la mort. Une durée plus longue indique également la difficulté de traiter ou de contrôler les facteurs sous-jacents tels que le diabète, guidant ainsi également le diagnostic de la cause sous-jacente du décès. Sélectionnez la meilleure unité en fonction de la réponse – jours ou mois. Une réponse valide se situe entre 0 et 30 jours ou entre 1 et 60 mois. Pour moins d'un jour ou 24 heures, saisissez « 0 » jour. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 60 mois. Si la réponse donnée était supérieure à 60 mois, confirmez la réponse et inscrivez « 60 ». Si le répondant ne se souvient pas de la durée, invitez-le et enregistrez-le en fonction de ce qui est médicalement pertinent à saisir. Si l'ulcère du pied contenait du pus :\n● depuis moins de 2 semaines - l'enquêteur doit saisir 13 jours ;\n● pendant au moins 2 semaines – l'enquêteur doit saisir 15 jours",
        choices: {
          days: "Jour",
          months: "mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10232_a: {
        label: "(Id10232_a) [Entrez la durée pendant laquelle l'ulcère du pied avait du pus en jours] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a dépassé 30 jours, demandez au répondant d'indiquer le délai en mois."
      },
      Id10232_b: {
        label: "(Id10232_b) [Entrez la durée pendant laquelle l'ulcère du pied avait du pus en mois] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse est supérieure à 60, confirmez la réponse et entrez 60."
      },
      Id10232: {
        label: "(Id10232) Pendant combien de jours l'ulcère du pied a-t-il suinté du pus ?"
      },
      Id10227: {
        label: "(Id10227) Avait-il des ulcères ou des plaies ailleurs sur le corps ?",
        hint: "Les ulcères et les plaies font référence à des lésions de la peau ou des muqueuses qui tardent à guérir ou qui reviennent sans cesse.",
        guidance:
          "Des troubles de la peau sont parfois observés lors de la maladie précédant le décès. Celles-ci pourraient prendre la forme de plaies, d’ulcères, d’ampoules, ou de plaies infectées ou « septiques », et pourraient être associées à une mauvaise santé chronique. Chez les adolescents et les adultes, ils peuvent initialement apparaître sous forme de cloques ou de plaques cutanées surélevées contenant du liquide. Chez les adultes/personnes âgées, des escarres peuvent apparaître dans le dos en raison d'un état d'alitement prolongé. Clarifiez ces points avec le répondant et enregistrez la réponse en conséquence. Il peut y avoir des termes locaux pour le décrire. Assurez-vous que les termes locaux sont inclus dans la version traduite du questionnaire et utilisez les termes locaux pour approfondir. Si « NON/NSP/Réf », passez à Id10233.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10229: {
        label: "(Id10229) Les ulcères ou les plaies contenaient-ils du pus ?",
        guidance:
          "Les plaies apparaissent parfois initialement sous la forme de minuscules bulles sur la peau, appelées cloques. Les « ampoules » sont une peau surélevée qui contient du liquide. De telles cloques peuvent être observées chez les nourrissons ou les jeunes enfants, accompagnées de fièvre. Souvent, le liquide clair se transforme en pus. Dans d’autres cas, l’escarre chronique peut s’infecter et se remplir de pus.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10233: {
        label: "(Id10233) A-t-il eu une éruption cutanée ?",
        guidance:
          "Une « éruption cutanée » est une anomalie cutanée qui n’est ni une coupure ni une ecchymose. Il apparaît généralement sous la forme d’un ensemble de taches rouges sur la peau, ou parfois sous la forme d’une tache rouge ou d’une tache sur la peau. Elle est parfois associée à des irritations, des démangeaisons ou des douleurs. Il peut y avoir un terme local pour décrire une éruption cutanée. Assurez-vous que le terme local est inclus dans la version traduite du questionnaire et utilisez le terme local pour approfondir. Pour Adulte si « NON/NSP/Réf », passez à Id10237. Pour les enfants si « NON/NSP/Réf », passez à Id10238.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10234: {
        label: "(Id10234) Pendant combien de jours a-t-il eu une éruption cutanée ?",
        hint: "Si le répondant est incapable de répondre, posez la question : L'éruption cutanée a-t-elle duré moins d'une semaine (l'enquêteur doit saisir 6 jours) ou pendant au moins 1 semaine (l'enquêteur doit saisir 8 jours) ? . Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours ; 1 mois = 30 jours. Entrez « 99 » pour « ne sait pas ». Entrez « 88 » pour « refuser ».",
        guidance:
          "La durée de l’éruption cutanée nous aidera à comprendre sa gravité et également à savoir si ce problème faisait partie de la maladie qui a entraîné la mort. Si moins de 1 jour ou 24 heures, entrez « 0 » jour. Utilisez 1 semaine = 7 jours ou 1 mois = 30 jours pour déterminer le nombre de jours. Si le répondant ne se souvient pas de la durée, invitez-le et enregistrez-le en fonction de ce qui est médicalement pertinent à saisir. Si l’éruption cutanée persiste : \n● moins d'une semaine - l'enquêteur doit saisir 6 jours ;\n● au moins 1 semaine – l'enquêteur doit saisir 8 jours.\nPour je ne sais pas, entrez « 99 ». Pour refusé, inscrivez « 88 ». Une réponse valide est comprise entre 0 et 99. Si la réponse a duré plus de 98 jours, confirmez la réponse et inscrivez « 98 ». Si la réponse à la durée est de 88 jours, inscrivez plutôt « 87 » afin que la réponse ne soit pas automatiquement codée comme refus de réponse.",
        constraintMessage:
          "Veuillez saisir une valeur comprise entre 0 et 99. Si la réponse a été supérieure à 98 jours, confirmez la réponse et saisissez 98."
      },
      Id10235: {
        label: "(Id10235) Où était l'éruption cutanée ?",
        guidance:
          "Il est important de savoir où se situe exactement l’éruption cutanée sur le corps. En effet, la localisation de l'éruption cutanée est caractéristique de certaines conditions et pourrait aider à les diagnostiquer. Cela nous aidera également à savoir si ce problème faisait partie de la maladie qui a conduit au décès. Cochez les cases appropriées, plusieurs réponses sont autorisées.\n● « Tronc » fait référence à la zone poitrine/dos/abdominale. \n● « Extrémités » fait référence aux bras et aux jambes.",
        constraintMessage:
          "Il n'est pas possible de sélectionner « Ne sait pas » ou « Refuse de répondre » avec d'autres options. Veuillez revenir en arrière et corriger la sélection.",
        choices: {
          face: "Visage",
          trunk: "Tronc ou abdomen",
          extremities: "Extrémités",
          everywhere: "partout",
          DK: "Ne sait pas",
          Ref: "Refus de repondre"
        }
      },
      Id10236: {
        label: "(Id10236) A-t-il eu une éruption cutanée due à la rougeole ?",
        guidance:
          "La rougeole est une affection associée à des éruptions cutanées qui survient principalement pendant la petite enfance. Parfois, de telles infections peuvent également survenir chez des enfants plus âgés ou des adultes, mais elles peuvent ne pas s'accompagner d'éruption cutanée et se présentent généralement sous la forme de fièvre et de maladies respiratoires.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10237: {
        label: "(Id10237) A-t-il déjà eu le zona ou le zona ?",
        guidance:
          "Il s’agit d’une forme spécifique d’affection cutanée associée à des problèmes du système immunitaire. Dans certains cas, une éruption cutanée localisée avec de petites cloques contenant un liquide clair apparaît en ligne le long des côtes ou sur le visage, accompagnée d'un courant électrique semblable à une douleur brûlante. La survenue d’une telle éruption cutanée infectieuse peut être associée à d’autres symptômes graves impliquant les poumons ou le cerveau. C'est assez rare. Demandez au répondant si la personne décédée s'est plainte d'une éruption cutanée localisée accompagnée d'une douleur brûlante.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10238: {
        label: "(Id10238) Sa peau s'écaille-t-elle par plaques ?",
        guidance:
          "Chez une personne souffrant de malnutrition de longue date, la peau devient extrêmement sèche et a tendance à se détacher ou à se décoller par plaques. Il s’agit d’un signe facilement reconnaissable lorsqu’il est présent et constitue un signe diagnostique utile.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10239: {
        label: "(Id10239) Avait-il des zones de peau devenues noires ?",
        guidance:
          "Nous posons cette question car cela pourrait indiquer que l'enfant a eu un saignement cutané, ce qui pourrait être dû à une infection qui a causé le décès.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10240: {
        label: "(Id10240) Avait-il des zones cutanées présentant des rougeurs et des gonflements ?",
        guidance:
          "Les infections cutanées peuvent parfois se manifester sous la forme de plaques de rougeur et de gonflement, sans présence de pus, ni de liquide. De telles infections peuvent être associées à de la fièvre et entraîner la mort.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10242: {
        label: "(Id10242) A-t-il saigné du nez, de la bouche ou de l'anus ?",
        guidance:
          "Cette question fait référence à des saignements qui ne sont associés à aucune blessure spécifique. Des saignements du nez, des gencives, de la muqueuse buccale et de l'anus sont fréquemment observés en cas de saignements dus à des troubles de la coagulation sanguine et à des infections comme la dengue et le virus Ebola.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10243: {
        label: "(Id10243) A-t-il perdu du poids de façon notable ?",
        guidance:
          "Certaines maladies sont typiquement associées à une perte de poids rapide précédant le décès, qui pourrait être décrite comme « devenir très mince et faible », « développer des joues enfoncées », « les vêtements/la ceinture se détachent », etc. Une perte de poids de plus de 10 % en 3 mois environ est un signe important. Clarifiez ces aspects avec le répondant pour confirmer ou exclure la perte de poids, et enregistrez la réponse en conséquence. Indépendamment du fait que la réponse soit « OUI/NON/NSP/Réf », la question suivante doit être posée.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10244: {
        label: "(Id10244) Était-il très maigre ou émacié ?",
        guidance:
          "Cette question vise à identifier la malnutrition chez le défunt. L'individu peut avoir souffert d'une insuffisance pondérale constante pendant une période prolongée et n'avoir pas connu de perte de poids rapide au stade terminal. Un individu chroniquement maigre ou émacié aurait souffert de malnutrition qui prédispose à plusieurs infections conduisant à la mort. Ceci est également observé dans les stades terminaux du cancer et dans certaines autres maladies chroniques qui pourraient affecter l'apport nutritionnel au fil du temps.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10245: {
        label: "(Id10245) Avait-il une éruption blanchâtre à l'intérieur de la bouche ou sur la langue ?",
        guidance:
          "Des taches blanchâtres à l’intérieur de la bouche ou sur la langue sont révélatrices d’infections chez les personnes dont le système immunitaire est très faible. Le système immunitaire assure la défense de l’organisme pour lutter contre les infections. Ce signe peut être difficile pour le répondant, à moins d'en être informé par le patient ou par un prestataire de soins. Enregistrez la réponse telle que rapportée. Il peut y avoir un terme local pour décrire une éruption cutanée. Assurez-vous que le terme local est inclus dans la version traduite du questionnaire et utilisez le terme local pour approfondir.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10246: {
        label: "(Id10246) Avait-il une raideur dans tout le corps ou était-il incapable d'ouvrir la bouche ?",
        guidance:
          "Certaines infections du système nerveux entraînent une raideur et une rigidité complètes du dos et de tous les membres, ainsi qu'une mâchoire serrée avec une incapacité à ouvrir la bouche. Il s'agit généralement d'un signe dramatique, dont peuvent se souvenir les personnes interrogées qui ont pris soin du défunt pendant sa maladie en phase terminale.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10247: {
        label: "(Id10247) Avait-il des poches au visage ?",
        hint: "Précisez avec le répondant que les gonflements du visage peuvent inclure uniquement les gonflements des yeux.",
        guidance:
          "Des poches ou un gonflement du visage sont observés lorsqu'il y a une accumulation de liquide (ou d'eau), en particulier dans les espaces/poches autour des yeux et dans d'autres parties. Précisez avec le répondant que les gonflements du visage peuvent inclure les gonflements des yeux. Cette accumulation de liquide est un signe diagnostique important, notamment en cas de maladie rénale, mais aussi dans certains troubles hormonaux. Il peut être observé et rappelé par les répondants, s'il est important. De telles poches du visage peuvent être présentes avec ou sans accumulation de liquide sur d'autres parties du corps telles que les chevilles ou les pieds, comme demandé dans une question ultérieure. Si « NON/NSP/Réf », passez à Id10249.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10248_units: {
        label: "(Id10248_units) Depuis combien de temps a-t-il eu des gonflements au visage ?",
        hint: "Si le répondant est incapable de répondre, posez la question : Les gonflements du visage ont-ils duré moins d'une semaine (l'enquêteur doit saisir 6 jours) ou pendant au moins 1 semaine (l'enquêteur doit saisir 8 jours) ?  Entrez 1 unité seulement : 0-30 jours ou 1-60 mois. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        guidance:
          "La durée des gonflements du visage avant le décès est importante pour comprendre la présence d’une maladie rénale chronique. Le patient peut avoir été sous traitement, auquel cas les gonflements peuvent avoir persisté de manière intermittente pendant plusieurs mois. Demandez et enregistrez la durée des gonflements du visage pendant la maladie en phase terminale. Sélectionnez la meilleure unité en fonction de la réponse – jours ou mois. Une réponse valide se situe entre 0 et 30 jours ou entre 1 et 60 mois. Pour moins d'un jour ou 24 heures, saisissez « 0 » jour. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 60 mois. Si la réponse donnée était supérieure à 60 mois, confirmez la réponse et inscrivez « 60 ». Si le répondant ne se souvient pas de la durée, invitez-le et enregistrez-le en fonction de ce qui est médicalement pertinent à saisir. Si les poches du visage perdurent : \n● pendant moins d'une semaine - l'enquêteur doit saisir 6 jours ;\n● pendant au moins 1 semaine – l'enquêteur doit saisir 8 jours.",
        choices: {
          days: "Jour",
          months: "mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10248_a: {
        label: "(Id10248_a) [Entrez combien de temps il a eu des gonflements du visage en jours] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a dépassé 30 jours, demandez au répondant d'indiquer le délai en mois."
      },
      Id10248_b: {
        label: "(Id10248_b) [Entrez combien de temps il a eu des gonflements du visage en mois] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse est supérieure à 60, confirmez la réponse et entrez 60."
      },
      Id10248: {
        label: "(Id10248) Depuis combien de jours a-t-il eu des gonflements au visage ?"
      },
      Id10249: {
        label: "(Id10249) Avait-il les jambes ou les pieds enflés ?",
        guidance:
          "Des pieds, des chevilles et même des jambes enflés peuvent survenir en raison de l'accumulation de liquide lors de maladies cardiaques et circulatoires, ou d'une maladie rénale. Plusieurs maladies produisent un déséquilibre dans la régulation de l’eau, entraînant son accumulation dans les parties dépendantes du corps. Cette accumulation se manifeste le plus souvent par une accumulation de liquide autour des chevilles, dont la présence pourrait être rappelée par les répondants. Si « NON/NSP/Réf », passez à Id10252.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10250_units: {
        label: "(Id10250_units) Combien de temps le gonflement a-t-il duré ?",
        hint: "Si le répondant est incapable de répondre, posez la question : Le gonflement a-t-il duré moins de 3 jours (l'enquêteur doit inscrire 2 jours) ou plus de 3 jours (l'enquêteur doit inscrire 4 jours) ?  Entrez 1 unité seulement : 0-30 jours ou 1-60 mois. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        guidance:
          "La durée pendant laquelle la collection de liquide était présente est importante pour comprendre la chronicité et la gravité de la maladie. Cela peut se produire de temps en temps, en particulier si le patient reçoit un traitement pour cette maladie. Sondez attentivement et notez le nombre de jours pendant lesquels des chevilles enflées étaient présentes au cours de la maladie en phase terminale. Sélectionnez la meilleure unité en fonction de la réponse – jours ou mois. Une réponse valide se situe entre 0 et 30 jours ou entre 1 et 60 mois. Pour moins d'un jour ou 24 heures, saisissez « 0 » jour. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 60 mois. Si la réponse donnée était supérieure à 60 mois, confirmez la réponse et inscrivez « 60 ». Si la personne interrogée ne se souvient pas de la durée exacte, demandez-la et notez-la en fonction de ce qui est médicalement pertinent à saisir. Si le gonflement dure :\n● pendant moins de 3 jours - l'enquêteur doit saisir 2 jours ;\n● pendant plus de 3 jours – l'enquêteur doit saisir 4 jours.",
        choices: {
          days: "Jour",
          months: "mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10250_a: {
        label: "(Id10250_a) [Entrez la durée du gonflement en jours] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a dépassé 30 jours, demandez au répondant d'indiquer le délai en mois."
      },
      Id10250_b: {
        label: "(Id10250_b) [Entrez la durée du gonflement en mois] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse est supérieure à 60, confirmez la réponse et entrez 60."
      },
      Id10250: {
        label: "(Id10250) Combien de jours le gonflement a-t-il duré ?"
      },
      Id10251: {
        label: "(Id10251) Avait-il les deux pieds enflés ?",
        guidance:
          "Dans certains cas, il peut y avoir un gonflement d’un seul pied, auquel cas l’affection sous-jacente serait différente, il s’agirait plus probablement d’une affection locale de la jambe affectée plutôt que d’une maladie cardiaque ou rénale. Il est donc important de confirmer que le gonflement concernait les deux pieds.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10252: {
        label: "(Id10252) Avait-il un gonflement général du corps ?",
        guidance:
          "Les troubles de longue date entraînent une accumulation de liquide dans les tissus mous de différentes parties du corps, notamment les jambes, l'abdomen, les bras et les mains, le visage ainsi que dans les poumons. Une telle accumulation généralisée de liquide pourrait se produire en cas de maladie rénale, d’insuffisance cardiaque et hépatique, ainsi que d’autres causes plus rares. En outre, l’accumulation généralisée de liquide se développe progressivement sur une période de plusieurs jours, voire semaines. Clarifiez ces aspects avec le répondant et enregistrez la réponse en conséquence.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10254: {
        label: "(Id10254) Avait-il des bosses ou des plaies dans la bouche ?",
        guidance:
          "De petites bosses violettes ou brunes peuvent être observées dans la bouche chez certains patients dont le système immunitaire est affaibli. Ces grumeaux peuvent saigner ou s'infecter lors de la mastication, etc. La présence de ces grumeaux ou plaques peut suggérer une maladie systémique plus grave. Dans d’autres situations plus rares, il peut y avoir un gonflement ou une excroissance chronique située sur la langue ou les gencives, ce qui constituerait une forme de cancer de la bouche. Il peut y avoir une tentative de recours à des soins médicaux pour son diagnostic et son traitement. Sondez attentivement s’il y a une réponse positive et enregistrez la réponse en conséquence.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10253: {
        label: "(Id10253) Avait-il des bosses ailleurs sur le corps ?",
        hint: "Les bosses peuvent se trouver dans le cou, les aisselles, l'aine ou d'autres parties du corps.",
        guidance:
          "Les bosses sont de petites tuméfactions solides et indolores qui sont parfois observées près de l'aisselle, du cou ou de l'aine. Ils sont observés en association avec certains types d’infections ou rarement dans certains cancers. Dans certains cas, les bosses peuvent être présentes à plusieurs endroits et des deux côtés, ce qui indique une forme de maladie plus généralisée. À moins que les masses ne soient assez grosses ou que le patient ne soit alité, elles peuvent ne pas être observées par le répondant. Il peut y avoir un terme local pour décrire les grumeaux. Assurez-vous que le terme local est inclus dans la version traduite du questionnaire et utilisez le terme local pour approfondir. Si « NON/NSP/Réf », passez à Id10258.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10255: {
        label: "(Id10255) Avait-il des bosses sur le cou ?",
        guidance:
          "Cette question vise à confirmer la présence de bosses sur le côté du cou. Dans certains cas, la grosseur peut traverser la peau et une matière blanchâtre ou du pus peut suinter de la grosseur. Dans de telles situations, il est probable qu'une tentative de recours à des soins médicaux soit tentée et, si tel est le cas, il peut y avoir une opinion sur la cause médicale de la grosseur et sur le traitement reçu. Clarifiez ces aspects, et en cas de réponse positive, notez les détails supplémentaires dans la section sur l'accès aux soins de santé, ou dans la section « Narration ouverte ».",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10256: {
        label: "(Id10256) Avait-il des bosses sous l'aisselle ?",
        guidance:
          "Cette question vise à confirmer la présence de bosses au niveau de l'aisselle. Il aurait pu être difficile pour le répondant de les observer, à moins qu'ils ne soient signalés par le défunt ou signalés par un professionnel de la santé.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10257: {
        label: "(Id10257) Avait-il des bosses à l'aine ?",
        guidance:
          "Cette question vise à confirmer la présence de bosses au niveau de l’aine, qui est la jonction entre le corps et le membre inférieur.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10258: {
        label: "(Id10258) Était-il paralysé d'une manière ou d'une autre ?",
        guidance:
          "La paralysie implique la faiblesse ou la perte de force ou de puissance dans certaines parties du corps. La faiblesse peut être partielle ou parfois totale, avec perte totale de puissance. La paralysie est généralement un signe facilement reconnaissable et mémorisable et constitue une caractéristique importante des maladies ou des lésions du système nerveux. Si « NON/NSP/Réf », passez à Id10261.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10259: {
        label: "(Id10259) Souffrait-il de paralysie d'un seul côté du corps ?",
        guidance:
          "La paralysie d'un côté du corps (bras et jambe droits ; ou bras et jambe gauches) est une caractéristique classique de l'obstruction de l'apport sanguin au cerveau, qui est l'une des causes courantes de décès chez les adultes et les personnes âgées dans la plupart des populations. La paralysie d'un côté du corps est un signe très clairement reconnaissable et facilement rappelé par les proches du défunt. Plusieurs communautés ont même un terme local pour décrire cette condition. Clarifiez la présence de ce signe et enregistrez la réponse en conséquence.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10260: {
        label: "(Id10260) Avait-elle une paralysie des deux jambes ?",
        guidance:
          "Il est important de confirmer si la paralysie affectait uniquement un membre en particulier, des parties du corps ou le corps tout entier. Marquez les parties spécifiques du corps qui ont été observées comme ayant été paralysées. Sélectionnez tout ce qui s'applique.",
        constraintMessage:
          "Il n'est pas possible de sélectionner « Ne sait pas » ou « Refus de répondre » avec d'autres options ou de sélectionner « un seul côté paralysé » et « côté gauche et droit » ou « corps entier » ensemble. . Veuillez revenir en arrière et corriger la sélection.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10261: {
        label: "(Id10261) Y a-t-il eu des difficultés ou des douleurs à avaler ?",
        guidance:
          "La difficulté à avaler est la sensation que la nourriture est coincée dans la gorge ou dans la poitrine. Cela peut être ressenti haut dans le cou ou plus bas, derrière le sternum (sternum) ou près de l'entrée dans le ventre. Il s'agit d'une sensation subjective qui est généralement rapportée par les patients (et rappelée par les proches), en particulier lorsqu'elle interfère avec la prise alimentaire quotidienne, c'est-à-dire lorsqu'elle est facilement reconnue et rappelée par les proches. En outre, il peut y avoir une douleur associée à la difficulté à avaler, comme une douleur de brûlure ou de compression au centre de la poitrine, derrière le sternum ou dans la partie supérieure de l'estomac. Il s’agit d’un symptôme important, alors sondez attentivement et essayez de vous assurer qu’il n’y a pas de fausse réponse négative. Si « NON/NSP/Réf », passez à Id10265.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10262_units: {
        label:
          "(Id10262_units) Pendant combien de temps a-t-il eu des difficultés ou des douleurs à avaler ?",
        hint: "Si le répondant est incapable de répondre, posez la question : La difficulté ou la douleur à avaler a-t-elle duré moins d'une semaine (l'intervieweur doit saisir 6 jours) ou pendant au moins 1 semaine (l'intervieweur doit saisir 8 jours) ?",
        guidance:
          "La durée indique la gravité et la progression de ce symptôme. Des difficultés ou des douleurs à avaler évoluant sur une période de plusieurs semaines sont généralement observées dans des pathologies majeures telles que les cancers de la gorge, des conduites alimentaires et/ou de l'estomac. Déterminez soigneusement la durée du symptôme en sondant l'apparition et la progression, confirmez la présence de ce symptôme jusqu'à la mort et enregistrez la réponse en conséquence. Sélectionnez la meilleure unité en fonction de la réponse – jours ou mois. Une réponse valide se situe entre 0 et 30 jours ou entre 1 et 60 mois. Pour moins d'un jour ou 24 heures, saisissez « 0 » jour. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 60 mois. Si la réponse donnée était supérieure à 60 mois, confirmez la réponse et inscrivez « 60 ». Si la personne interrogée ne se souvient pas de la durée exacte, demandez-la et notez-la en fonction de ce qui est médicalement pertinent à saisir. Si la difficulté ou la douleur à avaler persiste : \n● pendant moins d'une semaine - l'enquêteur doit saisir 6 jours ;\n● pendant au moins 1 semaine – l'enquêteur doit saisir 8 jours.",
        choices: {
          days: "Jour",
          weeks: "Semaines",
          months: "mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10262_a: {
        label:
          "(Id10262_a) [Entrez combien de temps avant le décès il a eu des difficultés ou des douleurs à avaler en jours] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a dépassé 30 jours, demandez au répondant d'indiquer le délai en mois."
      },
      Id10262_b: {
        label:
          "(Id10262_b) [Entrez combien de temps avant le décès il a eu des difficultés ou des douleurs à avaler en mois] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse est supérieure à 60, confirmez la réponse et entrez 60."
      },
      Id10262: {
        label: "(Id10262) Pendant combien de jours avant sa mort a-t-il eu des difficultés à avaler ?"
      },
      Id10262_c: {
        label: "(Id10262_c) La déglutition est-elle devenue impossible ?",
        hint: "La question vise à savoir s'il est devenu impossible pour le défunt d'avaler un quelconque aliment solide ou liquide.",
        guidance:
          "La question vise à savoir s'il est devenu impossible pour le défunt d'avaler un quelconque aliment solide ou liquide.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10265: {
        label: "(Id10265) Avait-il une décoloration jaune des yeux ?",
        guidance:
          "Une décoloration jaune des yeux, connue sous le nom de jaunisse, est souvent présente chez les nouveau-nés et est généralement légère. Cependant, chez le nouveau-né, cela peut survenir en relation avec des problèmes de groupe sanguin de la mère et du bébé, particulièrement observés dans les 1 à 2 jours suivant la naissance. Cela peut également être observé en cas d'infections graves. Parfois, à des stades avancés, on observe également une décoloration jaune des paumes ou de la peau et, si elle est observée, l'urine est également d'une couleur jaune intense. Enfants et adultes : Si « NON/NSP/Réf », passez à Id10267.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10266_units: {
        label: "(Id10266_units) Depuis combien de temps a-t-il eu une décoloration jaune ?",
        hint: "Si le répondant est incapable de répondre, posez la question : La décoloration jaune a-t-elle duré moins de 3 semaines (l'enquêteur doit saisir 20 jours) ou pendant au moins 3 semaines (l'enquêteur doit saisir 22 jours) ?  Entrez 1 unité seulement : 0-30 jours ou 1-60 mois. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        guidance:
          "La durée pendant laquelle une décoloration jaunâtre était présente aide à indiquer la gravité de la maladie. Vérifiez si la jaunisse était présente tout au long de la maladie en phase terminale ayant conduit au décès et enregistrez la durée. Sélectionnez la meilleure unité en fonction de la réponse – jours ou mois. Une réponse valide se situe entre 0 et 30 jours ou entre 1 et 60 mois. Pour moins d'un jour ou 24 heures, saisissez « 0 » jour. Utiliser 1 semaine = 7 jours. Une réponse probable est inférieure à 60 mois. Si la réponse donnée était supérieure à 60 mois, confirmez la réponse et inscrivez « 60 ». Si la personne interrogée ne se souvient pas de la durée exacte, demandez-la et notez-la en fonction de ce qui est médicalement pertinent à saisir. Si la décoloration jaune persiste : \n● depuis moins de 3 semaines - l'enquêteur doit saisir 20 jours ; \n● pendant au moins 3 semaines – l'enquêteur doit saisir 22 jours.",
        choices: {
          days: "Jour",
          months: "mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10266_a: {
        label: "(Id10266_a) [Entrez combien de temps il a eu la décoloration jaune en jours] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a dépassé 30 jours, demandez au répondant d'indiquer le délai en mois."
      },
      Id10266_b: {
        label: "(Id10266_b) [Entrez combien de temps il a eu la décoloration jaune en mois] :",
        hint: "Entrez 1 à 60 mois.",
        constraintMessage:
          "La réponse probable est inférieure à 60 mois. Si la réponse est supérieure à 60, confirmez la réponse et entrez 60."
      },
      Id10266: {
        label: "(Id10266) Pendant combien de jours a-t-il eu une décoloration jaune ?"
      },
      Id10267: {
        label: "(Id10267) Ses cheveux ont-ils changé de couleur pour devenir rougeâtres ou jaunâtres ?",
        guidance:
          "Chez les enfants plus âgés aux cheveux noirs, un changement de couleur des cheveux vers le rouge, le brun terne ou le jaune est révélateur d'une malnutrition modérée à avancée. Cela peut survenir en conjonction avec d’autres symptômes tels que la maigreur, l’émaciation et les infections.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10268: {
        label: "(Id10268) Était-il pâle ou avait-il les paumes, les yeux ou le lit des ongles pâles ?",
        hint: "Une carence sanguine à long terme entraîne une apparence pâle et blanchâtre des lèvres, de la langue et du sac oculaire. Parfois, on parle d’amincissement, de manque de sang ou de pâleur.",
        guidance:
          "Une carence sanguine à long terme entraîne une apparence pâle et blanchâtre des lèvres, de la langue et du sac oculaire. On parle parfois de fluidification du sang. Cela peut être dû à une perte de sang chronique, à une destruction ou à une diminution de la production de sang due à une infection cancéreuse. L'apparence pâle pourrait être reconnue et rappelée par les répondants.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10269: {
        label: "(Id10269) Avait-il les yeux enfoncés ?",
        guidance:
          "Des yeux profondément enfoncés peuvent être observés chez les nourrissons malades et les très jeunes enfants, ce qui est le signe d'une diminution marquée de l'eau dans le corps. Il s’agit d’un signe important qui aide à diagnostiquer la cause du décès, mais il est subtil et peut ne pas être facilement observé ou mémorisé par le répondant.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10271: {
        label:
          "(Id10271) Le bébé était-il capable de téter ou de prendre le biberon dans les 24 heures suivant la naissance ?",
        hint: "Cette question ne doit être posée que si l'enfant avait moins d'un an au moment de son décès.",
        guidance:
          "Une tétée ou une alimentation normale est un signe de bonne santé chez le nouveau-né. L'absence de tétée à la naissance est révélatrice de certaines conditions. Ne demandez que les défunts qui étaient",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10272: {
        label: "(Id10272) Le bébé a-t-il déjà tété normalement ?",
        hint: "Cette question ne doit être posée que si l'enfant avait moins d'un an au moment de son décès.",
        guidance:
          "Cette question est posée pour savoir s'il y a eu un effort normal et sain pour téter, ou s'il y a eu une faiblesse ou une léthargie dans l'effort de succion. Clarifier la distinction entre effort « normal/sain » et effort faible/léthargique. De plus, la tétée pourrait être affectée par certaines malformations congénitales des lèvres, de la bouche ou de la gorge. Si nécessaire, expliquez ces aspects de la normale et des problèmes liés à l'allaitement et enregistrez la réponse en conséquence. Ne demandez que les défunts qui étaient",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10273: {
        label: "(Id10273) Le bébé a-t-il arrêté de téter ?",
        hint: "Cette question ne doit être posée que si l'enfant avait moins d'un an au moment de son décès.",
        guidance:
          "Dans certaines infections comme le tétanos, le bébé perd la capacité de téter. La mère peut le reconnaître et est en mesure de signaler un tel arrêt si on lui demande soigneusement. Ne demandez que les défunts qui étaient",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10274_a: {
        label: "(Id10274_a) Combien de jours après la naissance le bébé a-t-il arrêté de téter ?",
        hint: "Si l'enquêté est incapable de répondre, posez la question suivante : Le bébé a-t-il arrêté de téter au cours du premier jour de sa vie (l'enquêteur doit saisir 0 jour), ou au moins avant le deuxième jour de sa vie (l'enquêteur doit saisir 3 jours) ?",
        guidance:
          "Le nombre de jours après la naissance pendant lesquels le bébé a cessé de téter est un indicateur important pour diagnostiquer le tétanos néonatal. Sondez attentivement pour obtenir une réponse précise. Moins de 1 jour = « 0 ». Pour je ne sais pas, entrez « 99 ». Pour refuser, entrez « 88 ». La réponse ne doit pas dépasser l’âge néonatal en jours au moment du décès. Si l’enquêté ne se souvient pas exactement du moment où le bébé a arrêté de téter, invitez-le et notez-le en fonction de ce qui est médicalement pertinent à saisir : si le bébé a arrêté de téter au cours du premier jour de sa vie, l’enquêteur doit saisir 0 jour ; ou si le bébé a arrêté de téter au moins au deuxième jour de sa vie – l'enquêteur doit saisir 3 jours",
        constraintMessage: "Veuillez saisir une valeur inférieure à l'âge néonatal en jours au décès."
      },
      Id10274_units: {
        label: "(Id10274_units) Combien de temps après la naissance le bébé a-t-il arrêté de téter ?",
        hint: "Si l'enquêté est incapable de répondre, posez la question : Le bébé a-t-il arrêté de téter au cours du premier jour de sa vie (l'intervieweur doit saisir 0 jour), ou au moins avant le deuxième jour de sa vie (l'enquêteur doit saisir 3 jours) ? Saisissez une seule unité : 0 à 30 jours ou 1 à 11 mois. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        guidance:
          "Ne demandez que les défunts qui étaient \n● au cours du premier jour de vie - l'enquêteur doit saisir 0 jour ;.\n● au moins avant le deuxième jour de la vie – l'enquêteur doit saisir 3 jours.",
        choices: {
          days: "Jour",
          months: "mois",
          DK: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10274_b: {
        label:
          "(Id10274_b) [Entrez combien de temps après la naissance le bébé a arrêté de téter en jours] :",
        hint: "Entrez 0 à 30 jours. Moins de 1 jour ou 24 heures = 0 jour ; 1 semaine = 7 jours.",
        constraintMessage:
          "Si la réponse a dépassé 30 jours, demandez au répondant d'indiquer le délai en mois."
      },
      Id10274_c: {
        label: "(Id10274_c) [Entrez combien de temps après la naissance le bébé a arrêté de téter en mois] :",
        hint: "Entrez 1 à 11 mois.",
        constraintMessage: "Entrez une réponse entre 1 et 11 mois."
      },
      Id10274: {
        label: "(Id10274) Combien de jours après la naissance le bébé a-t-il arrêté de téter ?"
      },
      Id10277: {
        label: "(Id10277) Le corps du bébé est-il devenu raide, avec le dos cambré vers l'arrière ?",
        hint: "Cette question ne doit être posée que si l'enfant avait moins d'un an au moment de son décès.",
        guidance:
          "Le corps du nouveau-né peut devenir raide et courbé vers l’arrière en cas de tétanos néonatal. Les mères peuvent le reconnaître et le signaler lorsqu'on leur demande. Si le répondant a des difficultés à comprendre cette question, démontrez un corps raide et courbé vers l'arrière. Ne demandez que les défunts qui étaient",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10278: {
        label: "(Id10278) Le bébé avait-il une fontanelle bombée ou surélevée ?",
        hint: "Montrer la photo si disponible.",
        guidance:
          "La fontanelle est la zone molle située à l'avant de la tête d'un bébé/nourrisson qui peut enfler et se soulever en cas d'infection du cerveau. Le renflement signifie qu’il était enflé, poussé vers l’extérieur et tendu lorsque le nourrisson était en position assise. Les mères peuvent le reconnaître et le signaler correctement s'il était présent. Sondez attentivement afin d’obtenir une réponse précise.  Ne demandez que les défunts qui étaient",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10279: {
        label: "(Id10279) Le bébé avait-il une fontanelle enfoncée ?",
        hint: "Montrer la photo si disponible.",
        guidance:
          "Une fontanelle enfoncée, ou un point mou à l’avant de la tête, est le signe d’une déshydratation grave. Cela peut être un signe difficile à remarquer ou à retenir pour la mère ou la personne qui s'occupe de l'enfant. Cependant, si on les sonde attentivement, ils peuvent répondre correctement. Ne demandez que les défunts qui étaient",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10281: {
        label: "(Id10281) Le bébé est-il devenu insensible ou inconscient ?",
        hint: "Cette question ne doit être posée que si l'enfant avait moins d'un an au moment de son décès.",
        guidance:
          "L'inconscience signifie l'incapacité totale de réveiller le nouveau-né sans aucun mouvement autre que la respiration. L’enfant ne répond même pas aux stimuli physiques, notamment à la douleur. Les nouveau-nés malades peuvent dormir pendant de longues périodes, mais doivent vérifier s'ils ne peuvent pas être réveillés, même pour se nourrir. L'identification de l'inconscience repose en grande partie sur la suggestion d'une maladie ou d'un trouble du cerveau ou du système nerveux central. Une courte période d'inconscience précède généralement la mort. Dans le cas des nouveau-nés, il est difficile de définir l’inconscience comme un symptôme spécifique d’une atteinte du cerveau ou du système nerveux. Si \"NO/DK/Ref\" est sur Id10281, passez à Id10284",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10282: {
        label:
          "(Id0282) Le bébé est-il devenu inconscient ou inconscient dans les 24 heures suivant la naissance ?",
        hint: "Cette question ne doit être posée que si l'enfant avait moins d'un an au moment de son décès.",
        guidance:
          "L'inconscience signifie l'incapacité totale de réveiller le nouveau-né sans aucun mouvement autre que la respiration. L’enfant ne répond même pas aux stimuli physiques, notamment à la douleur. Les nouveau-nés malades peuvent dormir pendant de longues périodes, mais doivent vérifier s'ils ne peuvent pas être réveillés, même pour se nourrir. L'identification de l'inconscience repose en grande partie sur la suggestion d'une maladie ou d'un trouble du cerveau ou du système nerveux central. Une courte période d'inconscience précède généralement la mort. Dans le cas des nouveau-nés, il est difficile de définir l’inconscience comme un symptôme spécifique d’une atteinte du cerveau ou du système nerveux. Si « OUI » à Id10282, passez à Id10284.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10283: {
        label:
          "(Id10283) Le bébé est-il devenu inconscient ou inconscient plus de 24 heures après la naissance ?",
        hint: "Cette question ne doit être posée que si l'enfant avait moins d'un an au moment de son décès.",
        guidance:
          "L'inconscience signifie l'incapacité totale de réveiller le nouveau-né sans aucun mouvement autre que la respiration. L’enfant ne répond même pas aux stimuli physiques, notamment à la douleur. Les nouveau-nés malades peuvent dormir pendant de longues périodes, mais doivent vérifier s'ils ne peuvent pas être réveillés, même pour se nourrir. L'identification de l'inconscience repose en grande partie sur la suggestion d'une maladie ou d'un trouble du cerveau ou du système nerveux central. Une courte période d'inconscience précède généralement la mort. Dans le cas des nouveau-nés, il est difficile de définir l’inconscience comme un symptôme spécifique d’une atteinte du cerveau ou du système nerveux. Si « NON/NSP/Réf » est sur Id10281, passez à Id10284. Si « OUI » à Id10282, passez à Id10284.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10284: {
        label: "(Id10284) Le bébé est-il devenu froid au toucher ?",
        guidance:
          "La froideur du corps indique que la température corporelle est inférieure à la normale, ce qui est associé à une maladie grave. Il s’agit toutefois d’un signe subjectif qui peut ne pas être facilement rappelé par le répondant. Il faut expliquer soigneusement ce qu'on entend par froid au toucher.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10286: {
        label: "(Id10286) Le bébé est-il devenu léthargique après une période d'activité normale ?",
        guidance:
          "La léthargie signifie un manque de force ou d’activité, avec des yeux ternes. Ce signe peut ne pas être facilement rappelé par le répondant. Il est nécessaire d'expliquer soigneusement ce que l'on entend par léthargie ou de démontrer à quoi ressemblera un bébé léthargique. Si le bébé n’a jamais eu de période d’activité normale, cela devrait être « NON ».",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10287: {
        label: "(Id10287) Le bébé avait-il des rougeurs ou du pus suintant du cordon ombilical ?",
        guidance:
          "Une rougeur du cordon ombilical peut indiquer une infection grave. Il s’agit d’une source importante d’infection chez le nouveau-né, et ce signe peut être facilement reconnu et mémorisé par les répondants.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10288: {
        label: "(Id10288) Le bébé avait-il des ulcères ou des plaies cutanées ?",
        guidance:
          "La présence d'ulcères ou de plaies cutanées, en particulier s'ils sont remplis d'un liquide jaunâtre (pus), indique le signe d'une infection cutanée grave, qui pourrait être liée à la cause du décès.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10289: {
        label: "(Id10289) Le bébé avait-il la peau, les paumes ou les plantes jaunes ?",
        guidance:
          "Une question précédente portait sur la décoloration jaune des yeux. Cette question vise à vérifier la réponse à cette question et porte sur la décoloration jaune généralisée de la peau, des paumes et des pieds. Parfois, la décoloration jaune des yeux peut ne pas être facilement observée, mais celle de l'ensemble du corps peut être observée et rappelée. L'urine est également jaune foncé ; et il existe souvent un terme local pour désigner la jaunisse.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10485: {
        label: "(Id10485) Souffrait-elle d'une fatigue extrême ?",
        hint: "Demandez-vous si la personne décédée se sentait si fatiguée qu'elle avait du mal à sortir du lit et à faire les choses de routine comme prendre une douche ou changer de vêtements.",
        guidance:
          "De nombreux patients atteints du COVID-19 ressentent une fatigue extrême. De nombreuses maladies sont connues pour provoquer de la fatigue et de l’épuisement. Vous devez donc approfondir la question pour distinguer une simple fatigue ou une légère fatigue d’une « fatigue extrême ». En règle générale, les patients atteints du COVID-19 ont du mal à se lever du lit et ont du mal à accomplir leurs activités habituelles, comme prendre une douche et changer de vêtements. Vous devez sonder doucement pour savoir si le défunt souffrait d'une fatigue extrême.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10486: {
        label:
          "(Id10486) A-t-il subi une nouvelle perte, un changement ou une diminution de l'odorat ou du goût ?",
        guidance:
          "Certains patients souffrant du COVID-19 auraient signalé à leurs soignants avoir remarqué un changement dans leur capacité à sentir ou à goûter les aliments. Vous devez préciser que vous posez des questions sur tout changement dans la capacité de sentir ou de goûter au cours de la maladie finale.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10294: {
        label: "(Id10294) Avait-elle une(des) grosseur(s) et/ou un(des) ulcère(s) au sein ?",
        guidance:
          "Un gonflement ou une grosseur dans le sein qui reste non résolu pendant plusieurs semaines au cours de la période menant au décès est un signe significatif d'un cancer potentiel du sein. Cela se produit généralement chez les femmes d’âge moyen ou âgées. Bien qu'il s'agisse d'un signe interne et qu'il ne soit donc pas directement observé par les personnes interrogées, cette condition peut avoir été portée à l'attention des soignantes de la famille et peut déclencher une tentative de recours à des soins de santé. Dans certains cas, la croissance du sein peut traverser la peau et provoquer un ulcère qui ne guérit pas. Il s’agit d’un signe ouvertement observable, généralement porté à l’attention des soignants, pour nettoyer et panser la plaie. Il existe donc une forte probabilité de rappel lorsqu'il est présent. En outre, il se peut qu'il y ait eu une tentative de recours à des soins de santé, avec la possibilité d'obtenir un avis médical quant au diagnostic. Clarifiez ces aspects et enregistrez tous les détails dans les sections pertinentes du questionnaire.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10296: {
        label: "(Id10296) A-t-elle déjà eu ses règles ou ses règles ?",
        hint: "Si la réponse est « NON », veuillez vous assurer qu’il n’y avait aucune chance que la défunte ait été enceinte récemment.",
        guidance:
          "Cette question vise à confirmer si la personne décédée avait atteint la puberté/ménarche, avec des cycles mensuels de saignements utérins. Si « oui », la cause de son décès pourrait potentiellement être liée à des conditions liées à la grossesse. Des investigations ou des éclaircissements peuvent être nécessaires si le défunt était très jeune (par exemple 12 à 15 ans) ; sinon, dans la plupart des cas, cette question serait simple avec une réponse simple. Si la réponse est « NON », veuillez vous assurer qu’il n’y avait aucune chance que la défunte ait été enceinte récemment. Si « NON/NSP/Réf », passez à Id10301.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10299: {
        label: "(Id10299) Ses règles se sont-elles arrêtées naturellement à cause de la ménopause ?",
        guidance:
          "Cette question est pertinente pour les femmes qui peuvent avoir connu la ménopause naturelle ou l'arrêt des cycles mensuels réguliers de saignements qui se produisent à la fin de l'âge adulte. Il peut y avoir un terme ou une expression en langue locale pour la ménopause, qui doit être utilisé dans la version traduite du questionnaire, et utiliser le terme local pour approfondir. Si la personne décédée est ménopausée, on pourrait exclure la possibilité de décès liés à la grossesse. Si la réponse est « OUI », passez à Id10300. Si « NON/NSP/Réf », passez à Id10301.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10300: {
        label: "(Id10300) A-t-elle eu des saignements vaginaux après l'arrêt des règles ?",
        guidance:
          "Cette question est pertinente pour les femmes ménopausées. Un intervalle de plusieurs mois, voire années après la ménopause, suivi de l'apparition de saignements vaginaux, est fortement évocateur d'un cancer des voies génitales. Assurez-vous qu'il y a un intervalle clair entre la ménopause et la récidive des saignements vaginaux. Si possible, enregistrez les détails fournis par le répondant dans la section narrative du questionnaire. Cette question n'a pas besoin d'être posée aux femmes non ménopausées",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10301: {
        label:
          "(Id10301) Y a-t-il eu des saignements vaginaux excessifs au cours de la semaine précédant le décès ?",
        hint: "La quantité excessive de sang est importante.",
        guidance:
          "Des saignements vaginaux excessifs au cours de la semaine précédant le décès pourraient être liés à la maladie en phase terminale. Ce saignement excessif peut être lié à la grossesse, au travail, à l'accouchement ou non. Quoi qu’il en soit, enregistrez ici la réponse aux saignements vaginaux au cours de la semaine précédant le décès. Un certain degré de saignement se produit naturellement pendant et immédiatement après l'accouchement, et est généralement contrôlé par des procédures standard par les accoucheuses. Les saignements difficiles à contrôler et continus et prolongés sur plusieurs heures pourraient être considérés comme excessifs et signalés comme tels par l'équipe d'accoucheuses aux membres du ménage, et cela pourrait potentiellement être rappelé, en particulier lorsqu'ils surviennent dans la semaine qui suit immédiatement l'accouchement. En revanche, il peut y avoir des saignements excessifs non associés à la grossesse ou à l’accouchement, à tout âge. En ce qui concerne les saignements menstruels, ils peuvent être considérés comme excessifs lorsqu'une femme saigne pendant plus de 7 jours (1 semaine) ou utilise plus de six serviettes hygiéniques bien imbibées par jour. Clarifiez le terme « excessif » ainsi que la survenance dans les quelques jours précédant immédiatement le décès, et notez la réponse en conséquence.\nREMARQUE :\n● Pour les femmes qui n'ont jamais eu leurs règles (c'est-à-dire Id10296=NON), passez à Id10305. Les questions Id10305 à 10308 sont posées pour confirmer qu'il ne s'agit pas d'un décès maternel et éviter les réponses faussement négatives à Id10296.\n● Pour les femmes âgées de 50 ans ou plus déclarées ménopausées (c'est-à-dire Id10299=OUI), après Id10301, passez à Id10340.\n● Pour les femmes âgées de 40 à 50 ans déclarées ménopausées (c'est-à-dire Id10299=OUI), passez à Id10305. Les questions Id10305 à 10308 sont posées pour confirmer qu'il ne s'agit pas d'un décès maternel et éviter les réponses faussement positives à Id10299.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10302: {
        label: "(Id10302) Au moment de son décès, ses règles étaient-elles en retard ?",
        guidance:
          "Cette question vise à déterminer si la personne décédée était connue pour être enceinte ou aurait pu l'être au moment de son décès. Dans certains cas de grossesse précoce, la période de retard peut ne pas être connue même des parentes proches. Cependant, dans les grossesses plus avancées, au-delà de 2 à 3 mois, cela est généralement connu des membres du foyer. Sondez attentivement et enregistrez la réponse. Si l’on savait que la femme était enceinte au moment de son décès ou si elle est décédée pendant le travail ou l’accouchement, la réponse à la question doit être « OUI ». Si « NON/NSP/Réf », passez à Id10305.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10303: {
        label: "(Id10303) Depuis combien de semaines ses règles étaient-elles en retard ?",
        hint: "Si le répondant n'est pas en mesure de répondre, posez la question : La période est-elle en retard depuis moins de 4 semaines (l'enquêteur doit saisir 3 semaines) ou depuis au moins 4 semaines (l'enquêteur doit saisir 5 semaines) ?. Moins d'une semaine = 0. 7 jours = 1 semaine. Entrez « 99 » pour « ne sait pas ». Entrez « 88 » pour « refuser ».",
        guidance:
          "Cette question clarifie la durée probable de la grossesse, si elle est connue. Aux premiers stades, le retard peut ne pas confirmer la grossesse, à moins que le ménage ne connaisse le résultat d'un test de grossesse spécifique, le cas échéant. Néanmoins, toute information de cette nature pourrait aider à diagnostiquer la probabilité que le décès soit lié à une grossesse précoce. Moins d'une semaine = 0 semaine. Utilisez 7 jours = 1 semaine pour déterminer le nombre de semaines. Une réponse valide est entre 0 et 99. Si la réponse a duré plus de 98 semaines, confirmez la réponse et inscrivez « 98 ». Si le répondant ne peut pas se rappeler exactement depuis combien de temps la période était en retard, demandez-lui et enregistrez-le en fonction de ce qui est médicalement pertinent à saisir. Si le délai était en retard :\n● moins de 4 semaines - l'enquêteur doit saisir 3 semaines ;\n● au moins 4 semaines – l'intervieweur doit saisir 5 semaines. Pour ne sait pas, saisissez « 99 ». Pour refusé, inscrivez « 88 ».",
        constraintMessage: "Veuillez saisir une valeur comprise entre 0 et 99."
      },
      Id10305: {
        label: "(Id10305) Était-elle enceinte et n'était pas encore en travail au moment du décès ?",
        hint: "Une réponse « Oui » à cette question signifie qu'un fœtus ou un bébé est resté dans le corps de la mère après sa mort. Si elle était déjà en travail ou en train d'avorter, veuillez répondre « NON » à Id10305.",
        guidance:
          "Cette question vise à déterminer si la défunte était enceinte au moment de son décès. Autrement dit, une réponse « OUI » à cette question signifie qu’un fœtus ou un bébé est resté dans le corps de la mère après sa mort. Si elle était déjà en travail ou en train d'avorter, veuillez répondre « NON » à cette question. La connaissance d’une grossesse peut être évidente après environ 3 mois. Cependant, plus tôt, lorsque les règles sont en retard de quelques semaines seulement, seuls les membres de la famille immédiate, comme le mari ou la sœur, peuvent en être informés. La confirmation de la grossesse est une contribution diagnostique importante à la cause du décès. Notez que la question sera posée même après une réponse « NON » à la question Id10296 (A-t-elle déjà eu ses règles ou ses règles). Il s'agit de garantir que toutes les femmes enceintes soient capturées, comme dans le cas d'une jeune femme tombant enceinte avant d'avoir observé ses premières règles, ou dans le cas d'une réponse faussement négative à Id10296. Si la réponse à la question Id10305 est « OUI », passez à la question Id10304. Si l'enquêtée déclare qu'elle n'était pas enceinte ou que le décès est survenu pendant ou après l'accouchement alors qu'elle ne portait déjà pas le fœtus/bébé, enregistrez la réponse à cette question comme « NON » ; et passez à la question suivante. Si la réponse à Id10305 est « NSP/Réf », passez à la question suivante.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10312: {
        label: "(Id10312) Est-elle décédée pendant le travail ou l'accouchement ?",
        hint: "Une réponse « Oui » à cette question exclut les femmes qui meurent lors d'un avortement ou d'une fausse couche.",
        guidance:
          "Cette question vise à confirmer si le décès est survenu pendant le processus d'accouchement, c'est-à-dire si le décès est survenu après le début des douleurs de l'accouchement et si certains signes de progression du travail ont été observés. Cependant, le décès est survenu avant la fin de l'accouchement. L'accouchement complet est défini comme l'accouchement du bébé. Les cas dans lesquels le décès survient suite à un accouchement placentaire incomplet doivent être considérés comme post-partum. Cette détermination peut être parfois difficile pour les répondants qui ne sont pas familiers avec le processus de travail – le choix du répondant est donc important – lorsque cela est possible, une parente proche doit être choisie comme répondante, même si elle n'est pas membre du ménage. Une réponse « OUI » à cette question exclut les femmes qui meurent lors d'un avortement ou d'une fausse couche. Si la réponse est « OUI », passez à Id10309. Si la réponse est « NON/NSP/Réf », passez au Id10313.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10313: {
        label: "(Id10313) Est-elle morte après avoir accouché ?",
        hint: "A noter qu'un décès maternel est pertinent jusqu'à 1 an après l'accouchement.",
        guidance:
          "La plupart des décès maternels surviennent juste après l'accouchement. Cette question vise à confirmer que le décès est survenu après l'accouchement, et non pendant la grossesse ou le travail (période d'accouchement). Notez qu'un décès maternel est pertinent jusqu'à 1 an après l'accouchement. Si « OUI », passez à Id10314. Si « NON/NSP/Réf », passez à Id10334.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10314: {
        label: "(Id10314) Est-elle décédée dans les 24 heures suivant l'accouchement ?",
        guidance:
          "Cette question est utilisée pour connaître le délai entre l'accouchement et le décès. On sait que plusieurs causes maternelles entraînent la mort dans le premier jour suivant l'accouchement, notamment les saignements qui surviennent après l'accouchement du bébé. Si « OUI », passez à Id10309. Si « NON/NSP/Réf », passez à la question suivante.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10306: {
        label: "(Id10306) Est-elle décédée dans les 6 semaines après l'accouchement ?",
        guidance:
          "Cette question est utilisée pour connaître le délai entre l'accouchement et le décès. Une réponse « OUI » à cette question signifie qu'un fœtus ou un bébé a accouché (par voie vaginale ou par césarienne) dans les 6 semaines précédant son décès - que l'interruption de grossesse soit due à la survenue d'un terme, d'un décès imminent ou d'une mortinaissance. Clarifiez la relation temporelle entre la fin de la grossesse et le décès et enregistrez la réponse en conséquence. Si la réponse est « OUI », passez à Id10309. Si « NON/NSP/Réf », passez à la question suivante.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10334: {
        label:
          "(Id10334) A-t-elle eu une grossesse qui s'est terminée par un avortement ou une fausse couche dans les 6 semaines précédant son décès ?",
        guidance:
          "Cette question vise spécifiquement à déterminer si le décès était associé à un avortement. Le mot « spontané » implique que l'avortement s'est produit naturellement (de lui-même) ; et le mot « provoqué » signifie que l’avortement a été spécifiquement provoqué par une action extérieure. Aux fins de cet entretien, la fausse couche est définie au sens large comme un échec naturel et spontané de la grossesse, généralement au cours du premier ou du deuxième trimestre. L'avortement spontané peut se chevaucher quelque peu avec une fausse couche, mais englobe généralement les avortements ultérieurs au deuxième trimestre. La plupart des pays aux ressources limitées utilisent un délai de 28 semaines pour déterminer la mortinatalité. Cela signifie que ceux qui sont morts avant 28 semaines in utero sont des morts fœtales intra-utérines et, lorsqu'ils sont expulsés, des avortements. Un avortement provoqué fait référence à une intervention utilisée pour interrompre la grossesse. Si nécessaire, clarifiez les termes fausse couche et avortement. Une réponse « OUI » à cette question signifie qu'un fœtus ou un bébé a été perdu, retiré ou accouché (par voie vaginale ou par césarienne) dans les 6 semaines précédant son décès. Si « NON/NSP/Réf », alors passez à la question Id10337.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10333: {
        label: "(Id10333) A-t-elle tenté d'interrompre la grossesse ?",
        guidance:
          "Cette question vise à déterminer si la personne décédée avait tenté de mettre fin à sa grossesse pour une raison quelconque, et si elle avait recours à des soins médicaux ou à d'autres moyens. Dans certains cas, de telles tentatives non professionnelles peuvent avoir des conséquences néfastes, notamment des saignements excessifs ou une infection. Les membres de la famille proche peuvent être conscients de ces intentions ou tentatives, mais peuvent ne pas réagir ouvertement en raison des circonstances sociales et de la stigmatisation. Par conséquent, posez la question avec soin et expliquez le sens de « tentative de résiliation » ; selon les besoins. S’il existe des termes culturellement acceptables qui pourraient être utilisés pour rechercher cette réponse, ils devraient être utilisés. REMARQUE : Id10334 et Id10336 ne doivent PAS être demandés s'il y a eu une naissance vivante (c'est-à-dire Id10316 = « OUI »).",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10308: {
        label:
          "(Id10308) Est-elle décédée moins d'un an après l'accouchement, l'avortement ou la fausse couche ?",
        guidance:
          "Cette question vise à identifier les décès survenus après 6 semaines mais dans l'année suivant l'accouchement ou l'interruption de grossesse. La limite d’un an est considérée comme la limite extérieure pour la définition des décès maternels tardifs. Si la réponse est « OUI », passez à Id10309. Si « NON/NSP/Réf », passez à Id10310.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10310: {
        label:
          "[Veuillez confirmer qu'au cours des 12 mois précédant son décès, la femme n'était pas enceinte, elle n'a pas accouché et elle n'a pas non plus eu d'avortement ou de fausse couche.]",
        hint: "Remarque : S'il s'agit d'un décès maternel, veuillez revenir en arrière pour indiquer les circonstances correctes.",
        guidance:
          "La note ci-dessus apparaît lorsque les réponses à Id10305/Id10312/Id10313/Id10334/Id10308 sont NON/NSP/Réf. Les réponses négatives à toutes ces questions suggèrent que la personne décédée n'était pas enceinte au moment de son décès et que le décès n'était survenu à aucun moment dans l'année suivant un accouchement ou une interruption de grossesse. Dans ce cas, il n’y a absolument aucune possibilité que la cause du décès de la personne décédée soit liée à la grossesse. Ainsi, en cochant la case de cette note (Id10310), nous confirmons que le décès n'est en aucun cas associé à une grossesse et excluons ainsi toute cause maternelle. Il n’est donc pas nécessaire de poser d’autres questions liées aux causes maternelles. S'il existe une certaine incertitude quant à savoir si la cause du décès pourrait être une cause maternelle ou liée à la grossesse, revenez au point Id10305 ; et répétez les questions, pour vérifier si les femmes auraient pu être enceintes ou récemment accouchées avant leur décès, et suivez à nouveau le même processus.",
        choices: {
          yes: "Je confirme qu'il ne s'agissait pas d'un décès maternel"
        }
      },
      Id10304: {
        label:
          "(Id10304) A-t-elle eu des douleurs abdominales aiguës au cours des 3 premiers mois de grossesse ?",
        guidance:
          "L'abdomen fait partie du corps situé au-dessous de la cage thoracique et au-dessus des os pelviens. Il est important de savoir si la défunte s'est plainte de douleurs abdominales au cours des 3 premiers mois de la grossesse et quelle est l'intensité de ces douleurs. Certaines causes maternelles, y compris la grossesse extra-utérine, sont associées à des douleurs abdominales aiguës et intenses, et si elles sont vraiment intenses, ces douleurs sont généralement portées à la connaissance des proches. Une telle douleur aiguë peut être ressentie au cours des 3 premiers mois de la grossesse, même si la personne décédée ou ses proches ne sont pas au courant de la grossesse. Si la réponse est « NON/NSP/Réf », passez à Id10309.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10304_a: {
        label:
          "(Id10304_a) Est-ce qu'elle s'est évanouie lorsqu'elle a ressenti une douleur abdominale aiguë ?",
        guidance:
          "Si une femme a un embryon (au début de la grossesse) fixé à l'extérieur de son ventre, il se rompra et entraînera des saignements dans l'estomac, ce qui provoquera de graves douleurs abdominales accompagnées de vertiges extrêmes ou d'évanouissements. Cette question porte sur les évanouissements et non sur les étourdissements fréquents pendant la grossesse.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10309: {
        label: "(Id10309) Pendant combien de mois était-elle enceinte ?",
        hint: "Si l'enquêtée n'est pas en mesure de répondre, posez la question : Était-elle enceinte depuis moins de 6 mois (l'enquêteur doit saisir 5 mois) ou depuis plus de 6 mois (l'enquêteur doit saisir 7 mois) ?.  Pour je ne sais pas, entrez « 99 ». Pour refusé, entrez « 88 ».",
        guidance:
          "Cette question vise à enregistrer la durée réelle de la grossesse en mois, au moment du décès. Écrivez le nombre de mois de grossesse révolus, par ex. 7,5 mois s'écrit 7 mois. Une réponse valide est comprise entre 0 et 11. Si la réponse est supérieure à 11 mois, confirmez la réponse et inscrivez « 11 ». Si le répondant ne se souvient pas exactement de la durée, invitez-le et enregistrez-le en fonction de ce qui est médicalement pertinent à saisir. Si la grossesse a duré :\n● depuis moins de 6 mois - l'enquêteur doit saisir 5 mois ;\n● ou plus de 6 mois – l'enquêteur doit saisir 7 mois.\nPour je ne sais pas, entrez « 99 ». Pour refusé, inscrivez « 88 ».",
        constraintMessage:
          "Veuillez saisir une valeur comprise entre 0 et 11 mois.  Si la réponse est supérieure à 11, confirmez la réponse et saisissez 11."
      },
      Id10317: {
        label: "(Id10317) De combien de bébés était-elle enceinte ?",
        guidance:
          "Certaines causes maternelles sont plus susceptibles de survenir en association avec une grossesse gémellaire. Précisez si elle était enceinte d'un singleton, de jumeaux, de triplés ou plus et enregistrez la réponse en conséquence.",
        choices: {
          singleton: "singleton",
          twins: "jumeaux",
          triplets: "triplés ou plus",
          dk: "Je ne sais pas",
          ref: "A refusé de répondre"
        }
      },
      Id10321: {
        label: "(Id10321) Pendant la grossesse, a-t-elle souffert d'hypertension artérielle ?",
        guidance:
          "De nos jours, de nombreuses femmes enceintes font vérifier leur tension artérielle dans le cadre des soins prénatals, et la présence d'hypertension artérielle, si elle est détectée, est notifiée aux patientes. Demandez si la personne décédée a reçu un diagnostic d'hypertension artérielle lors d'une consultation de soins prénatals et enregistrez la réponse. Il est important de déterminer si la femme souffre d’hypertension artérielle, car si la pression est élevée, cela peut être lié à une maladie cardiaque ou à un accident vasculaire cérébral.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10322_a: {
        label: "(Id10322_a) A-t-elle eu des pertes vaginales nauséabondes pendant la grossesse ?",
        guidance:
          "Des pertes vaginales nauséabondes indiquent une infection du canal génital et peuvent être remarquées pendant la grossesse. Des signes concomitants de douleur dans le bas-ventre et de fièvre peuvent être associés. Sondez attentivement et enregistrez les réponses.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10325: {
        label: "(Id10325) Des saignements sont-ils survenus pendant qu'elle était enceinte ?",
        guidance:
          "Cette question porte sur les saignements du canal génital pendant la durée de la grossesse AVANT le début des douleurs à l'accouchement ou l'accouchement. Pendant la grossesse, la présence et le moment du saignement indiquent des conditions spécifiques. A noter que le saignement survient alors que la défunte était encore enceinte. En cas de saignement, les questions suivantes tenteront de clarifier des détails plus spécifiques sur le moment du saignement pendant la grossesse. Si « NON/NSP/Réf », passez à Id10323. REMARQUE : Les questions Id10327, Id10323 et Id10324 ne sont pertinentes qu'au cours du troisième trimestre de la grossesse (et/ou après l'accouchement pour Id10323-10324). Il est important de comparer les réponses à ces questions avec la durée de la grossesse (Id10309). Dans la version électronique de l'instrument, les questions seront ignorées si la durée de la grossesse est inférieure à 6 mois. En cas de réponse « NSP/Réf » à Id10309, les questions Id10327, Id10323 et Id10324 doivent être posées car le manque de connaissance exacte de la durée de la grossesse n'est pas rare et ces questions peuvent avoir des réponses positives pertinentes et utiles.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10327: {
        label:
          "(Id10327) Y a-t-il eu des saignements vaginaux au cours des 3 derniers mois de la grossesse mais avant le début du travail ?",
        hint: "Les 3 derniers mois de grossesse font référence aux 7e-9e mois d’une grossesse à terme.",
        guidance:
          "Des saignements excessifs à l’approche du terme sont généralement associés à des troubles du placenta. Confirmez que ce saignement s'est produit AVANT l'apparition de TOUTES douleurs à l'accouchement ; et enregistrez la réponse en conséquence. Les 3 derniers mois de grossesse font référence aux 7e-9e mois d’une grossesse à terme.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10323: {
        label:
          "(Id10323) A-t-elle souffert de convulsions au cours des 3 derniers mois de grossesse et/ou après l'accouchement ?",
        hint: "Les 3 derniers mois de grossesse font référence aux 7e-9e mois d’une grossesse à terme.",
        guidance:
          "Les convulsions sont des contractions rapides ou des mouvements saccadés de parties des membres ou parfois de membres entiers qui s'atténuent fréquemment avec la perte de conscience. Le terme courant pour désigner les convulsions est crises, et il existe souvent un terme local pour de tels mouvements. Les convulsions sont un signe grave et sont généralement mémorisées par les observateurs et donc signalées par les répondants. Confirmez soigneusement la définition des convulsions, si nécessaire par une démonstration, et enregistrez la réponse en conséquence. Les convulsions peuvent indiquer une éclampsie (toxémie de la grossesse), une épilepsie ou plusieurs autres problèmes médicaux graves. Le moment de l’apparition de ces convulsions est important pour distinguer la maladie. Notez que les 3 derniers mois de grossesse font référence aux 7e-9e mois d’une grossesse à terme.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10324: {
        label:
          "(Id10324) Avait-elle une vision floue au cours des 3 derniers mois de grossesse et/ou après l'accouchement ?",
        hint: "Les 3 derniers mois de grossesse font référence aux 7e-9e mois d’une grossesse à terme.",
        guidance:
          "Une vision floue signifie une vision sombre sous une lumière normale. Cela peut être accompagné ou non de convulsions. La vision floue est un symptôme subjectif et ne peut pas être rapporté par la patiente à ses proches. Expliquez la signification d’une vision floue et enregistrez la réponse en conséquence. Les 3 derniers mois de grossesse font référence aux 7e-9e mois d’une grossesse à terme. Pour les femmes décédées pendant la grossesse (c'est-à-dire Id10305=OUI), passez à Id10319. Pour les femmes qui ont eu un avortement ou une fausse couche (c'est-à-dire Id10334=OUI ; (Id10313=NON et Id10308=OUI)), passez à Id10329_b. Pour les femmes décédées pendant ou après l'accouchement (c'est-à-dire Id10312=OUI ; Id10313=OUI ; Id10313=OUI et Id10308=OUI), passez à Id10328.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10328: {
        label: "(Id10328) A-t-elle eu des saignements excessifs pendant le travail ou l'accouchement ?",
        hint: "Ici, c'est la quantité excessive de sang PENDANT l'accouchement que nous demandons.",
        guidance:
          "Cette question fait référence aux saignements pendant le processus d'accouchement APRÈS le début des douleurs de l'accouchement mais avant l'accouchement complet. Des saignements excessifs pendant le travail et l'accouchement peuvent être dus à une blessure à l'utérus (utilisez le terme local) ou au canal génital. Confirmez le moment du saignement comme ayant commencé APRÈS l’apparition des douleurs à l’accouchement et pendant le travail avant l’accouchement, et enregistrez la réponse en conséquence. Pour les femmes décédées pendant le travail ou l'accouchement (c'est-à-dire Id10312=OUI), passez à Id10331. Pour les femmes décédées après l'accouchement (c'est-à-dire Id10313=OUI et Id10308=OUI), passez à Id10329_a.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10329_a: {
        label: "(Id10329_a) A-t-elle eu des saignements excessifs après l'accouchement ?",
        hint: "Ici, c'est la quantité excessive de sang APRÈS la naissance que nous demandons.",
        guidance:
          "Certains saignements sont normaux immédiatement (jusqu'à 1 à 2 heures) après l'accouchement. Cependant, les saignements excessifs (supérieurs à l'attente normale allant jusqu'à 500 ml en plus du placenta (après l'accouchement) entraînant la mort dans les 1 à 2 jours suivant l'accouchement sont généralement clairement rappelés et signalés comme tels par les familles interrogées. Dans de tels cas, même si l'accouchement avait lieu à domicile, le saignement excessif serait signalé par la sage-femme traitante et aurait conduit à une tentative de recours à des soins de santé, qui seraient également rappelés. Utilisez ces sondes pour confirmer un saignement excessif. Pour les femmes décédées après l'accouchement. (c'est-à-dire Id10313=OUI ; Id10313=OUI et Id10308=OUI), passez à Id10322_b.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10329_b: {
        label:
          "(Id10329_b) A-t-elle eu des saignements excessifs pendant ou après un avortement ou une fausse couche ?",
        hint: "Ici, la quantité excessive de sang APRÈS un avortement ou une fausse couche est ce que nous demandons",
        guidance:
          "Certains saignements sont normaux immédiatement (jusqu'à 1 à 2 heures) après l'avortement ou l'avortement spontané (fausse couche). Cependant, les saignements excessifs (au-dessus d'environ 300 ml ou un changement excessif de serviettes/vêtements utilisés) entraînant la mort dans les 1 à 2 jours suivant l'avortement/la fausse couche sont généralement clairement rappelés et signalés comme tels par les familles interrogées. Dans de tels cas, même si le décès était survenu à domicile, le saignement excessif serait signalé par une sage-femme traitante et aurait conduit à une tentative de recours à des soins de santé, qui seraient également rappelés. Utilisez ces sondes pour confirmer un saignement excessif.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10322_b: {
        label:
          "(Id10322_b) A-t-elle eu des pertes vaginales nauséabondes après l'accouchement/l'avortement ?",
        guidance:
          "Des pertes vaginales nauséabondes indiquent une infection du canal génital et peuvent être remarquées après un accouchement ou un avortement. Des signes concomitants de douleur dans le bas-ventre et de fièvre peuvent être associés. Sondez attentivement et enregistrez les réponses. Pour les femmes qui ont eu un avortement ou une fausse couche (c'est-à-dire Id10334=OUI ; (Id10313=NON et Id10308=OUI)), passez à Id10319. Sinon, passez au Id10331. REMARQUE : Les questions Id10331 à Id10337 suivantes ne concernent que les femmes décédées pendant ou après l'accouchement (c'est-à-dire Id10312=OUI ; Id10313=OUI ; Id10313=OUI et Id10308=OUI).",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10331: {
        label: "(Id10331) A-t-elle accouché ou tenté d'accoucher d'un bébé dans une position anormale ?",
        hint: "Demandez à la personne interrogée quelle est sa compréhension de ce qu'est un bébé anormalement positionné ; Si cela n'est pas clair ou est faux, expliquez qu'il s'agit des bébés dont la première partie du corps sortant du vagin n'est pas la tête.",
        guidance:
          "Là encore, la position du bébé est connue de la sage-femme traitante, mais elle est généralement communiquée aux membres de la famille. Renseignez-vous soigneusement sur la compréhension qu’a la personne interrogée de ce qu’est un bébé dans une position anormale. Si cela n’est pas clair ou est erroné, expliquez qu’il s’agit d’un bébé dont la première partie du corps sortant du vagin n’est pas la tête. Enregistrez tous les détails dans la section narrative du questionnaire.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10332: {
        label: "(Id10332) Pendant combien d'heures le travail a-t-il duré ?",
        hint: "Si l'enquêtée est incapable de répondre, posez la question : Est-ce qu'elle était en travail depuis moins de 24 heures (l'intervieweur doit saisir 23 heures) ou pendant plus de 24 heures (l'intervieweur doit saisir 25 heures). Moins de 60 minutes = 0 heure. 1 jour = 24 heures. Entrez « 99 » pour « ne sait pas ». Entrez « 88 » pour « refuser ».",
        guidance:
          "Le temps écoulé entre le début des douleurs à l’accouchement et l’accouchement est un indicateur important de la cause probable du décès. Lors des premières grossesses, cela se produira probablement dans un délai de 6 à 12 heures (8 heures en moyenne) ; et lors des grossesses ultérieures, elle est plus courte. Un travail prolongé de plus de 12 heures restera probablement dans les mémoires des proches. La réponse pourrait être donnée dans une autre unité, mais pour la saisie des données, les heures d'utilisation. Moins de 60 minutes = 0 heure. 1 jour = 24 heures. Entrez \"99\" pour je ne sais pas. Entrez « 88 » pour avoir refusé de répondre. Une réponse valide est comprise entre 0 et 99. Si la réponse a duré plus de 98 heures, confirmez la réponse et entrez « 98 ». Si la réponse à la durée est de 88 heures, inscrivez plutôt « 87 » afin que la réponse ne soit pas automatiquement codée comme refus de réponse. Si le répondant ne se souvient pas exactement de la durée, invitez-le et enregistrez-le en fonction de ce qui est médicalement pertinent à saisir. Si le travail a duré :\n● pendant moins de 24 heures - l'enquêteur doit saisir 23 heures ; \n● pendant plus de 24 heures – l'enquêteur doit saisir 25 heures.",
        constraintMessage:
          "Veuillez saisir une valeur comprise entre 0 et 99. Si la réponse a été supérieure à 98 heures, confirmez la réponse et saisissez 98."
      },
      Id10342: {
        label: "(Id10342) L'accouchement a-t-il été normal par voie vaginale, sans forceps ni aspirateur ?",
        guidance:
          "Un accouchement vaginal normal est un accouchement dans lequel la tête du bébé est accouchée en premier ; et il n'y a aucun soutien ou assistance au processus par l'utilisation d'instruments. Les accouchements instrumentaux, au moyen de forceps ou d'aspirateurs, sont effectués uniquement dans les établissements de santé, et les membres de la famille sont généralement informés si cela a lieu. Confirmez le mode de livraison et enregistrez la réponse en conséquence. Si la réponse est « OUI », passez à Id10330. Si la réponse est « NON/NSP/Réf », passez à la question suivante.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10343: {
        label: "(Id10343) L'accouchement s'est-il déroulé par voie vaginale, avec forceps ou aspiration ?",
        guidance:
          "Si des instruments ont été utilisés pour faciliter l'accouchement, enregistrez « OUI » ici et passez à Id10330. Ces instruments (forceps ou aspirateur) peuvent être placés sur la tête du bébé ou dans certains cas utilisés pour faciliter un accouchement par le siège (forceps). Si la réponse est « NON/NSP/Réf », passez à la question suivante.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10344: {
        label: "(Id10344) L'accouchement a-t-il eu lieu par césarienne ?",
        guidance:
          "Les accouchements difficiles et les grossesses chez les femmes souffrant d'autres problèmes médicaux sont souvent gérés en procédant à un accouchement opératoire appelé césarienne. Encore une fois, les membres de la famille sauraient très bien si une telle opération avait été effectuée pour accoucher du bébé et seraient signalés par l'enquêtée.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10330: {
        label: "(Id10330) Le placenta a-t-il été complètement libéré ?",
        guidance:
          "Le terme placenta fait référence au matériau livré attaché à l’extrémité interne du cordon ombilical. On l’appelle communément après l’accouchement, et il existe généralement un terme local pour cela. Le placenta est généralement livré intact (c'est-à-dire en un seul morceau, sans cassures, déchirures ou lacérations). Il est connu que les sages-femmes examinent le placenta avant de le rejeter, notamment en cas de saignement. Cependant, cette connaissance peut ou non avoir été communiquée aux proches, alors clarifiez ces détails avec le répondant. Il peut y avoir un terme local pour décrire le placenta. Assurez-vous que le terme local est inclus dans la version traduite du questionnaire et utilisez le terme local pour approfondir.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10337: {
        label: "(Id10337) Où a-t-elle accouché ?",
        guidance:
          "Demandez au répondant quel est le lieu où la livraison a eu lieu et enregistrez la réponse en conséquence.",
        choices: {
          hospital: "Hôpital",
          other_health_facility: "autre établissement de santé",
          home: "à domicile",
          on_route_to_hospital_or_facility: "en route vers l'hôpital",
          other: "Autres",
          DK: "Ne sait pas",
          Ref: "Refus de repondre"
        }
      },
      Id10319: {
        label:
          "(Id10319) Combien de naissances, y compris les mortinaissances, a-t-elle/la mère ont-elles eu avant cette grossesse ?",
        hint: "Pour je ne sais pas, entrez « 99 ». Pour refusé, entrez « 88 ».",
        guidance:
          "Demandez et enregistrez les antécédents obstétricaux avant cette naissance. A noter que les naissances n'incluent pas les avortements (spontanés ou provoqués) et les fausses couches survenues au cours des 6 premiers mois de grossesse. Les naissances multiples doivent être comptées comme des événements distincts. Par exemple, donner naissance à des jumeaux équivaut à 2 naissances. Une réponse valide est comprise entre 0 et 20. Si la réponse est supérieure à 20 naissances, confirmez la réponse et inscrivez « 20 ». Pour je ne sais pas, entrez « 99 ». Pour refusé, inscrivez « 88 ». Si la réponse à cette question est \"ZÉRO (0)\", c'est-à-dire il s'agit du premier accouchement (y compris la mortinatalité) et la femme est décédée pendant la grossesse (c'est-à-dire Id10305=OUI) - puis passez à Id10411. Sinon, passez à Id10340. Si la réponse est « UN ou tout nombre supérieur à UN », passez à la question suivante.",
        constraintMessage:
          "Veuillez saisir une valeur comprise entre 0 et 20. Si la réponse est supérieure à 20, confirmez la réponse et saisissez 20."
      },
      Id10320: {
        label: "(Id10320) Avait-elle déjà eu une césarienne ?",
        guidance:
          "Demandez et notez si l'une des naissances d'enfants a eu lieu par le biais d'opérations. Les antécédents de césariennes antérieures augmentent le risque de certaines causes de décès maternel. Certaines personnes interrogées ne connaissent peut-être pas le terme césarienne, vous pouvez donc également poser des questions sur un accouchement abdominal chirurgical ou opératoire.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10340: {
        label: "(Id10340) A-t-elle subi une opération pour retirer son utérus peu avant son décès ?",
        hint: "La question est pertinente pour les cas de travail dystocique et de rupture de l'utérus.",
        guidance:
          "Dans certains cas, le travail peut être prolongé, ce qui peut être dû à une obstruction de l'accouchement, entraînant une déchirure de l'utérus. Ceci est résolu par une opération d’urgence au cours de laquelle l’utérus déchiré est soit réparé, soit retiré. L’utérus peut également être retiré si la femme saigne abondamment et que le saignement ne peut être stabilisé d’une autre manière. Cependant, malgré cette action, la mère se trouve parfois déjà dans un état critique et la mort peut survenir même après l'opération. Bien que cela soit rare, il est connu que les proches se souviennent de tels événements, alors clarifiez si nécessaire et enregistrez la réponse en conséquence. Les femmes ménopausées peuvent se faire retirer l'utérus en raison d'un cancer de l'appareil reproducteur.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10354: {
        label: "(Id10354) L'enfant faisait-il partie d'une naissance multiple ?",
        hint: "Cette question ne doit être posée que si l'enfant avait moins d'un an au moment de son décès. Si deux enfants ou plus naissent en même temps, cela est compté comme une naissance multiple, même si un ou plusieurs des bébés sont morts-nés.",
        guidance:
          "Il est important de le savoir, car les bébés issus de naissances multiples comportent des risques supplémentaires dus à certaines causes. Si deux enfants ou plus naissent en même temps, cela est compté comme naissances multiples même si un ou plusieurs des bébés sont morts-nés. Ne demandez que les défunts qui étaient",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10366_check: {
        label: "la carte de santé pour enfants est-elle disponible ?",
        choices: {
          yes: "Oui",
          no: "Non"
        }
      },
      n10366: {
        label:
          "Entrez le poids à la naissance de la carte. Enregistrez le poids en grammes sur 4 chiffres. Pour la saisie des données, convertissez-les en grammes si nécessaire. 1 kilogramme = 1 000 grammes."
      },
      Id10366: {
        label: "(Id10366) Quel était le poids (en grammes) du défunt à la naissance ?",
        guidance:
          "Demandez si la carte de santé pour enfants est disponible. Si la carte est disponible et que le poids à la naissance est enregistré, saisissez le poids à la naissance figurant sur la carte. Enregistrez le poids en grammes sur quatre chiffres. Les répondants peuvent donner la réponse en kilogrammes. Pour la saisie des données, convertissez-les en grammes. 1 kilogramme = 1 000 grammes. Si la carte n'est pas disponible et/ou le poids à la naissance n'est pas disponible, allez à Id10363. Si le poids est enregistré, passez à Id10367.",
        constraintMessage: "Veuillez saisir une valeur comprise entre 0 et 9999"
      },
      Id10363: {
        label:
          "(Id10363) À la naissance, le bébé était-il plus petit que d'habitude (pesant moins de 2,5 kg) ?",
        hint: "Montrer des photos si disponibles. Cette question ne doit être posée que si l'enfant avait moins d'un an au moment de son décès.",
        guidance:
          "L'insuffisance pondérale à la naissance est un facteur important associé à un risque accru de décès néonatal, notamment dû à des problèmes respiratoires, à des traumatismes à la naissance et à l'hypothermie. Une taille plus petite que d'habitude peut être difficile à expliquer, mais les mères peuvent être en mesure de signaler si le bébé était petit. Si « OUI », passez à Id10367.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10365: {
        label:
          "(Id10365) À la naissance, le bébé était-il plus gros que d'habitude (pesant plus de 4,5 kg) ?",
        hint: "Montrer des photos si disponibles. Cette question ne doit être posée que si l'enfant avait moins d'un an au moment de son décès.",
        guidance:
          "Cette question est à poser uniquement si la réponse à Id10363 était « NON/NSP/Réf ». Les bébés nés plus gros que d'habitude sont associés à des problèmes causés à la mère lors de l'accouchement, mais parfois le nouveau-né présente également des risques accrus de blessures à la naissance, de malformations congénitales et de diabète.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10367: {
        label: "(Id10367) Combien de mois a duré la grossesse avant la naissance de l'enfant ?",
        hint: "Si l'enquêtée n'est pas en mesure de répondre, posez la question : La grossesse a-t-elle duré moins de 8 mois (l'enquêteur doit saisir 7 mois) ; est-ce que cela a duré 8 ou 9 mois (l'enquêteur doit saisir 9 mois) ; ou depuis plus de 9 mois (l'enquêteur doit saisir 10 mois) ? Pour je ne sais pas, entrez « 99 ». Pour refusé, entrez « 88 ».",
        guidance:
          "La durée de la grossesse au moment de l’accouchement est un facteur important qui pourrait aider à déterminer la cause du décès du nouveau-né. L'accouchement à moins de 8 mois de grossesse est associé à des bébés de plus petite taille, qui comportent des risques de problèmes respiratoires, de blessures à la naissance et d'hypothermie (froid au toucher). Enregistrez soigneusement la durée, en demandant à l'enquêtée de compter les mois écoulés depuis la date des dernières règles jusqu'à la date de l'accouchement. Si le répondant donne une réponse en demi-mois (par exemple 6,5 mois) ou en mois et semaines (par exemple 6 mois et 2 semaines), arrondissez à l'inférieur (par exemple saisissez « 6 ») pour saisir les mois complétés. Une réponse valide est comprise entre 0 et 11. Si la réponse est supérieure à 11 mois, confirmez la réponse et inscrivez « 11 ». Si l'enquêtée ne se souvient pas exactement de la durée, demandez-la et enregistrez-la en fonction de ce qui est médicalement pertinent à saisir : si la grossesse a duré moins de 8 mois, l'enquêteur doit saisir 7 mois ; si la grossesse a duré 8 ou 9 mois – l'enquêteur doit saisir 9 mois ; ou si la grossesse a duré plus de 9 mois – l'enquêteur doit saisir 10 mois. Pour je ne sais pas, entrez « 99 ». Pour refusé, inscrivez « 88 ».",
        constraintMessage: "Veuillez saisir une valeur comprise entre 0 et 11 mois."
      },
      Id10369: {
        label: "(Id10369) Y a-t-il eu des complications pendant le travail ou l'accouchement ?",
        guidance:
          "Les complications pendant le travail ou l'accouchement font référence à une fièvre ou une infection, à l'apparition d'une fuite de liquide du canal génital avant l'apparition de la douleur ; ou progression très lente ou obstruction du travail : ou apparition de lésions du canal génital chez la mère ; ou des saignements abondants, entre autres. Demandez attentivement, en donnant ces exemples si nécessaire. Demandez tous les enfants. Si l'enfant a moins d'un an, passez aux questions suivantes. Si l'enfant a 1 an ou plus, passez à Id10418.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10370: {
        label:
          "(Id10370) Une partie du bébé était-elle physiquement anormale au moment de l'accouchement ? (par exemple : partie du corps trop grande ou trop petite, croissance supplémentaire sur le corps) ?",
        guidance:
          "Une forme anormale d'un membre due à une déformation physique ou à toute anomalie physique externe peut entraîner un travail difficile et peut également être associée à d'autres malformations congénitales des organes internes pouvant être à l'origine du décès. Si la réponse est « NON », passez à Id10382. Si « OUI/NSP/Réf », passez aux questions suivantes.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10371: {
        label:
          "(Id10371) Le bébé/l'enfant présentait-il un gonflement ou une anomalie au dos au moment de la naissance ?",
        guidance:
          "Cette question porte spécifiquement sur les anomalies affectant la colonne vertébrale et peuvent apparaître sous la forme d'un gonflement ou d'un défaut (absence de parties, c'est-à-dire d'os ou de tissu) associé au système nerveux. Ces conditions sont très rares, mais seraient rappelées si elles étaient présentes.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10372: {
        label: "(Id10372) Le bébé/enfant avait-il une très grosse tête au moment de la naissance ?",
        guidance:
          "De même, l’apparition d’une très grosse tête est également due à des affections affectant le système nerveux. Encore une fois, cette condition est très rare, mais elle est souvent associée à une naissance vivante et à une survie de quelques semaines ou plus, en particulier avec un traitement. Cette condition est également perceptible et serait rappelée par les répondants, si elle était présente. Nouveau-né : Si « OUI », passez à Id10382. Enfants :Si « OUI », passez au Id10418",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10373: {
        label: "(Id10373) Le bébé/enfant avait-il une très petite tête au moment de la naissance ?",
        guidance:
          "Ceci est généralement associé soit à une mortinatalité, soit à une survie de quelques heures seulement. Cette affection est très rare, et se remarque par une absence d'os du sommet de la tête. Il s’agit d’une question sensible, il faut donc faire très attention à ne pas contrarier la personne interrogée en posant cette question.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10382: {
        label: "(Id10382) Combien d'heures ont duré le travail et l'accouchement ?",
        hint: "Si le répondant est incapable de répondre, posez la question : Le travail a-t-il duré moins de 24 heures (l'enquêteur doit saisir 23 heures) ou plus de 24 heures (l'enquêteur doit saisir 25 heures) ? Si moins d'une heure, entrez 0. Pour ne sait pas, entrez « 99 ». Pour refusé, entrez « 88 ».",
        guidance:
          "La durée du travail a des implications importantes sur le bien-être du nouveau-né ainsi que sur celui de la mère. Renseignez-vous et enregistrez la durée totale du travail depuis l'apparition des douleurs jusqu'à la délivrance du placenta en heures. On s’attend à ce que cette réponse soit principalement une approximation plutôt qu’une mesure exacte. Si moins d'une heure, entrez « 0 » heures. Une réponse valide est comprise entre 0 et 99. Si la réponse a duré plus de 98 heures, confirmez la réponse et entrez « 98 ». Si la personne interrogée ne se souvient pas exactement de la durée, demandez-la et notez-la en fonction de ce qui est médicalement pertinent à saisir : Si le travail et l'accouchement ont duré :\n● pendant moins de 24 heures - l'enquêteur doit saisir 23 heures ;\n● pendant plus de 24 heures – l'enquêteur doit saisir 25 heures.\nPour je ne sais pas, entrez « 99 ». Pour refusé, inscrivez « 88 ». Si la durée indiquée est de 88 heures, inscrivez « 87 » afin que la réponse ne soit pas automatiquement codée comme refus de réponse.",
        constraintMessage:
          "Saisissez un nombre entier d'heures compris entre 0 et 98. Utilisez 0 pendant moins d'une heure ; utiliser 23 ou 25 lorsque seule l'estimation à moins ou à plus de 24 heures est connue ; utilisez 88 pour refusé ; et utilisez 99 pour je ne sais pas. Si la durée réelle était de 88 heures, entrez 87."
      },
      Id10383: {
        label: "(Id10383) Le bébé est-il né 24 heures ou plus après la perte des eaux ?",
        guidance:
          "Habituellement, la perte des eaux se produit peu de temps (jusqu'à quelques heures) avant le début de l'accouchement. Une fuite ou un bris d'eau pendant plus de 24 heures avant l'accouchement peut être associé à une infection et à d'autres causes de décès chez les nouveau-nés. Sondez attentivement pour obtenir une réponse précise à cette question.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10384: {
        label: "(Id10384) L'alcool sentait-il nauséabond ?",
        guidance:
          "L'alcool (l'eau dans l'utérus) peut avoir une mauvaise odeur en cas d'infection. Les mères seraient capables de s'en souvenir et de faire rapport. Sondez attentivement pour obtenir une vraie réponse.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10385: {
        label: "(Id10385) Quelle était la couleur de la liqueur lorsque les eaux se brisèrent ?",
        guidance:
          "Dans de nombreux cas, il se peut qu’il n’y ait pas de rappel/réponse clair à cette question. Dans des circonstances normales, la liqueur est comme « l’eau » (c’est-à-dire sans couleur spécifique). Dans certains cas, il peut être taché de substances noires verdâtres ou brunes. Une telle décoloration serait probablement mémorisée, de sorte qu'une réponse peu claire ou incertaine suggérerait généralement que les eaux étaient claires. Sélectionnez la réponse appropriée. Pour toute description anormale, enregistrez la réponse comme indiqué dans la section narrative.",
        choices: {
          green_or_brown: "Vert ou marron",
          clear: "Clair (normal)",
          other: "Autre",
          dk: "Je ne sais pas",
          ref: "A refusé de répondre"
        }
      },
      Id10387: {
        label: "(Id10387) L'accouchement a-t-il été normal par voie vaginale, sans forceps ni aspirateur ?",
        guidance:
          'La plupart des accouchements ont lieu lorsque la tête du bébé sort en premier, depuis le canal génital. Une telle livraison, si elle a lieu sans l’aide d’aucun instrument, est qualifiée de livraison normale. Toute utilisation d\'instruments, présentation autre que la tête en premier ou accouchement suite à une opération abdominale ne constitue pas un accouchement normal et est associé à un ensemble différent de risques de décès du nouveau-né. Clarifiez la signification d\'un accouchement vaginal normal (en prenant soin de préciser "tête en premier") à l\'enquêtée, avant d\'enregistrer la réponse. Si la réponse est "OUI", passez à Id10391. Si la réponse est "NON/NSP/Réf", passez à la question suivante.',
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10388: {
        label: "(Id10388) L'accouchement s'est-il déroulé par voie vaginale, avec forceps ou aspiration ?",
        guidance:
          "Souvent, un terme local est utilisé pour désigner l'utilisation d'instruments destinés à faciliter l'accouchement. Renseignez-vous en utilisant ce terme et marquez la réponse en conséquence. Marquez la réponse en conséquence et si « OUI », passez à Id10391. Si « NON/NSP/Réf », passez à la question suivante.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10389: {
        label: "(Id10389) L'accouchement a-t-il eu lieu par césarienne ?",
        guidance:
          "Le terme « césarienne » fait référence à une opération abdominale qui consiste à ouvrir l’utérus et à extraire l’enfant de l’abdomen. Ce terme « césarienne » est communément connu des membres de la communauté, mais si nécessaire, les mots ou termes locaux désignant l'accouchement par opération abdominale pourraient être utilisés.",
        constraintMessage:
          "Il n'est pas possible de répondre « Non » aux trois questions précédentes. Veuillez revenir en arrière et revoir les réponses.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10391: {
        label:
          "(Id10391) Est-ce que vous/la mère du bébé avez reçu des vaccins depuis que vous avez atteint l'âge adulte, y compris pendant cette grossesse ?",
        guidance:
          "Les femmes enceintes reçoivent des injections de vaccin pour prévenir la survenue d'une infection grave chez les nouveau-nés. La vaccination lors de grossesses antérieures peut également fournir un certain degré de protection, c'est pourquoi cette question demande que de telles vaccinations soient effectuées après avoir atteint l'âge adulte. Si la réponse est « NON/NSP/Réf », passez à Id10395.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10393: {
        label:
          "(Id10393) Est-ce que vous/la mère du bébé avez reçu le vaccin contre l'anatoxine tétanique (TT) ?",
        guidance:
          "Cette question est posée pour identifier s'il existe des connaissances spécifiques quant à la nature du vaccin reçu, c'est-à-dire contre le tétanos. Une réponse positive à cette question permettrait d’exclure le tétanos comme cause de décès des nouveau-nés. Essayez soigneusement d'obtenir une réponse correcte à cette question.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10395: {
        label: "(Id10395) Pendant le travail, est-ce que vous/la mère du bébé avez souffert de fièvre ?",
        guidance:
          "La fièvre au moment de l'accouchement est une indication d'infections maternelles, qui pourraient avoir été transmises au bébé à ce moment-là. De telles infections pourraient être liées à la cause du décès du nouveau-né, c'est pourquoi l'identification de la fièvre chez la mère est un indicateur important.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10396: {
        label:
          "(Id10396) Au cours des 3 derniers mois de la grossesse, du travail ou de l'accouchement, est-ce que vous/la mère du bébé avez souffert d'hypertension artérielle ?",
        guidance:
          "La tension artérielle est vérifiée lors des visites périodiques de soins prénatals et, si elle est élevée, l'agent de santé informera les femmes enceintes de l'hypertension artérielle et leur conseillera de réduire le sel dans leur alimentation et éventuellement de prescrire certains médicaments. L'hypertension artérielle pendant la grossesse peut être associée à un faible poids à la naissance, à un accouchement prématuré et à d'autres complications. Dans certains cas, l’hypertension artérielle peut se manifester uniquement pendant le travail ou l’accouchement. Les mères et/ou leurs proches seraient en mesure de se souvenir et de signaler une hypertension artérielle et ainsi de sonder attentivement.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10397: {
        label: "(Id10397) Est-ce que vous/la mère du bébé souffriez de diabète sucré ?",
        guidance:
          "Le diabète maternel est associé à la naissance de bébés de plus grande taille, qui comportent leurs propres risques de décès néonatal. Le diabète maternel est également associé à divers types d'anomalies congénitales, notamment des malformations cardiaques congénitales. La série de questions suivante concerne la santé de la mère pendant la grossesse et l'accouchement. Ces symptômes et signes sont utiles pour identifier la cause du décès du nouveau-né. Mentionnez la nature des questions suivantes et la raison pour laquelle vous les posez, puis continuez.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10398: {
        label:
          "(Id10398) Est-ce que vous/la mère du bébé avez eu des pertes vaginales nauséabondes pendant la grossesse ou après l'accouchement ?",
        guidance:
          "Les sécrétions nauséabondes provenant du canal génital de l'enfant indiquent une infection grave et sont généralement accompagnées de douleurs dans le bas de l'abdomen et de fièvre. De telles infections peuvent être transmises au nouveau-né et provoquer des maladies graves pouvant entraîner la mort néonatale. Il est probable que la mère se souvienne de ce signe si elle est sondée attentivement.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10399: {
        label:
          "(Id10399) Au cours des 3 derniers mois de la grossesse, du travail ou de l'accouchement, est-ce que vous/la mère du bébé avez souffert de convulsions ?",
        guidance:
          "Les convulsions sont des contractions rapides ou des mouvements saccadés de parties des membres ou parfois de membres entiers, qui durent généralement quelques minutes et s'arrêtent lorsque la personne perd connaissance. Le terme courant pour désigner les convulsions est crises, et il existe souvent un terme local pour de tels mouvements. Dans certains cas, l'hypertension artérielle pendant la grossesse peut entraîner de telles crises, en particulier au cours des trois derniers mois. En l’absence de soins prénatals appropriés, de telles convulsions peuvent constituer le seul signe majeur d’hypertension artérielle sous-jacente chez la femme enceinte, avec les risques connus pour le nouveau-né, comme décrit ci-dessus. Les convulsions peuvent également survenir uniquement pendant le travail ou l'accouchement, ce qui constitue un événement grave et dramatique dont on se souviendra facilement. Clarifiez la signification du terme convulsions, la période d’intérêt (les 3 derniers mois) et enregistrez la réponse.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10400: {
        label:
          "(Id10400) Au cours des 3 derniers mois de la grossesse, est-ce que vous/la mère du bébé avez souffert d'une vision floue ?",
        guidance:
          "La vision floue est définie comme le fait de voir des objets sans forme ni marge claires, ou de voir des objets doubles. C'est également un signe d'hypertension artérielle pendant la grossesse, mais il peut être difficile à retenir et à retenir par la mère, mais un sondage minutieux peut obtenir une réponse précise.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10401: {
        label: "(Id10401) Est-ce que vous/la mère du bébé souffriez d'anémie sévère ?",
        guidance:
          "Dans certains cas, la grossesse est associée à un « amincissement » sévère du sang, qui se manifeste par une couleur blanche ou claire de la langue, des ongles, des paumes et du bord des yeux. Cette condition est connue sous le nom d’anémie et est associée à un accouchement prématuré, à un faible poids à la naissance, à une asphyxie à la naissance et à d’autres complications. Par conséquent, l’identification de l’anémie maternelle aide au diagnostic de la cause du décès néonatal.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10402: {
        label:
          "(Id10402) Est-ce que vous/la mère du bébé avez eu des saignements vaginaux au cours des 3 derniers mois de la grossesse mais avant le début du travail ?",
        guidance:
          "Un saignement du canal génital avant le début du travail est un signe important et est souvent associé à un trouble du placenta (utiliser un terme local). Des saignements excessifs mettent en danger la vie de la mère et du nouveau-né. Ceci est généralement facilement rappelé et rapporté par la mère.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10403: {
        label:
          "(Id10403) Les fesses, les pieds, le bras ou la main du bébé sont-ils sortis du vagin avant sa tête ?",
        guidance:
          "La première partie du bébé à naître est généralement la tête. La présentation de toute autre partie du corps en premier (par exemple les fesses, les pieds, le bras ou la main) est associée à plusieurs causes de décès néonatal, notamment les blessures à la naissance, les problèmes respiratoires graves et les infections pulmonaires. Les mères connaissent généralement la partie du corps qui a été accouchée en premier et peuvent donner la vraie réponse à cette question si on la leur pose soigneusement.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10404: {
        label:
          "(Id10404) Le cordon ombilical a-t-il été enroulé plus d'une fois autour du cou de l'enfant à la naissance ?",
        guidance:
          "Les mères sauraient si le cordon était autour du cou, mais ne se souviendraient peut-être pas du nombre de fois. Il est important de vérifier si le cordon a été enroulé plus d'une fois, car le risque de décès du bébé augmente s'il a été enroulé plus d'une fois.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10405: {
        label: "(Id10405) Le cordon ombilical a-t-il été délivré en premier ?",
        guidance:
          "Il s’agit d’une pathologie relativement rare, mais associée à des issues néonatales indésirables. La mère peut ne pas avoir pleinement connaissance de son apparition.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10406: {
        label: "(Id10406) Le bébé était-il de couleur bleue à la naissance ?",
        guidance:
          "La couleur bleuâtre du bébé à la naissance suggère un problème affectant la respiration du bébé. Les mères peuvent être en mesure de signaler que le bébé était bleu ou est devenu foncé si elles sont soigneusement sondées.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10411: {
        label: "(Id10411) A-t-il bu de l'alcool ?",
        guidance:
          "La consommation d'alcool pourrait être associée à des maladies du foie, ainsi qu'à des problèmes de santé mentale associés à la dépression et au suicide, et également à une prise de risque conduisant à des accidents de la route ou à des violences interpersonnelles. Bien que l’alcool puisse être directement lié à l’événement ou à la circonstance spécifique ayant conduit au décès, il pourrait exister un risque sous-jacent associé à une consommation chronique ou régulière d’alcool. Cette question vise à saisir la consommation régulière au moins une fois par semaine ou plus souvent. Notez tous les détails spécifiques fournis par le répondant dans la section narrative du questionnaire. Cette question est utilisée par le logiciel d'analyse automatisée. La consommation d’alcool étant une question sensible, aucune information supplémentaire sur la fréquence ou la quantité de consommation n’est demandée.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10413: {
        label: "(Id10413) A-t-il déjà fumé du tabac ?",
        hint: "Pour clarifier, la série s'interroge sur la consommation de tabac à n'importe quelle période de la vie (c'est-à-dire pas seulement sur l'état actuel avant le décès).",
        guidance:
          "Le terme « fumée » est utilisé dans cette question pour désigner spécifiquement les types de tabac fumés. Le tabagisme est lié, entre autres, au cancer du poumon, au cancer de la bouche et à l'asthme chronique. Cette question ne vise pas à saisir l’usage ou la consommation de tabac à chiquer. La série s'interroge sur le tabagisme à n'importe quelle période de la vie (c'est-à-dire pas seulement sur l'état actuel avant la mort). Si la réponse est « NON/NSP/Réf », passez à Id10414.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10413_a: {
        label: "(Id10413_a) Pendant combien de temps a-t-il fumé du tabac ?",
        hint: "[ Si le défunt a fumé pendant moins d'un mois, entrez 1 mois comme durée de l'entretien VA. ]",
        guidance:
          "Inscrivez la durée pendant laquelle le défunt a fumé du tabac en nombre de mois ou d'années. Si la personne décédée a fumé pendant moins d'un mois, inscrivez 1 mois comme durée.",
        choices: {
          months: "Mois",
          years: "Années",
          dk: "Je ne sais pas",
          ref: "A refusé de répondre"
        }
      },
      Id10413_d: {
        label: "(Id10413_d) Combien (mois/années)"
      },
      Id10413_b: {
        label: "(Id10413_b) A-t-il déjà fumé quotidiennement ?",
        hint: "La question vise à savoir s'il y a eu une période dans la vie du défunt où il a fumé quotidiennement - même si cette période n'a pas été continue ou si le défunt n'a pas fumé pendant la période ayant conduit au décès.",
        guidance:
          "La question vise à savoir s’il y a eu une période dans la vie du défunt où il a fumé du tabac quotidiennement (c’est-à-dire au moins 1 fois par jour) – même si cette période n’a pas été continue ou si le défunt n’a pas fumé pendant la période ayant conduit au décès. Fumer quotidiennement est associé à des risques importants pour la santé, même à de faibles niveaux de consommation.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10414: {
        label: "(Id10414) A-t-il déjà mâché et/ou reniflé du tabac ?",
        hint: "Pour clarifier, la série s'interroge sur la consommation de tabac à n'importe quelle période de la vie (c'est-à-dire pas seulement sur l'état actuel avant le décès).",
        guidance:
          "La question vise à saisir la consommation de produits du tabac sans fumée sous forme de mastication et/ou de reniflage. Si la réponse est « NON/NSP/Réf », passez à Id10418.",
        constraintMessage:
          "Il n'est pas possible de sélectionner des cigarettes ou une pipe et de répondre « non » à « A-t-il fumé du tabac ? ». Veuillez revenir en arrière et corriger les sélections.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10414_a: {
        label: "(Id10414_a) Pendant combien de temps a-t-il mâché et/ou reniflé du tabac ?",
        guidance:
          "Inscrivez la durée pendant laquelle la personne décédée a mâché et/ou reniflé du tabac, en nombre de mois ou d'années. Si la personne décédée a mâché et/ou reniflé du tabac pendant moins d'un mois, inscrivez 1 mois comme durée.",
        constraintMessage:
          "Il n'est pas possible de sélectionner des cigarettes ou une pipe et de répondre « non » à « A-t-il fumé du tabac ? ». Veuillez revenir en arrière et corriger les sélections.",
        choices: {
          months: "Mois",
          years: "Années",
          dk: "Je ne sais pas",
          ref: "A refusé de répondre"
        }
      },
      Id10414_d: {
        label: "(Id10414_d) Combien (mois/années)"
      },
      Id10414_b: {
        label: "(Id10414_b) A-t-il déjà mâché et/ou sniffé du tabac quotidiennement ?",
        hint: "La question vise à savoir s'il y a déjà eu une période dans la vie du défunt pendant laquelle il mâchait et/ou reniflait du tabac quotidiennement - même si cette période n'était pas continue ou si le défunt ne mâchait et/ou ne reniflait pas dans la période menant au décès.",
        guidance:
          "La question vise à savoir s’il y a eu une période dans la vie du défunt où il a mâché et/ou sniffé du tabac quotidiennement (c’est-à-dire au moins 1 fois par jour) – même si cette période n’a pas été continue ou si le défunt n’a pas mâché et/ou sniffé du tabac pendant la période ayant conduit au décès.",
        constraintMessage:
          "Il n'est pas possible de sélectionner des cigarettes ou une pipe et de répondre « non » à « A-t-il fumé du tabac ? ». Veuillez revenir en arrière et corriger les sélections.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10418: {
        label: "(Id10418) A-t-il reçu un traitement pour la maladie qui a conduit au décès ?",
        guidance:
          "Cette question fait référence aux traitements de santé formels, et non aux médecines traditionnelles, aux remèdes maison ou aux traitements non professionnels. Si la réponse à cette question est « NON », vous passerez alors à Id10435. REMARQUE : Il convient de répondre à ces questions selon que le patient a reçu le traitement OU a eu besoin du traitement, tel que recommandé par un professionnel de la santé.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10419: {
        label: "(Id10419) A-t-il reçu des sels de réhydratation orale ?",
        guidance:
          "Les sels de réhydratation orale se présentent sous forme de sachet de poudre qui doit être dissous dans l'eau et administré aux personnes souffrant de diarrhée, en particulier aux enfants. Il s’agit d’un remède efficace et connu pour prévenir la mort. Cette question concerne uniquement les sachets fournis par les professionnels de santé, et non les solutions faites maison. Cette question vise à évaluer la disponibilité et l'accès aux services de santé.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10420: {
        label: "(Id10420) A-t-il reçu (ou eu besoin) d'un traitement par perfusion intraveineuse ?",
        guidance:
          "Un goutte-à-goutte est généralement administré dans un centre de santé par un agent de santé qualifié. L'administration d'un goutte-à-goutte est évocatrice d'affections graves telles qu'une déshydratation.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10421: {
        label: "(Id10421) A-t-il reçu (ou besoin) une transfusion sanguine ?",
        guidance:
          "Une transfusion sanguine est également une indication de la gravité de la maladie et peut être évocatrice de causes de décès associées à une perte de sang aiguë.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10422: {
        label:
          "(Id10422) A-t-il reçu (ou eu besoin) d'un traitement/de nourriture par le biais d'un tube passé dans le nez ?",
        guidance:
          "L'alimentation par la sonde nasale indique des dommages potentiels au système nerveux, et des problèmes liés à une telle manière d'alimentation peuvent entraîner des vomissements partiels et une infection des poumons, entraînant la mort. Renseignez-vous sur la durée pendant laquelle l'alimentation a été fournie par la sonde et si la sonde a été en place jusqu'au décès, et notez tous ces détails dans la section narrative du questionnaire.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10423: {
        label: "(Id10423) A-t-il reçu (ou eu besoin) d'antibiotiques injectables ?",
        hint: "Les antibiotiques injectables excluent les vaccinations, les vaccins et les analgésiques. Les antibiotiques sont administrés contre les infections (c'est-à-dire les germes).",
        guidance:
          "Les antibiotiques injectables excluent les vaccinations, les vaccins et les analgésiques. Les antibiotiques injectables sont des médicaments contre les infections bactériennes administrés par aiguille. Ils indiquent une infection grave d’une ou plusieurs parties du corps et sont presque toujours administrés uniquement dans les établissements de santé. Cependant, les détails d’un tel traitement peuvent ou non être partagés avec les membres de la famille.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10424: {
        label: "(Id10424) A-t-il reçu (ou eu besoin) d'un traitement antirétroviral (TAR) ?",
        guidance:
          "La thérapie médicamenteuse ART est administrée aux patients séropositifs. Cette thérapie consiste en des pilules pour adultes et souvent des suspensions liquides (sirops) pour les enfants, qui sont généralement prises quotidiennement et à long terme. Cette question peut être pertinente ou non, compte tenu du profil épidémiologique du pays ou de la région du pays où ce questionnaire est administré. De plus, les proches du patient peuvent ne pas connaître ces détails. Expliquez soigneusement la question et enregistrez la réponse en conséquence.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10425: {
        label: "(Id10425) A-t-il subi (ou besoin) une opération à cause de la maladie ?",
        guidance:
          "Une opération peut également être une indication de la gravité de la maladie. La raison médicale de l’opération est probablement connue des proches. Si la réponse est « OUI », demandez aux proches s'ils connaissent le problème de santé (par exemple cancer, ulcère de l'estomac, maladie cardiaque, etc.) qui a motivé l'opération ; et notez les détails dans la section narrative du questionnaire.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10426: {
        label: "(Id10426) A-t-il été opéré dans le mois précédant le décès ?",
        guidance:
          "Le moment de l’opération permettra de déterminer tout lien entre le traitement et la cause du décès.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10435: {
        label: "(Id10435) Un agent de santé vous a-t-il indiqué la cause du décès ?",
        guidance: "Si la réponse est « NON/NSP/Réf », passez à Id10446.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10436: {
        label: "(Id10436) Qu'a dit l'agent de santé ?",
        guidance:
          "Enregistrez ici les détails de toute information communiquée verbalement sur la cause probable du décès."
      },
      Id10446: {
        label:
          "(Id10446) La mère (biologique) du défunt a-t-elle déjà été informée qu'elle était atteinte du VIH/SIDA par un agent de santé ?",
        guidance:
          "Il s’agit peut-être d’une question sensible, mais il s’agit d’informations très importantes qui peuvent aider à déterminer la cause du décès.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      botecrn: {
        label:
          "État civil : \"Il s'agit du certificat de décès légal obtenu auprès des autorités de l'état civil (montrer l'image du certificat de décès local si disponible).\""
      },
      Id10069_a: {
        label: "(Id10069_a) Avez-vous un acte de décès de l'état civil ?",
        guidance:
          "Demandez à voir le certificat ou les documents d’enregistrement du décès. Les enquêteurs doivent être familiarisés avec l'autorité d'état civil locale et avec le(s) formulaire(s) d'enregistrement de décès approprié(s) contenant les informations pertinentes d'enregistrement de décès, comme demandé dans cette section. Si « OUI » et que les documents sont disponibles, continuez avec Id10070–Id10073. Si les documents ne sont pas disponibles, passez à Id10462.",
        choices: {
          yes: "Oui",
          no: "Non"
        }
      },
      Id10070: {
        label: "(Id10070) [Numéro d'enregistrement/certificat de décès]",
        hint: "Entrez un « - » si cette information n'est pas disponible.",
        guidance:
          "Enregistrez le numéro d’enregistrement ou de certificat. Notez que les répondants peuvent avoir une « notification de décès » avec un numéro de « notification » ou un « certificat de décès » avec un « certificat », un « enregistrement », un « numéro de série » ou un autre type de numéro. Le bureau du projet doit s'assurer que tous les enquêteurs savent clairement quel numéro doit être enregistré. Le bureau de projet pourra adapter cet élément aux usages locaux de numérotation. Entrez « - », si cette information n'est pas disponible."
      },
      Id10071_check: {
        label: "(Id10071_check) [La date d'inscription est-elle disponible ?]",
        choices: {
          yes: "Oui",
          no: "Non"
        }
      },
      Id10071: {
        label: "(Id10071) [Date d'inscription]",
        guidance: "Enregistrez la date d’inscription si elle est connue."
      },
      Id10072: {
        label: "(Id10072) [Lieu d'immatriculation]",
        hint: "Entrez un « - » si cette information n'est pas disponible.",
        guidance:
          "Enregistrez tous les détails du lieu d’enregistrement. Cela peut inclure le nom du village/ville/municipalité où le décès a été enregistré. Entrez « - », si cette information n'est pas disponible. Le site du projet peut ajouter une liste déroulante d'options d'emplacement."
      },
      Id10073: {
        label: "(Id10073) [Numéro national d'identification du défunt]",
        hint: "Enregistrez le numéro d’identification national. Pour les nouveau-nés qui n’ont pas de numéro d’identification, utilisez la pièce d’identité de la mère. Si la pièce d’identité de la mère n’est pas disponible, utilisez la pièce d’identité du père. Si ces informations sont inconnues ou non disponibles, entrez « - ». Notez dont l'ID a été saisi dans l'espace après que l'ID a été enregistré.",
        guidance:
          "Enregistrez le numéro d’identification national. Pour les nouveau-nés qui n’ont pas de numéro d’identification, utilisez la pièce d’identité de la mère. Si la pièce d’identité de la mère n’est pas disponible, utilisez la pièce d’identité du père. Si ces informations sont inconnues ou non disponibles, entrez « - ». Notez dont l'ID a été saisi dans l'espace après que l'ID a été enregistré."
      },
      noteccd: {
        label:
          "Certificat de décès avec cause du décès : \"Il s'agit du certificat médical indiquant la cause du décès (montrer l'image du certificat médical local indiquant la cause du décès, si disponible).\""
      },
      Id10462: {
        label: "(Id10462) Un certificat médical indiquant la cause du décès a-t-il été délivré ?",
        hint: "Les informations suivantes servent uniquement à compléter les informations sur la cause du décès dans certains environnements. Dans les CRVS de routine, ces informations pourraient être ignorées lors de l’entretien et les informations pourraient être collectées auprès d’autres sources, si elles sont disponibles.",
        guidance:
          "Demandez au répondant s'il existe un certificat médical indiquant la cause du décès de la personne décédée. Le certificat médical indiquant la cause du décès est généralement obtenu auprès d'un médecin d'un hôpital et doit être distingué du certificat de décès délivré par l'organisme d'état civil. Lors de l'adaptation nationale, les pays doivent préciser le nom spécifique de l'autorité locale d'état civil qui délivre les certificats de décès ; L'adaptation au pays devrait également indiquer s'il existe d'autres « certificats » tels que le permis d'inhumer avec lesquels cette question peut être confondue.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10463: {
        label: "(Id10463) Puis-je voir le certificat médical de la cause du décès ?",
        hint: "Cette section vise à collecter des informations à partir du certificat médical standard international de cause de décès. Ce niveau de détail peut être présent ou non dans l'acte de décès délivré à la famille. Enregistrez « non » si les informations médicales sur la cause du décès ne sont pas disponibles. Le certificat médical indiquant la cause du décès est généralement obtenu auprès d'un médecin d'un hôpital et doit être distingué du certificat de décès délivré par l'organisme d'état civil.",
        guidance:
          "Demandez si vous pouvez voir le certificat médical de la cause du décès afin d'enregistrer des informations sur la cause du décès. Lors de l'adaptation nationale, les pays doivent préciser le nom spécifique de l'autorité locale d'état civil qui délivre les certificats de décès ; L'adaptation au pays devrait également indiquer s'il existe d'autres « certificats » tels que le permis d'inhumer avec lesquels cette question peut être confondue. Remplissez les questions suivantes uniquement si la copie du certificat vous est présentée. Ne remplissez pas uniquement sur la base de déclarations orales. Enregistrez « NON » si les informations médicales sur la cause du décès ne sont pas disponibles.",
        choices: {
          yes: "Oui",
          no: "Non",
          dk: "Ne sait pas",
          ref: "Refus de repondre"
        }
      },
      Id10464: {
        label: "(Id10464) [Enregistrer la cause immédiate du décès à partir du certificat (ligne 1a)]",
        hint: 'Si ce détail n\'est pas présent, inscrivez "-" (non disponible).',
        guidance:
          "Cette section vise à collecter des informations à partir du certificat médical standard international de cause de décès. Ce niveau de détail peut être présent ou non dans l'acte de décès délivré à la famille. Si ce détail n'est pas présent, remplissez « - » pour Id10464–Id10473. Copiez la cause du décès sur la première ligne du certificat de décès. Il devrait toujours y avoir une cause enregistrée ici. Si une durée pendant laquelle cette cause a été ressentie est également enregistrée dans la colonne à côté de la cause, inscrivez-la dans Id10465."
      },
      Id10465: {
        label: "(Id10465) [Durée de la cause immédiate du décès (Ia) :]",
        hint: 'Pour toutes les lignes suivantes, ajoutez la durée, si indiqué. Si ce détail n\'est pas présent, inscrivez "-" (non disponible).',
        guidance:
          "Cette section vise à collecter des informations à partir du certificat médical standard international de cause de décès. Ce niveau de détail peut être présent ou non dans l'acte de décès délivré à la famille. Si ce détail n'est pas présent, remplissez « - » pour Id10464–Id10473. Copiez la cause du décès sur la première ligne du certificat de décès. Il devrait toujours y avoir une cause enregistrée ici. Si une durée pendant laquelle cette cause a été ressentie est également enregistrée dans la colonne à côté de la cause, inscrivez-la dans Id10465."
      },
      Id10466: {
        label: "(Id10466) [Enregistrer la première cause antérieure du décès du certificat (ligne 1b)]",
        hint: 'Une cause antérieure est celle qui a provoqué celle de la ligne ci-dessus, par ex. le diabète sucré peut être une cause antérieure à une maladie rénale. Si ce détail n\'est pas présent, inscrivez "-" (non disponible).',
        guidance:
          "Copiez la cause de la deuxième ligne de l'acte de décès s'il y en a une ainsi que sa durée."
      },
      Id10467: {
        label: "(Id10467) [Durée de la première cause antérieure de décès (Ib) :]",
        hint: 'Si ce détail n\'est pas présent, inscrivez "-" (non disponible).',
        guidance:
          "Copiez la cause de la deuxième ligne de l'acte de décès s'il y en a une ainsi que sa durée."
      },
      Id10468: {
        label: "(Id10468) [Enregistrer la deuxième cause antérieure du décès du certificat (ligne 1c)]",
        hint: 'Si ce détail n\'est pas présent, inscrivez "-" (non disponible).',
        guidance:
          "Copiez la cause de la troisième ligne de l'acte de décès s'il y en a une ainsi que sa durée."
      },
      Id10469: {
        label: "(Id10469) [Durée de la deuxième cause antérieure de décès (Ic) :]",
        hint: 'Si ce détail n\'est pas présent, inscrivez "-" (non disponible).',
        guidance:
          "Copiez la cause de la troisième ligne de l'acte de décès s'il y en a une ainsi que sa durée."
      },
      Id10470: {
        label: "(Id10470) [Enregistrer la troisième cause antérieure du décès du certificat (ligne 1d)]",
        hint: 'Si ce détail n\'est pas présent, inscrivez "-" (non disponible).',
        guidance:
          "Copiez la cause de la quatrième ligne de l'acte de décès s'il y en a une ainsi que sa durée."
      },
      Id10471: {
        label: "(Id10471) [Durée de la troisième cause antérieure de décès (Id) :]",
        hint: 'Si ce détail n\'est pas présent, inscrivez "-" (non disponible).',
        guidance:
          "Copiez la cause de la quatrième ligne de l'acte de décès s'il y en a une ainsi que sa durée."
      },
      Id10472: {
        label:
          "(Id10472) [Enregistrer la ou les causes contributives du décès à partir du certificat (partie 2)]",
        hint: 'Si ce détail n\'est pas présent, inscrivez "-" (non disponible).',
        guidance:
          "Énumérez toutes les causes contributives enregistrées dans la partie II du certificat de décès."
      },
      Id10473: {
        label: "(Id10473) [Durée de la ou des causes contributives du décès (partie 2) :]",
        hint: 'Si ce détail n\'est pas présent, inscrivez "-" (non disponible).',
        guidance:
          "Énumérez toutes les causes contributives enregistrées dans la partie II du certificat de décès."
      },
      Id10481: {
        label: "Heure de fin de l'entretien"
      },
      noteend: {
        label:
          "[ Informez le répondant que l'entretien avec le VA est terminé. Remerciez le répondant pour son temps et ses réponses, et demandez-lui s'il a des questions ou des commentaires à faire. Utilisez cette section pour enregistrer tous les détails supplémentaires que vous et/ou le répondant avez sur l'entretien. ]",
        guidance: "Enregistrez ici tous les détails supplémentaires sur l’intervieweur."
      },
      comment: {
        label: "(commentaire) Commentaire",
        guidance: "Enregistrez ici tous les détails supplémentaires sur l’intervieweur."
      },
      custom_medical_certificate_upload: {
        label: "Téléverser le certificat médical (image ou PDF)",
        hint: "Choisissez une image JPEG ou PNG, ou un document PDF."
      }
    }
  },
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
    recorded: "Enregistré",
    startingMicrophone: "Démarrage du microphone…",
    stopAndSaveRecording: "Arrêter et enregistrer l’audio",
    savingRecording: "Enregistrement de l’audio…",
    replaceAudio: "Remplacer l’audio",
    recordAudio: "Enregistrer un audio",
    microphonePermissionDenied:
      "L’accès au microphone a été refusé. Autorisez-le dans le navigateur et réessayez.",
    audioRecordingFailed: "L’enregistrement audio a échoué. Veuillez réessayer.",
    selectedImage: "Image sélectionnée",
    savedImageLoadFailed: "L’image enregistrée n’a pas pu être chargée depuis cet appareil.",
    openingCamera: "Ouverture de l’appareil photo…",
    camera: "Appareil photo",
    openingImages: "Ouverture des images…",
    replaceImage: "Remplacer l’image",
    chooseImage: "Choisir une image",
    hideImage: "Masquer l’image",
    viewImage: "Afficher l’image",
    rotate: "Faire pivoter",
    zoomIn: "Agrandir",
    zoomOut: "Réduire",
    removeImage: "Supprimer l’image",
    attachment: "pièce jointe",
    pdf: "PDF",
    openingFiles: "Ouverture des fichiers…",
    replaceAttachment: "Remplacer {kind}",
    chooseAttachment: "Choisir {kind}",
    removeAttachment: "Supprimer {kind}",
    attachmentProcessingFailed: "La pièce jointe sélectionnée n’a pas pu être traitée et a été supprimée.",
    imageInputTooLarge: "Choisissez une image de moins de 10 Mo.",
    imageTypeNotAllowed:
      "Choisissez une image JPEG ou PNG valide. Les fichiers renommés ou non pris en charge ne sont pas acceptés.",
    imageDimensionsInvalid:
      "Les dimensions de cette image ne sont pas valides et elle ne peut pas être utilisée.",
    imageDimensionsTooLarge:
      "Cette image contient trop de pixels. Choisissez une image plus petite ou reprenez la photo.",
    imageDecodeFailed: "Ce fichier n’a pas pu être décodé comme une image sûre.",
    imageOutputInvalid: "L’image traitée n’a pas pu être vérifiée comme fichier JPEG.",
    imageOutputTooLarge:
      "Cette image n’a pas pu être réduite à moins de 2 Mo. Reprenez-la avec une résolution inférieure.",
    imageProcessingUnavailable:
      "Le traitement des images n’est pas disponible. L’image d’origine n’a pas été enregistrée.",
    attachmentStorageFailed: "La pièce jointe traitée n’a pas pu être enregistrée sur cet appareil.",
    pdfInputTooLarge: "Choisissez un PDF de moins de 5 Mo.",
    pdfTypeNotAllowed:
      "Choisissez un PDF valide. Les fichiers renommés ou non pris en charge ne sont pas acceptés.",
    pdfRenderFailed: "Ce PDF n’a pas pu être converti de façon sûre en images de pages et a été supprimé.",
    pdfTooManyPages: "Ce PDF contient trop de pages. Sélectionnez un document de 10 pages maximum.",
    pdfOutputTooLarge: "Les pages PDF converties sont trop volumineuses et ont été supprimées.",
    pdfProcessingUnavailable:
      "La conversion PDF n’est pas disponible. Le PDF d’origine n’a pas été enregistré."
  }
} satisfies WhoVaLanguageFile;
