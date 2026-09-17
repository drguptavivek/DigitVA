-- Wide answer table with one JSONB column per WHO VA 2022 question.
-- Column names are generated from question labels only.
create table if not exists who_va_instruments (
  entry_uid text primary key references who_va_form_entries (uid) on delete cascade,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  "audit" jsonb,
  "name_of_va_interviewer" jsonb,
  "age_of_va_interviewer" jsonb,
  "sex_of_va_interviewer" jsonb,
  "of_va_interviewer" jsonb,
  "interview_language" jsonb,
  "is_this_a_region_of_high_hiv_aids_mortality" jsonb,
  "is_this_a_region_of_high_malaria_mortality" jsonb,
  "during_which_season_did_s_he_die" jsonb,
  "what_is_the_full_name_of_va_respondent" jsonb,
  "what_is_the_sex_of_va_respondent" jsonb,
  "what_is_the_age_of_va_respondent" jsonb,
  "what_is_your_the_respondent_s_relationship_to_the_deceased" jsonb,
  "did_you_the_respondent_live_with_the_deceased_in_the_period_lea" jsonb,
  "date_of_the_interview" jsonb,
  "did_the_respondent_give_consent" jsonb,
  "start_time_of_the_interview" jsonb,
  "what_was_the_first_or_given_name_s_of_the_deceased" jsonb,
  "what_was_the_surname_s_or_family_name_s_of_the_deceased" jsonb,
  "what_was_the_sex_of_the_deceased" jsonb,
  "is_the_date_of_birth_known" jsonb,
  "when_was_the_deceased_born" jsonb,
  "is_the_date_of_death_known" jsonb,
  "when_did_s_he_die" jsonb,
  "when_did_s_he_die_2" jsonb,
  "when_did_s_he_die_3" jsonb,
  "please_indicate_the_year_of_death" jsonb,
  "age_in_days" jsonb,
  "age_in_days_2" jsonb,
  "age_in_years" jsonb,
  "ageinyearsremain" jsonb,
  "age_in_months" jsonb,
  "ageinmonthsremain" jsonb,
  "the_deceased_person_is_a_neonate" jsonb,
  "the_deceased_person_is_a_child" jsonb,
  "the_deceased_person_is_an_adult" jsonb,
  "neonate_was_ageindays_days_old" jsonb,
  "child_was_ageinyears_years_ageinmonths_months_and_ageinmonthsre" jsonb,
  "adult_was_ageinyears_years_old" jsonb,
  "what_age_group_corresponds_to_the_deceased" jsonb,
  "how_many_days_old_was_the_baby_enter_neonate_s_age_in_days" jsonb,
  "how_many_hours_was_the_baby_alive" jsonb,
  "how_old_was_the_child_enter_child_s_age_in" jsonb,
  "enter_child_s_age_in_days" jsonb,
  "enter_child_s_age_in_months" jsonb,
  "enter_child_s_age_in_years" jsonb,
  "enter_adult_s_age_in_years" jsonb,
  "age_in_months_2" jsonb,
  "age_in_years_2" jsonb,
  "the_deceased_person_is_a_neonate_2" jsonb,
  "the_deceased_person_is_a_child_2" jsonb,
  "the_deceased_person_is_an_adult_2" jsonb,
  "the_deceased_person_is_a_neonate_3" jsonb,
  "the_deceased_person_is_a_child_3" jsonb,
  "the_deceased_person_is_an_adult_3" jsonb,
  "age_in_days_3" jsonb,
  "it_is_not_possible_to_select_that_the_respondent_is_the_child_o" jsonb,
  "where_did_the_deceased_die" jsonb,
  "in_the_two_weeks_before_death_did_s_he_live_with_visit_or_care" jsonb,
  "is_there_a_need_to_collect_additional_demographic_data_on_the_d" jsonb,
  "what_was_her_his_citizenship_nationality" jsonb,
  "what_was_her_his_ethnicity" jsonb,
  "what_was_her_his_place_of_birth" jsonb,
  "what_was_her_his_place_of_usual_residence_the_place_where_the_p" jsonb,
  "where_did_the_death_occur_specify_country_province_district_vil" jsonb,
  "what_was_her_his_marital_status" jsonb,
  "what_was_her_his_highest_level_of_schooling" jsonb,
  "was_s_he_able_to_read_and_or_write" jsonb,
  "what_was_her_his_economic_activity_status_in_year_prior_to_deat" jsonb,
  "what_was_her_his_occupation_that_is_what_kind_of_work_did_s_he" jsonb,
  "what_was_the_full_name_of_the_father" jsonb,
  "what_was_the_full_name_of_the_mother" jsonb,
  "record_detailed_notes_of_response_or_audio_record_the_response" jsonb,
  "thank_you_for_your_information_now_can_you_please_tell_me_in_yo" jsonb,
  "thank_you_for_your_information_now_can_you_please_tell_me_in_2" jsonb,
  "select_any_of_the_following_words_that_were_mentioned_as_presen" jsonb,
  "select_any_of_the_following_words_that_were_mentioned_as_pres_2" jsonb,
  "select_any_of_the_following_words_that_were_mentioned_as_pres_3" jsonb,
  "some_of_the_following_questions_may_be_repetetive_or_irrelevant" jsonb,
  "did_the_baby_ever_cry" jsonb,
  "did_the_baby_cry_immediately_after_birth_even_if_only_a_little" jsonb,
  "how_many_minutes_after_birth_did_the_baby_first_cry" jsonb,
  "did_the_baby_stop_being_able_to_cry" jsonb,
  "did_the_baby_stop_moving_in_the_womb" jsonb,
  "did_the_baby_stop_moving_before_or_after_the_onset_of_labour" jsonb,
  "did_the_baby_ever_move_after_being_delivered" jsonb,
  "did_the_baby_ever_breathe" jsonb,
  "did_the_baby_breathe_immediately_after_birth_even_a_little" jsonb,
  "did_the_baby_have_a_breathing_problem" jsonb,
  "was_the_baby_given_assistance_to_breathe_at_birth" jsonb,
  "if_the_baby_didn_t_show_any_sign_of_life_was_it_born_dead" jsonb,
  "were_there_any_bruises_or_signs_of_injury_on_baby_s_body_after" jsonb,
  "was_the_baby_s_body_soft_discoloured_and_the_skin_peeling_away" jsonb,
  "explain_to_the_respondent_that_the_following_section_contains_a" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_tuberculosi" jsonb,
  "was_an_hiv_test_ever_positive" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_aids" jsonb,
  "did_s_he_have_a_recent_positive_test_by_a_health_professional_f" jsonb,
  "did_s_he_have_a_recent_negative_test_by_a_health_professional_f" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_covid_19" jsonb,
  "did_s_h_e_have_a_recent_test_for_covid_19" jsonb,
  "what_was_the_result" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_dengue_feve" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_measles" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_high_blood" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_heart_disea" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_diabetes" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_asthma" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_epilepsy" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_cancer" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_chronic_obs" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_dementia" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_depression" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_stroke" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_sickle_cell" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_kidney_dise" jsonb,
  "was_there_any_diagnosis_by_a_health_professional_of_liver_disea" jsonb,
  "unless_specified_the_following_questions_on_signs_symptoms_trea" jsonb,
  "did_s_he_suffer_from_any_injury_or_accident_that_led_to_her_his" jsonb,
  "how_long_after_the_injury_or_accident_did_s_he_die" jsonb,
  "interviewer_click_ok_to_confirm_the_answer_she_died_less_than_o" jsonb,
  "was_it_a_road_transport_injury" jsonb,
  "was_it_a_non_road_transport_injury" jsonb,
  "was_s_he_injured_in_a_fall" jsonb,
  "was_there_any_poisoning" jsonb,
  "did_s_he_die_of_drowning" jsonb,
  "was_s_he_injured_by_a_venomous_bite_or_sting_from_an_animal_or" jsonb,
  "was_s_he_injured_by_an_animal_or_insect_non_venomous" jsonb,
  "what_was_the_animal_insect" jsonb,
  "was_s_he_injured_by_burns_fire" jsonb,
  "was_s_he_injured_by_a_firearm" jsonb,
  "was_s_he_stabbed_cut_or_pierced" jsonb,
  "was_s_he_strangled" jsonb,
  "was_s_h_e_electrocuted" jsonb,
  "was_s_he_injured_by_a_blunt_force" jsonb,
  "was_s_he_injured_by_a_force_of_nature" jsonb,
  "did_s_he_suffer_any_other_injury" jsonb,
  "was_the_injury_accidental" jsonb,
  "was_the_injury_self_inflicted" jsonb,
  "was_the_injury_intentionally_inflicted_by_someone_else" jsonb,
  "how_many_days_old_was_the_baby_when_the_fatal_illness_started" jsonb,
  "before_the_illness_that_led_to_death_was_the_baby_the_child_gro" jsonb,
  "for_how_many_days_was_s_he_ill_before_death" jsonb,
  "for_how_long_was_s_he_ill_before_death" jsonb,
  "months" jsonb,
  "years" jsonb,
  "days" jsonb,
  "calculated_number_of_days_with_illness" jsonb,
  "did_s_he_die_suddenly" jsonb,
  "did_s_he_have_a_fever" jsonb,
  "how_many_days_did_the_fever_last" jsonb,
  "how_long_did_the_fever_last" jsonb,
  "enter_how_long_the_fever_lasted_in_days" jsonb,
  "enter_how_long_the_fever_lasted_in_months" jsonb,
  "how_many_days_did_the_fever_last_2" jsonb,
  "did_the_fever_continue_until_death" jsonb,
  "how_severe_was_the_fever" jsonb,
  "what_was_the_pattern_of_the_fever" jsonb,
  "did_s_he_have_a_cough" jsonb,
  "for_how_long_did_s_he_have_a_cough" jsonb,
  "enter_how_long_s_he_had_a_cough_in_days" jsonb,
  "enter_how_long_s_he_had_a_cough_in_months" jsonb,
  "for_how_many_days_did_s_he_have_a_cough" jsonb,
  "was_the_cough_productive_with_sputum" jsonb,
  "was_the_cough_very_severe" jsonb,
  "did_s_he_cough_up_blood" jsonb,
  "did_s_he_make_a_whooping_sound_when_coughing" jsonb,
  "did_s_he_have_any_difficulty_breathing_or_breathlessness" jsonb,
  "for_how_many_days_did_the_difficulty_breathing_or_breathlessnes" jsonb,
  "for_how_long_did_the_difficulty_breathing_or_breathlessness_las" jsonb,
  "enter_how_long_the_difficult_breathing_or_breathlessness_lasted" jsonb,
  "enter_how_long_the_difficult_breathing_or_breathlessness_last_2" jsonb,
  "enter_how_long_the_difficult_breathing_or_breathlessness_last_3" jsonb,
  "calculated_number_of_days_with_illness_2" jsonb,
  "was_the_difficulty_in_breathing_continuous_or_on_and_off" jsonb,
  "was_s_he_unable_to_carry_out_daily_routines_due_to_breathlessne" jsonb,
  "was_s_he_breathless_while_lying_flat" jsonb,
  "did_s_he_have_fast_breathing" jsonb,
  "for_how_many_days_did_the_fast_breathing_last" jsonb,
  "how_long_did_the_fast_breathing_last" jsonb,
  "enter_how_long_the_fast_breathing_lasted_in_days" jsonb,
  "enter_how_long_the_fast_breathing_lasted_in_months" jsonb,
  "how_long_did_the_fast_breathing_last_2" jsonb,
  "did_you_see_the_lower_chest_wall_ribs_being_pulled_in_as_the_ch" jsonb,
  "did_his_her_breathing_sound_like_any_of_the_following" jsonb,
  "did_s_he_have_wheezing" jsonb,
  "during_the_illness_that_led_to_death_did_his_her_breathing_soun" jsonb,
  "did_s_he_have_chest_pain" jsonb,
  "was_the_chest_pain_severe" jsonb,
  "how_many_days_before_death_did_s_he_have_chest_pain" jsonb,
  "how_long_did_the_chest_pain_last" jsonb,
  "enter_how_long_the_chest_pain_lasted_in_hours" jsonb,
  "enter_how_long_the_chest_pain_lasted_in_days" jsonb,
  "did_s_he_have_diarrhoea" jsonb,
  "how_long_did_s_he_have_diarrhoea" jsonb,
  "enter_how_long_s_he_have_diarrhoea_in_days" jsonb,
  "enter_how_long_s_he_have_diarrhoea_in_months" jsonb,
  "for_how_many_days_did_s_he_have_diarrhoea" jsonb,
  "how_many_stools_did_the_baby_or_child_have_on_the_day_that_diar" jsonb,
  "how_many_days_before_death_did_the_diarrhoea_start" jsonb,
  "how_long_before_death_did_the_diarrhoea_start" jsonb,
  "enter_how_long_before_death_the_diarrhoea_started_in_days" jsonb,
  "enter_how_long_before_death_the_diarrhoea_started_in_months" jsonb,
  "did_the_diarrhoea_continue_until_death" jsonb,
  "at_any_time_during_the_final_illness_was_there_blood_in_the_sto" jsonb,
  "did_s_he_vomit" jsonb,
  "for_how_long_did_s_he_vomit" jsonb,
  "enter_how_long_before_death_s_he_vomited_in_days" jsonb,
  "enter_how_long_before_death_s_he_vomited_in_months" jsonb,
  "did_s_he_vomit_in_the_week_preceding_the_death" jsonb,
  "did_s_he_vomit_every_time_s_he_ate_and_or_drank" jsonb,
  "was_there_blood_in_the_vomit" jsonb,
  "was_the_vomit_black" jsonb,
  "did_s_he_have_abdominal_pain" jsonb,
  "was_the_abdominal_pain_severe" jsonb,
  "for_how_long_did_s_he_have_abdominal_pain" jsonb,
  "enter_how_long_s_he_had_abdominal_pain_in_hours" jsonb,
  "enter_how_long_s_he_had_abdominal_pain_in_days" jsonb,
  "enter_how_long_s_he_had_abdominal_pain_in_months" jsonb,
  "calculated_number_of_days_with_abdominal_pain" jsonb,
  "where_was_the_location_of_the_abdominal_pain" jsonb,
  "did_s_he_have_a_more_than_usually_protruding_abdomen" jsonb,
  "for_how_long_before_death_did_s_he_have_a_more_than_usually_pro" jsonb,
  "enter_how_long_before_death_s_he_had_a_more_than_usually_protru" jsonb,
  "enter_how_long_before_death_s_he_had_a_more_than_usually_prot_2" jsonb,
  "calculated_number_of_days_with_protruding_abdomen" jsonb,
  "how_rapidly_did_s_he_develop_the_protruding_abdomen" jsonb,
  "did_s_he_have_any_mass_in_the_abdomen" jsonb,
  "for_how_long_did_s_he_have_a_mass_in_the_abdomen" jsonb,
  "enter_how_long_s_he_had_a_mass_in_the_abdomen_in_days" jsonb,
  "enter_how_long_s_he_had_a_mass_in_the_abdomen_in_months" jsonb,
  "calculated_number_of_days_with_a_mass_in_the_abdomen" jsonb,
  "did_s_he_have_a_severe_headache" jsonb,
  "did_s_he_have_a_stiff_or_painful_neck" jsonb,
  "how_long_before_death_did_s_he_have_a_stiff_or_painful_neck" jsonb,
  "enter_how_long_before_death_did_s_he_have_stiff_or_painful_neck" jsonb,
  "enter_how_long_before_death_did_s_he_have_stiff_or_painful_ne_2" jsonb,
  "for_how_many_days_before_death_did_s_he_have_stiff_or_painful_n" jsonb,
  "did_s_he_have_mental_confusion" jsonb,
  "how_long_did_s_he_have_mental_confusion" jsonb,
  "enter_how_long_s_he_had_mental_confusion_in_days" jsonb,
  "enter_how_long_s_he_had_mental_confusion_in_months" jsonb,
  "for_how_many_months_did_s_he_have_mental_confusion" jsonb,
  "was_s_he_unconscious" jsonb,
  "how_long_before_death_did_unconsciousness_start" jsonb,
  "enter_how_long_before_death_unconsciousness_started_in_hours" jsonb,
  "enter_how_long_before_death_unconsciousness_started_in_days" jsonb,
  "how_many_hours_before_death_did_unconsciousness_start" jsonb,
  "did_the_unconsciousness_start_suddenly_quickly_at_least_within" jsonb,
  "did_s_he_experience_any_generalized_convulsions" jsonb,
  "did_s_he_become_unconscious_immediately_after_the_convulsion" jsonb,
  "did_the_baby_have_convulsions_starting_within_the_first_24_hour" jsonb,
  "did_the_baby_have_convulsions_starting_more_than_24_hours_after" jsonb,
  "did_s_he_have_any_urine_problems" jsonb,
  "during_the_final_illness_did_s_he_ever_pass_blood_in_the_urine" jsonb,
  "did_s_he_stop_urinating" jsonb,
  "did_s_he_have_an_ulcer_on_the_foot" jsonb,
  "did_the_ulcer_on_the_foot_have_pus" jsonb,
  "how_long_did_the_ulcer_on_the_foot_have_pus" jsonb,
  "enter_how_long_the_ulcer_on_the_foot_had_pus_in_days" jsonb,
  "enter_how_long_the_ulcer_on_the_foot_had_pus_in_months" jsonb,
  "for_how_many_days_did_the_ulcer_on_the_foot_ooze_pus" jsonb,
  "did_s_he_have_ulcers_or_sores_anywhere_else_on_the_body" jsonb,
  "did_the_ulcers_or_sores_have_pus" jsonb,
  "did_s_he_have_any_skin_rash" jsonb,
  "for_how_many_days_did_s_he_have_the_skin_rash" jsonb,
  "where_was_the_rash" jsonb,
  "did_s_he_have_measles_rash" jsonb,
  "did_s_he_ever_have_shingles_or_herpes_zoster" jsonb,
  "did_her_his_skin_flake_off_in_patches" jsonb,
  "did_he_she_have_areas_of_the_skin_that_turned_black" jsonb,
  "did_he_she_have_areas_of_the_skin_with_redness_and_swelling" jsonb,
  "did_s_he_bleed_from_the_nose_mouth_or_anus" jsonb,
  "did_s_he_have_noticeable_weight_loss" jsonb,
  "was_s_he_severely_thin_or_wasted" jsonb,
  "did_s_he_have_a_whitish_rash_inside_the_mouth_or_on_the_tongue" jsonb,
  "did_s_he_have_stiffness_of_the_whole_body_or_was_unable_to_open" jsonb,
  "did_s_he_have_puffiness_of_the_face" jsonb,
  "how_long_did_s_he_have_puffiness_of_the_face" jsonb,
  "enter_how_long_s_he_had_puffiness_of_the_face_in_days" jsonb,
  "enter_how_long_s_he_had_puffiness_of_the_face_in_months" jsonb,
  "for_how_many_days_did_s_he_have_puffiness_of_the_face" jsonb,
  "did_s_he_have_swollen_legs_or_feet" jsonb,
  "how_long_did_the_swelling_last" jsonb,
  "enter_how_long_the_swelling_lasted_in_days" jsonb,
  "enter_how_long_the_swelling_lasted_in_months" jsonb,
  "how_many_days_did_the_swelling_last" jsonb,
  "did_s_he_have_both_feet_swollen" jsonb,
  "did_s_he_have_general_swelling_of_the_body" jsonb,
  "did_s_he_have_any_lumps_or_sores_in_the_mouth" jsonb,
  "did_s_he_have_lumps_anywhere_else_on_the_body" jsonb,
  "did_s_he_have_any_lumps_on_the_neck" jsonb,
  "did_s_he_have_any_lumps_on_the_armpit" jsonb,
  "did_s_he_have_any_lumps_on_the_groin" jsonb,
  "was_s_he_in_any_way_paralysed" jsonb,
  "did_s_he_have_paralysis_of_only_one_side_of_the_body" jsonb,
  "did_she_have_paralysis_of_both_legs" jsonb,
  "was_there_difficulty_or_pain_in_swallowing" jsonb,
  "for_how_long_did_s_he_have_difficulty_or_pain_in_swallowing" jsonb,
  "enter_how_long_before_death_s_he_had_difficulty_or_pain_in_swal" jsonb,
  "enter_how_long_before_death_s_he_had_difficulty_or_pain_in_sw_2" jsonb,
  "for_how_many_days_before_death_did_s_he_have_difficulty_swallow" jsonb,
  "did_swallowing_become_impossible" jsonb,
  "did_s_he_have_yellow_discoloration_of_the_eyes" jsonb,
  "for_how_long_did_s_he_have_the_yellow_discoloration" jsonb,
  "enter_how_long_s_he_had_the_yellow_discoloration_in_days" jsonb,
  "enter_how_long_s_he_had_the_yellow_discoloration_in_months" jsonb,
  "for_how_many_days_did_s_he_have_the_yellow_discoloration" jsonb,
  "did_her_his_hair_change_in_color_to_a_reddish_or_yellowish_colo" jsonb,
  "did_s_he_look_pale_or_have_pale_palms_eyes_or_nail_beds" jsonb,
  "did_s_he_have_sunken_eyes" jsonb,
  "was_the_baby_able_to_suckle_or_bottle_feed_within_the_first_24" jsonb,
  "did_the_baby_ever_suckle_in_a_normal_way" jsonb,
  "did_the_baby_stop_suckling" jsonb,
  "how_many_days_after_birth_did_the_baby_stop_suckling" jsonb,
  "how_long_after_birth_did_the_baby_stop_suckling" jsonb,
  "enter_how_long_after_birth_the_baby_stopped_suckling_in_days" jsonb,
  "enter_how_long_after_birth_the_baby_stopped_suckling_in_months" jsonb,
  "how_many_days_after_birth_did_the_baby_stop_suckling_2" jsonb,
  "did_the_baby_s_body_become_stiff_with_the_back_arched_backwards" jsonb,
  "did_the_baby_have_a_bulging_or_raised_fontanelle" jsonb,
  "did_the_baby_have_a_sunken_fontanelle" jsonb,
  "did_the_baby_become_unresponsive_or_unconscious" jsonb,
  "did_the_baby_become_unresponsive_or_unconscious_within_24_hours" jsonb,
  "did_the_baby_become_unresponsive_or_unconscious_more_than_24_ho" jsonb,
  "did_the_baby_become_cold_to_touch" jsonb,
  "did_the_baby_become_lethargic_after_a_period_of_normal_activity" jsonb,
  "did_the_baby_have_redness_or_pus_oozing_from_the_umbilical_cord" jsonb,
  "did_the_baby_have_skin_ulcer_s_or_sore_s" jsonb,
  "did_the_baby_have_yellow_skin_palms_or_soles" jsonb,
  "did_s_h_e_suffer_from_extreme_fatigue" jsonb,
  "did_s_he_experience_a_new_loss_change_or_decreased_sense_of_sme" jsonb,
  "did_she_have_any_lump_s_and_or_ulcer_s_in_the_breast" jsonb,
  "did_she_ever_have_a_period_or_menstruate" jsonb,
  "did_her_menstrual_period_stop_naturally_because_of_menopause" jsonb,
  "did_she_have_vaginal_bleeding_after_cessation_of_menstruation" jsonb,
  "was_there_excessive_vaginal_bleeding_in_the_week_prior_to_death" jsonb,
  "at_the_time_of_death_was_her_period_overdue" jsonb,
  "for_how_many_weeks_had_her_period_been_overdue" jsonb,
  "was_she_pregnant_and_not_yet_in_labour_at_the_time_of_death" jsonb,
  "did_she_die_during_labour_or_delivery" jsonb,
  "did_she_die_after_delivering_a_baby" jsonb,
  "did_she_die_within_24_hours_after_delivery" jsonb,
  "did_she_die_within_6_weeks_after_delivery" jsonb,
  "did_she_have_a_pregnancy_that_ended_in_an_abortion_or_miscarria" jsonb,
  "did_she_attempt_to_terminate_the_pregnancy" jsonb,
  "did_she_die_less_than_1_year_after_delivery_abortion_or_miscarr" jsonb,
  "please_confirm_that_in_the_12_months_prior_to_her_death_the_wom" jsonb,
  "did_she_have_a_sharp_abdominal_pain_in_the_first_3_months_of_pr" jsonb,
  "did_she_faint_when_she_had_the_sharp_abdominal_pain" jsonb,
  "for_how_many_months_was_she_pregnant" jsonb,
  "how_many_babies_was_she_pregnant_with" jsonb,
  "during_pregnancy_did_she_suffer_from_high_blood_pressure" jsonb,
  "did_she_have_foul_smelling_vaginal_discharge_during_pregnancy" jsonb,
  "did_bleeding_occur_while_she_was_pregnant" jsonb,
  "was_there_vaginal_bleeding_during_the_last_3_months_of_pregnanc" jsonb,
  "did_she_suffer_from_convulsions_during_the_last_3_months_of_pre" jsonb,
  "did_she_have_blurred_vision_during_the_last_3_months_of_pregnan" jsonb,
  "did_she_have_excessive_bleeding_during_labour_or_delivery" jsonb,
  "did_she_have_excessive_bleeding_after_delivery" jsonb,
  "did_she_have_excessive_bleeding_during_or_after_abortion_or_mis" jsonb,
  "did_she_have_foul_smelling_vaginal_discharge_after_delivery_abo" jsonb,
  "did_she_deliver_or_try_to_deliver_an_abnormally_positioned_baby" jsonb,
  "for_how_many_hours_was_she_in_labour" jsonb,
  "was_the_delivery_normal_vaginal_without_forceps_or_vacuum" jsonb,
  "was_the_delivery_vaginal_with_forceps_or_vacuum" jsonb,
  "was_the_delivery_a_caesarean_section" jsonb,
  "was_the_placenta_completely_delivered" jsonb,
  "where_did_she_give_birth" jsonb,
  "how_many_births_including_stillbirths_did_she_the_mother_have_b" jsonb,
  "had_she_had_any_previous_caesarean_section" jsonb,
  "did_she_have_an_operation_to_remove_her_uterus_shortly_before_d" jsonb,
  "was_the_child_part_of_a_multiple_birth" jsonb,
  "is_the_child_health_card_is_available" jsonb,
  "enter_the_birth_weight_from_the_card_record_the_weight_in_gramm" jsonb,
  "what_was_the_weight_in_grammes_of_the_deceased_at_birth" jsonb,
  "at_birth_was_the_baby_smaller_than_usual_weighing_under_2_5_kg" jsonb,
  "at_birth_was_the_baby_larger_than_usual_weighing_over_4_5_kg" jsonb,
  "how_many_months_long_was_the_pregnancy_before_the_child_was_bor" jsonb,
  "were_there_any_complications_during_labour_or_delivery" jsonb,
  "was_any_part_of_the_baby_physically_abnormal_at_time_of_deliver" jsonb,
  "did_the_baby_child_have_a_swelling_or_defect_on_the_back_at_tim" jsonb,
  "did_the_baby_child_have_a_very_large_head_at_time_of_birth" jsonb,
  "did_the_baby_child_have_a_very_small_head_at_time_of_birth" jsonb,
  "how_many_hours_did_labour_and_delivery_take" jsonb,
  "was_the_baby_born_24_hours_or_more_after_the_water_broke" jsonb,
  "was_the_liquor_foul_smelling" jsonb,
  "what_was_the_colour_of_the_liquor_when_the_waters_broke" jsonb,
  "was_the_delivery_normal_vaginal_without_forceps_or_vacuum_2" jsonb,
  "was_the_delivery_vaginal_with_forceps_or_vacuum_2" jsonb,
  "was_the_delivery_a_caesarean_section_2" jsonb,
  "did_you_the_baby_s_mother_receive_any_vaccinations_since_reachi" jsonb,
  "did_you_the_baby_s_mother_receive_tetanus_toxoid_tt_vaccine" jsonb,
  "during_labour_did_the_you_the_baby_s_mother_suffer_from_fever" jsonb,
  "during_the_last_3_months_of_pregnancy_labour_or_delivery_did_yo" jsonb,
  "did_you_the_baby_s_mother_have_diabetes_mellitus" jsonb,
  "did_you_the_baby_s_mother_have_foul_smelling_vaginal_discharge" jsonb,
  "during_the_last_3_months_of_pregnancy_labour_or_delivery_did_2" jsonb,
  "during_the_last_3_months_of_pregnancy_did_you_the_baby_s_mother" jsonb,
  "did_you_the_baby_s_mother_have_severe_anemia" jsonb,
  "did_you_the_baby_s_mother_have_vaginal_bleeding_during_the_last" jsonb,
  "did_the_baby_s_bottom_feet_arm_or_hand_come_out_of_the_vagina_b" jsonb,
  "was_the_umbilical_cord_wrapped_more_than_once_around_the_neck_o" jsonb,
  "was_the_umbilical_cord_delivered_first" jsonb,
  "was_the_baby_blue_in_colour_at_birth" jsonb,
  "did_s_he_drink_alcohol" jsonb,
  "did_s_he_ever_smoke_tobacco" jsonb,
  "for_how_long_did_s_he_smoke_tobacco" jsonb,
  "how_many_months_years" jsonb,
  "did_s_he_ever_smoke_daily" jsonb,
  "did_s_he_ever_chew_and_or_sniff_tobacco" jsonb,
  "for_how_long_did_s_he_chew_and_or_sniff_tobacco" jsonb,
  "how_many_months_years_2" jsonb,
  "did_s_he_ever_chew_and_or_sniff_tobacco_daily" jsonb,
  "did_s_he_receive_any_treatment_for_the_illness_that_led_to_deat" jsonb,
  "did_s_he_receive_oral_rehydration_salts" jsonb,
  "did_s_he_receive_or_need_intravenous_fluids_drip_treatment" jsonb,
  "did_s_he_receive_or_need_a_blood_transfusion" jsonb,
  "did_s_he_receive_or_need_treatment_food_through_a_tube_passed_t" jsonb,
  "did_s_he_receive_or_need_injectable_antibiotics" jsonb,
  "did_s_he_receive_or_need_antiretroviral_therapy_art" jsonb,
  "did_s_he_have_or_need_an_operation_for_the_illness" jsonb,
  "did_s_he_have_the_operation_within_1_month_before_death" jsonb,
  "did_a_health_care_worker_tell_you_the_cause_of_death" jsonb,
  "what_did_the_health_care_worker_say" jsonb,
  "has_the_deceased_s_biological_mother_ever_been_told_she_had_hiv" jsonb,
  "civil_registration_this_refers_to_the_legal_death_certificate_o" jsonb,
  "do_you_have_a_death_certificate_from_the_civil_registry" jsonb,
  "death_registration_number_certificate" jsonb,
  "is_the_date_of_registration_available" jsonb,
  "date_of_registration" jsonb,
  "place_of_registration" jsonb,
  "national_number_of_deceased" jsonb,
  "death_certificate_with_cause_of_death_this_refers_to_the_medica" jsonb,
  "was_a_medical_certificate_of_cause_of_death_issued" jsonb,
  "can_i_see_the_medical_certificate_of_cause_of_death" jsonb,
  "record_the_immediate_cause_of_death_from_the_certificate_line_1" jsonb,
  "duration_of_the_immediate_cause_of_death_ia" jsonb,
  "record_the_first_antecedent_cause_of_death_from_the_certificate" jsonb,
  "duration_of_the_first_antecedent_cause_of_death_ib" jsonb,
  "record_the_second_antecedent_cause_of_death_from_the_certificat" jsonb,
  "duration_of_second_antecedent_cause_of_death_ic" jsonb,
  "record_the_third_antecedent_cause_of_death_from_the_certificate" jsonb,
  "duration_of_third_antecedent_cause_of_death" jsonb,
  "record_the_contributing_cause_s_of_death_from_the_certificate_p" jsonb,
  "duration_of_the_contributing_cause_s_of_death_part2" jsonb,
  "end_time_of_the_interview" jsonb,
  "inform_the_respondent_that_the_va_interview_has_come_to_an_end" jsonb,
  "comment_comment" jsonb
);

comment on column who_va_instruments."audit" is 'audit';
comment on column who_va_instruments."name_of_va_interviewer" is 'Name of VA interviewer';
comment on column who_va_instruments."age_of_va_interviewer" is 'Age of VA interviewer';
comment on column who_va_instruments."sex_of_va_interviewer" is 'Sex of VA interviewer';
comment on column who_va_instruments."of_va_interviewer" is 'of VA interviewer';
comment on column who_va_instruments."interview_language" is 'Interview language';
comment on column who_va_instruments."is_this_a_region_of_high_hiv_aids_mortality" is 'Is this a region of high HIV/AIDS mortality?';
comment on column who_va_instruments."is_this_a_region_of_high_malaria_mortality" is 'Is this a region of high malaria mortality?';
comment on column who_va_instruments."during_which_season_did_s_he_die" is 'During which season did (s)he die?';
comment on column who_va_instruments."what_is_the_full_name_of_va_respondent" is 'What is the full name of VA respondent?';
comment on column who_va_instruments."what_is_the_sex_of_va_respondent" is 'What is the sex of VA respondent?';
comment on column who_va_instruments."what_is_the_age_of_va_respondent" is 'What is the age of VA respondent?';
comment on column who_va_instruments."what_is_your_the_respondent_s_relationship_to_the_deceased" is 'What is your/the respondent''s relationship to the deceased?';
comment on column who_va_instruments."did_you_the_respondent_live_with_the_deceased_in_the_period_lea" is 'Did you/the respondent live with the deceased in the period leading to her/his death?';
comment on column who_va_instruments."date_of_the_interview" is 'Date of the interview';
comment on column who_va_instruments."did_the_respondent_give_consent" is 'Did the respondent give consent?';
comment on column who_va_instruments."start_time_of_the_interview" is 'Start time of the interview';
comment on column who_va_instruments."what_was_the_first_or_given_name_s_of_the_deceased" is 'What was the first or given name(s) of the deceased?';
comment on column who_va_instruments."what_was_the_surname_s_or_family_name_s_of_the_deceased" is 'What was the surname(s) (or family name(s)) of the deceased?';
comment on column who_va_instruments."what_was_the_sex_of_the_deceased" is 'What was the sex of the deceased?';
comment on column who_va_instruments."is_the_date_of_birth_known" is 'Is the date of birth known?';
comment on column who_va_instruments."when_was_the_deceased_born" is 'When was the deceased born?';
comment on column who_va_instruments."is_the_date_of_death_known" is 'Is the date of death known?';
comment on column who_va_instruments."when_did_s_he_die" is 'When did (s)he die?';
comment on column who_va_instruments."when_did_s_he_die_2" is 'When did (s)he die?';
comment on column who_va_instruments."when_did_s_he_die_3" is 'When did (s)he die?';
comment on column who_va_instruments."please_indicate_the_year_of_death" is 'Please indicate the year of death.';
comment on column who_va_instruments."age_in_days" is 'Age in Days';
comment on column who_va_instruments."age_in_days_2" is 'Age in Days';
comment on column who_va_instruments."age_in_years" is 'Age in Years';
comment on column who_va_instruments."ageinyearsremain" is 'ageInYearsRemain';
comment on column who_va_instruments."age_in_months" is 'Age in Months';
comment on column who_va_instruments."ageinmonthsremain" is 'ageInMonthsRemain';
comment on column who_va_instruments."the_deceased_person_is_a_neonate" is 'The deceased person is a Neonate';
comment on column who_va_instruments."the_deceased_person_is_a_child" is 'The deceased person is a Child';
comment on column who_va_instruments."the_deceased_person_is_an_adult" is 'The deceased person is an Adult';
comment on column who_va_instruments."neonate_was_ageindays_days_old" is 'NEONATE was ${ageInDays} days old.';
comment on column who_va_instruments."child_was_ageinyears_years_ageinmonths_months_and_ageinmonthsre" is 'CHILD was ${ageInYears} years ${ageInMonths} months and ${ageInMonthsRemain} days old.';
comment on column who_va_instruments."adult_was_ageinyears_years_old" is 'ADULT was ${ageInYears} years old.';
comment on column who_va_instruments."what_age_group_corresponds_to_the_deceased" is 'What age group corresponds to the deceased?';
comment on column who_va_instruments."how_many_days_old_was_the_baby_enter_neonate_s_age_in_days" is 'How many days old was the baby? Enter neonate''s age in days:';
comment on column who_va_instruments."how_many_hours_was_the_baby_alive" is 'How many hours was the baby alive?';
comment on column who_va_instruments."how_old_was_the_child_enter_child_s_age_in" is 'How old was the child? Enter child''s age in:';
comment on column who_va_instruments."enter_child_s_age_in_days" is 'Enter child''s age in days:';
comment on column who_va_instruments."enter_child_s_age_in_months" is 'Enter child''s age in months:';
comment on column who_va_instruments."enter_child_s_age_in_years" is 'Enter child''s age in years:';
comment on column who_va_instruments."enter_adult_s_age_in_years" is 'Enter adult''s age in years:';
comment on column who_va_instruments."age_in_months_2" is 'Age in Months';
comment on column who_va_instruments."age_in_years_2" is 'Age in Years';
comment on column who_va_instruments."the_deceased_person_is_a_neonate_2" is 'The deceased person is a Neonate';
comment on column who_va_instruments."the_deceased_person_is_a_child_2" is 'The deceased person is a Child';
comment on column who_va_instruments."the_deceased_person_is_an_adult_2" is 'The deceased person is an Adult';
comment on column who_va_instruments."the_deceased_person_is_a_neonate_3" is 'The deceased person is a Neonate';
comment on column who_va_instruments."the_deceased_person_is_a_child_3" is 'The deceased person is a Child';
comment on column who_va_instruments."the_deceased_person_is_an_adult_3" is 'The deceased person is an Adult';
comment on column who_va_instruments."age_in_days_3" is 'Age in days';
comment on column who_va_instruments."it_is_not_possible_to_select_that_the_respondent_is_the_child_o" is 'It is not possible to select that the respondent is the child of the deceased and enter that the deceased is a neonate or child. Please go back and correct the selection.';
comment on column who_va_instruments."where_did_the_deceased_die" is 'Where did the deceased die?';
comment on column who_va_instruments."in_the_two_weeks_before_death_did_s_he_live_with_visit_or_care" is 'In the two weeks before death, did (s)he live with, visit, or care for someone who had any COVID-19 symptoms or a positive COVID-19 test?';
comment on column who_va_instruments."is_there_a_need_to_collect_additional_demographic_data_on_the_d" is 'Is there a need to collect additional demographic data on the deceased?';
comment on column who_va_instruments."what_was_her_his_citizenship_nationality" is 'What was her/his citizenship/nationality?';
comment on column who_va_instruments."what_was_her_his_ethnicity" is 'What was her/his ethnicity?';
comment on column who_va_instruments."what_was_her_his_place_of_birth" is 'What was her/his place of birth?';
comment on column who_va_instruments."what_was_her_his_place_of_usual_residence_the_place_where_the_p" is 'What was her/his place of usual residence? (the place where the person lived most of the year)';
comment on column who_va_instruments."where_did_the_death_occur_specify_country_province_district_vil" is 'Where did the death occur? (specify country, province, district, village)';
comment on column who_va_instruments."what_was_her_his_marital_status" is 'What was her/his marital status?';
comment on column who_va_instruments."what_was_her_his_highest_level_of_schooling" is 'What was her/his highest level of schooling?';
comment on column who_va_instruments."was_s_he_able_to_read_and_or_write" is 'Was (s)he able to read and/or write?';
comment on column who_va_instruments."what_was_her_his_economic_activity_status_in_year_prior_to_deat" is 'What was her/his economic activity status in year prior to death?';
comment on column who_va_instruments."what_was_her_his_occupation_that_is_what_kind_of_work_did_s_he" is 'What was her/his occupation, that is, what kind of work did (s)he mainly do?';
comment on column who_va_instruments."what_was_the_full_name_of_the_father" is 'What was the full name of the father?';
comment on column who_va_instruments."what_was_the_full_name_of_the_mother" is 'What was the full name of the mother?';
comment on column who_va_instruments."record_detailed_notes_of_response_or_audio_record_the_response" is 'Record detailed notes of response or audio record the response if the option is available. If needed, probe the respondent for additional details on when the deceased recognized symptoms, abnormalities, care sought, etc. Ask the respondent if any medical records from the time preceding death are available and record any relevant information. Some of the following questions may be repetetive or irrelevant to the respondent but they are very important in the COD assignment process.';
comment on column who_va_instruments."thank_you_for_your_information_now_can_you_please_tell_me_in_yo" is 'Thank you for your information. Now can you please tell me in your own words about the events that led to the death?';
comment on column who_va_instruments."thank_you_for_your_information_now_can_you_please_tell_me_in_2" is 'Thank you for your information. Now can you please tell me in your own words about the events that led to the death?';
comment on column who_va_instruments."select_any_of_the_following_words_that_were_mentioned_as_presen" is 'Select any of the following words that were mentioned as present in the narrative.';
comment on column who_va_instruments."select_any_of_the_following_words_that_were_mentioned_as_pres_2" is 'Select any of the following words that were mentioned as present in the narrative.';
comment on column who_va_instruments."select_any_of_the_following_words_that_were_mentioned_as_pres_3" is 'Select any of the following words that were mentioned as present in the narrative.';
comment on column who_va_instruments."some_of_the_following_questions_may_be_repetetive_or_irrelevant" is 'Some of the following questions may be repetetive or irrelevant to the respondent but they are very important in the COD assignment process.';
comment on column who_va_instruments."did_the_baby_ever_cry" is 'Did the baby ever cry?';
comment on column who_va_instruments."did_the_baby_cry_immediately_after_birth_even_if_only_a_little" is 'Did the baby cry immediately after birth, even if only a little bit?';
comment on column who_va_instruments."how_many_minutes_after_birth_did_the_baby_first_cry" is 'How many minutes after birth did the baby first cry?';
comment on column who_va_instruments."did_the_baby_stop_being_able_to_cry" is 'Did the baby stop being able to cry?';
comment on column who_va_instruments."did_the_baby_stop_moving_in_the_womb" is 'Did the baby stop moving in the womb?';
comment on column who_va_instruments."did_the_baby_stop_moving_before_or_after_the_onset_of_labour" is 'Did the baby stop moving before or after the onset of labour?';
comment on column who_va_instruments."did_the_baby_ever_move_after_being_delivered" is 'Did the baby ever move after being delivered?';
comment on column who_va_instruments."did_the_baby_ever_breathe" is 'Did the baby ever breathe?';
comment on column who_va_instruments."did_the_baby_breathe_immediately_after_birth_even_a_little" is 'Did the baby breathe immediately after birth, even a little?';
comment on column who_va_instruments."did_the_baby_have_a_breathing_problem" is 'Did the baby have a breathing problem?';
comment on column who_va_instruments."was_the_baby_given_assistance_to_breathe_at_birth" is 'Was the baby given assistance to breathe at birth?';
comment on column who_va_instruments."if_the_baby_didn_t_show_any_sign_of_life_was_it_born_dead" is 'If the baby didn''t show any sign of life, was it born dead?';
comment on column who_va_instruments."were_there_any_bruises_or_signs_of_injury_on_baby_s_body_after" is 'Were there any bruises or signs of injury on baby''s body after the birth?';
comment on column who_va_instruments."was_the_baby_s_body_soft_discoloured_and_the_skin_peeling_away" is 'Was the baby''s body soft, discoloured and the skin peeling away?';
comment on column who_va_instruments."explain_to_the_respondent_that_the_following_section_contains_a" is 'Explain to the respondent that the following section contains a series of questions on whether diagnosis from a health professional was obtained for a number of illnesses. Clarify that the aim of this series is on medical diagnosis of specific illnesses, and not on signs and symptoms or the perceived cause of death by the respondent.';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_tuberculosi" is 'Was there any diagnosis by a health professional of tuberculosis?';
comment on column who_va_instruments."was_an_hiv_test_ever_positive" is 'Was an HIV test ever positive?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_aids" is 'Was there any diagnosis by a health professional of AIDS?';
comment on column who_va_instruments."did_s_he_have_a_recent_positive_test_by_a_health_professional_f" is 'Did (s)he have a recent positive test by a health professional for malaria?';
comment on column who_va_instruments."did_s_he_have_a_recent_negative_test_by_a_health_professional_f" is 'Did (s)he have a recent negative test by a health professional for malaria?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_covid_19" is 'Was there any diagnosis by a health professional of COVID-19?';
comment on column who_va_instruments."did_s_h_e_have_a_recent_test_for_covid_19" is 'Did s(h)e have a recent test for COVID-19?';
comment on column who_va_instruments."what_was_the_result" is 'What was the result?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_dengue_feve" is 'Was there any diagnosis by a health professional of dengue fever?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_measles" is 'Was there any diagnosis by a health professional of measles?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_high_blood" is 'Was there any diagnosis by a health professional of high blood pressure?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_heart_disea" is 'Was there any diagnosis by a health professional of heart disease?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_diabetes" is 'Was there any diagnosis by a health professional of diabetes?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_asthma" is 'Was there any diagnosis by a health professional of asthma?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_epilepsy" is 'Was there any diagnosis by a health professional of epilepsy?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_cancer" is 'Was there any diagnosis by a health professional of cancer?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_chronic_obs" is 'Was there any diagnosis by a health professional of Chronic Obstructive Pulmonary Disease (COPD)?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_dementia" is 'Was there any diagnosis by a health professional of dementia?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_depression" is 'Was there any diagnosis by a health professional of depression?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_stroke" is 'Was there any diagnosis by a health professional of stroke?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_sickle_cell" is 'Was there any diagnosis by a health professional of sickle cell disease?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_kidney_dise" is 'Was there any diagnosis by a health professional of kidney disease?';
comment on column who_va_instruments."was_there_any_diagnosis_by_a_health_professional_of_liver_disea" is 'Was there any diagnosis by a health professional of liver disease?';
comment on column who_va_instruments."unless_specified_the_following_questions_on_signs_symptoms_trea" is 'Unless specified, the following questions on signs, symptoms, treatment and circumstances relate specifically to the illness and the period of illness that led to death.';
comment on column who_va_instruments."did_s_he_suffer_from_any_injury_or_accident_that_led_to_her_his" is 'Did (s)he suffer from any injury or accident that led to her/his death?';
comment on column who_va_instruments."how_long_after_the_injury_or_accident_did_s_he_die" is 'How long after the injury or accident did s/he die?';
comment on column who_va_instruments."interviewer_click_ok_to_confirm_the_answer_she_died_less_than_o" is 'Interviewer click "OK" to confirm the answer: She/died less than or equal to 7 days after the accident';
comment on column who_va_instruments."was_it_a_road_transport_injury" is 'Was it a road transport injury?';
comment on column who_va_instruments."was_it_a_non_road_transport_injury" is 'Was it a non-road transport injury?';
comment on column who_va_instruments."was_s_he_injured_in_a_fall" is 'Was (s)he injured in a fall?';
comment on column who_va_instruments."was_there_any_poisoning" is 'Was there any poisoning?';
comment on column who_va_instruments."did_s_he_die_of_drowning" is 'Did (s)he die of drowning?';
comment on column who_va_instruments."was_s_he_injured_by_a_venomous_bite_or_sting_from_an_animal_or" is 'Was (s)he injured by a venomous bite or sting from an animal or insect?';
comment on column who_va_instruments."was_s_he_injured_by_an_animal_or_insect_non_venomous" is 'Was (s)he injured by an animal or insect (non-venomous)?';
comment on column who_va_instruments."what_was_the_animal_insect" is 'What was the animal/insect?';
comment on column who_va_instruments."was_s_he_injured_by_burns_fire" is 'Was (s)he injured by burns/fire?';
comment on column who_va_instruments."was_s_he_injured_by_a_firearm" is 'Was (s)he injured by a firearm?';
comment on column who_va_instruments."was_s_he_stabbed_cut_or_pierced" is 'Was (s)he stabbed, cut or pierced?';
comment on column who_va_instruments."was_s_he_strangled" is 'Was (s)he strangled?';
comment on column who_va_instruments."was_s_h_e_electrocuted" is 'Was s(h)e electrocuted?';
comment on column who_va_instruments."was_s_he_injured_by_a_blunt_force" is 'Was (s)he injured by a blunt force?';
comment on column who_va_instruments."was_s_he_injured_by_a_force_of_nature" is 'Was (s)he injured by a force of nature?';
comment on column who_va_instruments."did_s_he_suffer_any_other_injury" is 'Did (s)he suffer any other injury?';
comment on column who_va_instruments."was_the_injury_accidental" is 'Was the injury accidental?';
comment on column who_va_instruments."was_the_injury_self_inflicted" is 'Was the injury self-inflicted?';
comment on column who_va_instruments."was_the_injury_intentionally_inflicted_by_someone_else" is 'Was the injury intentionally inflicted by someone else?';
comment on column who_va_instruments."how_many_days_old_was_the_baby_when_the_fatal_illness_started" is 'How many days old was the baby when the fatal illness started?';
comment on column who_va_instruments."before_the_illness_that_led_to_death_was_the_baby_the_child_gro" is 'Before the illness that led to death, was the baby/the child growing normally?';
comment on column who_va_instruments."for_how_many_days_was_s_he_ill_before_death" is '( ) For how many days was (s)he ill before death?';
comment on column who_va_instruments."for_how_long_was_s_he_ill_before_death" is 'For how long was (s)he ill before death?';
comment on column who_va_instruments."months" is 'Months';
comment on column who_va_instruments."years" is 'Years';
comment on column who_va_instruments."days" is '( ) Days';
comment on column who_va_instruments."calculated_number_of_days_with_illness" is 'Calculated number of Days with illness';
comment on column who_va_instruments."did_s_he_die_suddenly" is 'Did (s)he die suddenly?';
comment on column who_va_instruments."did_s_he_have_a_fever" is 'Did (s)he have a fever?';
comment on column who_va_instruments."how_many_days_did_the_fever_last" is 'How many days did the fever last?';
comment on column who_va_instruments."how_long_did_the_fever_last" is 'How long did the fever last?';
comment on column who_va_instruments."enter_how_long_the_fever_lasted_in_days" is 'Enter how long the fever lasted in days :';
comment on column who_va_instruments."enter_how_long_the_fever_lasted_in_months" is 'Enter how long the fever lasted in months :';
comment on column who_va_instruments."how_many_days_did_the_fever_last_2" is 'How many days did the fever last?';
comment on column who_va_instruments."did_the_fever_continue_until_death" is 'Did the fever continue until death?';
comment on column who_va_instruments."how_severe_was_the_fever" is 'How severe was the fever?';
comment on column who_va_instruments."what_was_the_pattern_of_the_fever" is 'What was the pattern of the fever?';
comment on column who_va_instruments."did_s_he_have_a_cough" is 'Did (s)he have a cough?';
comment on column who_va_instruments."for_how_long_did_s_he_have_a_cough" is 'For how long did (s)he have a cough?';
comment on column who_va_instruments."enter_how_long_s_he_had_a_cough_in_days" is 'Enter how long (s)he had a cough in days :';
comment on column who_va_instruments."enter_how_long_s_he_had_a_cough_in_months" is 'Enter how long (s)he had a cough in months :';
comment on column who_va_instruments."for_how_many_days_did_s_he_have_a_cough" is 'For how many days did (s)he have a cough?';
comment on column who_va_instruments."was_the_cough_productive_with_sputum" is 'Was the cough productive, with sputum?';
comment on column who_va_instruments."was_the_cough_very_severe" is 'Was the cough very severe?';
comment on column who_va_instruments."did_s_he_cough_up_blood" is 'Did (s)he cough up blood?';
comment on column who_va_instruments."did_s_he_make_a_whooping_sound_when_coughing" is 'Did (s)he make a whooping sound when coughing?';
comment on column who_va_instruments."did_s_he_have_any_difficulty_breathing_or_breathlessness" is 'Did s/he have any difficulty breathing or breathlessness?';
comment on column who_va_instruments."for_how_many_days_did_the_difficulty_breathing_or_breathlessnes" is '( ) For how many days did the difficulty breathing or breathlessness last?';
comment on column who_va_instruments."for_how_long_did_the_difficulty_breathing_or_breathlessness_las" is 'For how long did the difficulty breathing or breathlessness last?';
comment on column who_va_instruments."enter_how_long_the_difficult_breathing_or_breathlessness_lasted" is '( ) Enter how long the difficult breathing or breathlessness lasted in days :';
comment on column who_va_instruments."enter_how_long_the_difficult_breathing_or_breathlessness_last_2" is 'Enter how long the difficult breathing or breathlessness lasted in months :';
comment on column who_va_instruments."enter_how_long_the_difficult_breathing_or_breathlessness_last_3" is 'Enter how long the difficult breathing or breathlessness lasted in years :';
comment on column who_va_instruments."calculated_number_of_days_with_illness_2" is 'Calculated number of Days with illness';
comment on column who_va_instruments."was_the_difficulty_in_breathing_continuous_or_on_and_off" is 'Was the difficulty in breathing continuous or on and off?';
comment on column who_va_instruments."was_s_he_unable_to_carry_out_daily_routines_due_to_breathlessne" is 'Was (s)he unable to carry out daily routines due to breathlessness?';
comment on column who_va_instruments."was_s_he_breathless_while_lying_flat" is 'Was (s)he breathless while lying flat?';
comment on column who_va_instruments."did_s_he_have_fast_breathing" is 'Did (s)he have fast breathing?';
comment on column who_va_instruments."for_how_many_days_did_the_fast_breathing_last" is 'For how many days did the fast breathing last?';
comment on column who_va_instruments."how_long_did_the_fast_breathing_last" is 'How long did the fast breathing last?';
comment on column who_va_instruments."enter_how_long_the_fast_breathing_lasted_in_days" is 'Enter how long the fast breathing lasted in days :';
comment on column who_va_instruments."enter_how_long_the_fast_breathing_lasted_in_months" is 'Enter how long the fast breathing lasted in months :';
comment on column who_va_instruments."how_long_did_the_fast_breathing_last_2" is 'How long did the fast breathing last?';
comment on column who_va_instruments."did_you_see_the_lower_chest_wall_ribs_being_pulled_in_as_the_ch" is 'Did you see the lower chest wall/ribs being pulled in as the child breathed in (chest in-drawing)?';
comment on column who_va_instruments."did_his_her_breathing_sound_like_any_of_the_following" is 'Did his/her breathing sound like any of the following:';
comment on column who_va_instruments."did_s_he_have_wheezing" is 'Did (s)he have wheezing?';
comment on column who_va_instruments."during_the_illness_that_led_to_death_did_his_her_breathing_soun" is 'During the illness that led to death did his/her breathing sound like any of the following:';
comment on column who_va_instruments."did_s_he_have_chest_pain" is 'Did (s)he have chest pain?';
comment on column who_va_instruments."was_the_chest_pain_severe" is 'Was the chest pain severe?';
comment on column who_va_instruments."how_many_days_before_death_did_s_he_have_chest_pain" is 'How many days before death did (s)he have chest pain?';
comment on column who_va_instruments."how_long_did_the_chest_pain_last" is 'How long did the chest pain last?';
comment on column who_va_instruments."enter_how_long_the_chest_pain_lasted_in_hours" is 'Enter how long the chest pain lasted in hours :';
comment on column who_va_instruments."enter_how_long_the_chest_pain_lasted_in_days" is '( ) Enter how long the chest pain lasted in days :';
comment on column who_va_instruments."did_s_he_have_diarrhoea" is 'Did (s)he have diarrhoea?';
comment on column who_va_instruments."how_long_did_s_he_have_diarrhoea" is 'How long did (s)he have diarrhoea?';
comment on column who_va_instruments."enter_how_long_s_he_have_diarrhoea_in_days" is 'Enter how long (s)he have diarrhoea in days :';
comment on column who_va_instruments."enter_how_long_s_he_have_diarrhoea_in_months" is 'Enter how long (s)he have diarrhoea in months :';
comment on column who_va_instruments."for_how_many_days_did_s_he_have_diarrhoea" is 'For how many days did (s)he have diarrhoea?';
comment on column who_va_instruments."how_many_stools_did_the_baby_or_child_have_on_the_day_that_diar" is 'How many stools did the baby or child have on the day that diarrhoea was most frequent?';
comment on column who_va_instruments."how_many_days_before_death_did_the_diarrhoea_start" is 'How many days before death did the diarrhoea start?';
comment on column who_va_instruments."how_long_before_death_did_the_diarrhoea_start" is 'How long before death did the diarrhoea start?';
comment on column who_va_instruments."enter_how_long_before_death_the_diarrhoea_started_in_days" is 'Enter how long before death the diarrhoea started in days :';
comment on column who_va_instruments."enter_how_long_before_death_the_diarrhoea_started_in_months" is 'Enter how long before death the diarrhoea started in months :';
comment on column who_va_instruments."did_the_diarrhoea_continue_until_death" is 'Did the diarrhoea continue until death?';
comment on column who_va_instruments."at_any_time_during_the_final_illness_was_there_blood_in_the_sto" is 'At any time during the final illness was there blood in the stools?';
comment on column who_va_instruments."did_s_he_vomit" is 'Did (s)he vomit?';
comment on column who_va_instruments."for_how_long_did_s_he_vomit" is 'For how long did (s)he vomit?';
comment on column who_va_instruments."enter_how_long_before_death_s_he_vomited_in_days" is 'Enter how long before death(s)he vomited in days :';
comment on column who_va_instruments."enter_how_long_before_death_s_he_vomited_in_months" is 'Enter how long before death(s)he vomited in months :';
comment on column who_va_instruments."did_s_he_vomit_in_the_week_preceding_the_death" is 'Did (s)he vomit in the week preceding the death?';
comment on column who_va_instruments."did_s_he_vomit_every_time_s_he_ate_and_or_drank" is '( ) Did s/he vomit every time s/he ate and/or drank?';
comment on column who_va_instruments."was_there_blood_in_the_vomit" is 'Was there blood in the vomit?';
comment on column who_va_instruments."was_the_vomit_black" is 'Was the vomit black?';
comment on column who_va_instruments."did_s_he_have_abdominal_pain" is 'Did (s)he have abdominal pain?';
comment on column who_va_instruments."was_the_abdominal_pain_severe" is 'Was the abdominal pain severe?';
comment on column who_va_instruments."for_how_long_did_s_he_have_abdominal_pain" is 'For how long did (s)he have abdominal pain?';
comment on column who_va_instruments."enter_how_long_s_he_had_abdominal_pain_in_hours" is 'Enter how long (s)he had abdominal pain in hours :';
comment on column who_va_instruments."enter_how_long_s_he_had_abdominal_pain_in_days" is 'Enter how long (s)he had abdominal pain in days :';
comment on column who_va_instruments."enter_how_long_s_he_had_abdominal_pain_in_months" is 'Enter how long (s)he had abdominal pain in months :';
comment on column who_va_instruments."calculated_number_of_days_with_abdominal_pain" is 'Calculated number of Days with abdominal pain';
comment on column who_va_instruments."where_was_the_location_of_the_abdominal_pain" is 'Where was the location of the abdominal pain?';
comment on column who_va_instruments."did_s_he_have_a_more_than_usually_protruding_abdomen" is 'Did (s)he have a more than usually protruding abdomen?';
comment on column who_va_instruments."for_how_long_before_death_did_s_he_have_a_more_than_usually_pro" is 'For how long before death did (s)he have a more than usually protruding abdomen?';
comment on column who_va_instruments."enter_how_long_before_death_s_he_had_a_more_than_usually_protru" is 'Enter how long before death (s)he had a more than usually protruding abdomen in days :';
comment on column who_va_instruments."enter_how_long_before_death_s_he_had_a_more_than_usually_prot_2" is 'Enter how long before death (s)he had a more than usually protruding abdomen in months :';
comment on column who_va_instruments."calculated_number_of_days_with_protruding_abdomen" is 'Calculated number of Days with protruding abdomen';
comment on column who_va_instruments."how_rapidly_did_s_he_develop_the_protruding_abdomen" is 'How rapidly did (s)he develop the protruding abdomen?';
comment on column who_va_instruments."did_s_he_have_any_mass_in_the_abdomen" is 'Did (s)he have any mass in the abdomen?';
comment on column who_va_instruments."for_how_long_did_s_he_have_a_mass_in_the_abdomen" is 'For how long did (s)he have a mass in the abdomen?';
comment on column who_va_instruments."enter_how_long_s_he_had_a_mass_in_the_abdomen_in_days" is 'Enter how long (s)he had a mass in the abdomen in days :';
comment on column who_va_instruments."enter_how_long_s_he_had_a_mass_in_the_abdomen_in_months" is 'Enter how long (s)he had a mass in the abdomen in months :';
comment on column who_va_instruments."calculated_number_of_days_with_a_mass_in_the_abdomen" is 'Calculated number of Days with a mass in the abdomen';
comment on column who_va_instruments."did_s_he_have_a_severe_headache" is 'Did (s)he have a severe headache?';
comment on column who_va_instruments."did_s_he_have_a_stiff_or_painful_neck" is 'Did s/he have a stiff or painful neck?';
comment on column who_va_instruments."how_long_before_death_did_s_he_have_a_stiff_or_painful_neck" is 'How long before death did s/he have a stiff or painful neck?';
comment on column who_va_instruments."enter_how_long_before_death_did_s_he_have_stiff_or_painful_neck" is 'Enter how long before death did (s)he have stiff or painful neck in days :';
comment on column who_va_instruments."enter_how_long_before_death_did_s_he_have_stiff_or_painful_ne_2" is 'Enter how long before death did (s)he have stiff or painful neck in months :';
comment on column who_va_instruments."for_how_many_days_before_death_did_s_he_have_stiff_or_painful_n" is 'For how many days before death did (s)he have stiff or painful neck?';
comment on column who_va_instruments."did_s_he_have_mental_confusion" is 'Did (s)he have mental confusion?';
comment on column who_va_instruments."how_long_did_s_he_have_mental_confusion" is 'How long did (s)he have mental confusion?';
comment on column who_va_instruments."enter_how_long_s_he_had_mental_confusion_in_days" is 'Enter how long (s)he had mental confusion in days :';
comment on column who_va_instruments."enter_how_long_s_he_had_mental_confusion_in_months" is 'Enter how long (s)he had mental confusion in months :';
comment on column who_va_instruments."for_how_many_months_did_s_he_have_mental_confusion" is 'For how many months did (s)he have mental confusion?';
comment on column who_va_instruments."was_s_he_unconscious" is 'Was (s)he unconscious?';
comment on column who_va_instruments."how_long_before_death_did_unconsciousness_start" is 'How long before death did unconsciousness start?';
comment on column who_va_instruments."enter_how_long_before_death_unconsciousness_started_in_hours" is 'Enter how long before death unconsciousness started in hours ?';
comment on column who_va_instruments."enter_how_long_before_death_unconsciousness_started_in_days" is 'Enter how long before death unconsciousness started in days ?';
comment on column who_va_instruments."how_many_hours_before_death_did_unconsciousness_start" is 'How many hours before death did unconsciousness start?';
comment on column who_va_instruments."did_the_unconsciousness_start_suddenly_quickly_at_least_within" is 'Did the unconsciousness start suddenly, quickly (at least within a single day)?';
comment on column who_va_instruments."did_s_he_experience_any_generalized_convulsions" is 'Did (s)he experience any generalized convulsions?';
comment on column who_va_instruments."did_s_he_become_unconscious_immediately_after_the_convulsion" is 'Did (s)he become unconscious immediately after the convulsion?';
comment on column who_va_instruments."did_the_baby_have_convulsions_starting_within_the_first_24_hour" is 'Did the baby have convulsions starting within the first 24 hours of life?';
comment on column who_va_instruments."did_the_baby_have_convulsions_starting_more_than_24_hours_after" is 'Did the baby have convulsions starting more than 24 hours after birth?';
comment on column who_va_instruments."did_s_he_have_any_urine_problems" is 'Did (s)he have any urine problems?';
comment on column who_va_instruments."during_the_final_illness_did_s_he_ever_pass_blood_in_the_urine" is 'During the final illness did (s)he ever pass blood in the urine?';
comment on column who_va_instruments."did_s_he_stop_urinating" is 'Did (s)he stop urinating?';
comment on column who_va_instruments."did_s_he_have_an_ulcer_on_the_foot" is 'Did (s)he have an ulcer on the foot?';
comment on column who_va_instruments."did_the_ulcer_on_the_foot_have_pus" is 'Did the ulcer on the foot have pus?';
comment on column who_va_instruments."how_long_did_the_ulcer_on_the_foot_have_pus" is 'How long did the ulcer on the foot have pus?';
comment on column who_va_instruments."enter_how_long_the_ulcer_on_the_foot_had_pus_in_days" is 'Enter how long the ulcer on the foot had pus in days :';
comment on column who_va_instruments."enter_how_long_the_ulcer_on_the_foot_had_pus_in_months" is 'Enter how long the ulcer on the foot had pus in months :';
comment on column who_va_instruments."for_how_many_days_did_the_ulcer_on_the_foot_ooze_pus" is 'For how many days did the ulcer on the foot ooze pus?';
comment on column who_va_instruments."did_s_he_have_ulcers_or_sores_anywhere_else_on_the_body" is 'Did (s)he have ulcers or sores anywhere else on the body?';
comment on column who_va_instruments."did_the_ulcers_or_sores_have_pus" is 'Did the ulcers or sores have pus?';
comment on column who_va_instruments."did_s_he_have_any_skin_rash" is 'Did (s)he have any skin rash?';
comment on column who_va_instruments."for_how_many_days_did_s_he_have_the_skin_rash" is 'For how many days did (s)he have the skin rash?';
comment on column who_va_instruments."where_was_the_rash" is 'Where was the rash?';
comment on column who_va_instruments."did_s_he_have_measles_rash" is 'Did (s)he have measles rash?';
comment on column who_va_instruments."did_s_he_ever_have_shingles_or_herpes_zoster" is 'Did (s)he ever have shingles or herpes zoster?';
comment on column who_va_instruments."did_her_his_skin_flake_off_in_patches" is 'Did her/his skin flake off in patches?';
comment on column who_va_instruments."did_he_she_have_areas_of_the_skin_that_turned_black" is 'Did he/she have areas of the skin that turned black?';
comment on column who_va_instruments."did_he_she_have_areas_of_the_skin_with_redness_and_swelling" is 'Did he/she have areas of the skin with redness and swelling?';
comment on column who_va_instruments."did_s_he_bleed_from_the_nose_mouth_or_anus" is 'Did (s)he bleed from the nose, mouth or anus?';
comment on column who_va_instruments."did_s_he_have_noticeable_weight_loss" is 'Did (s)he have noticeable weight loss?';
comment on column who_va_instruments."was_s_he_severely_thin_or_wasted" is 'Was (s)he severely thin or wasted?';
comment on column who_va_instruments."did_s_he_have_a_whitish_rash_inside_the_mouth_or_on_the_tongue" is 'Did s/he have a whitish rash inside the mouth or on the tongue?';
comment on column who_va_instruments."did_s_he_have_stiffness_of_the_whole_body_or_was_unable_to_open" is 'Did (s)he have stiffness of the whole body or was unable to open the mouth?';
comment on column who_va_instruments."did_s_he_have_puffiness_of_the_face" is 'Did (s)he have puffiness of the face?';
comment on column who_va_instruments."how_long_did_s_he_have_puffiness_of_the_face" is 'How long did (s)he have puffiness of the face?';
comment on column who_va_instruments."enter_how_long_s_he_had_puffiness_of_the_face_in_days" is 'Enter how long (s)he had puffiness of the face in days :';
comment on column who_va_instruments."enter_how_long_s_he_had_puffiness_of_the_face_in_months" is 'Enter how long (s)he had puffiness of the face in months :';
comment on column who_va_instruments."for_how_many_days_did_s_he_have_puffiness_of_the_face" is 'For how many days did (s)he have puffiness of the face?';
comment on column who_va_instruments."did_s_he_have_swollen_legs_or_feet" is 'Did (s)he have swollen legs or feet?';
comment on column who_va_instruments."how_long_did_the_swelling_last" is 'How long did the swelling last?';
comment on column who_va_instruments."enter_how_long_the_swelling_lasted_in_days" is 'Enter how long the swelling lasted in days :';
comment on column who_va_instruments."enter_how_long_the_swelling_lasted_in_months" is 'Enter how long the swelling lasted in months :';
comment on column who_va_instruments."how_many_days_did_the_swelling_last" is 'How many days did the swelling last?';
comment on column who_va_instruments."did_s_he_have_both_feet_swollen" is 'Did (s)he have both feet swollen?';
comment on column who_va_instruments."did_s_he_have_general_swelling_of_the_body" is 'Did (s)he have general swelling of the body?';
comment on column who_va_instruments."did_s_he_have_any_lumps_or_sores_in_the_mouth" is 'Did (s)he have any lumps or sores in the mouth?';
comment on column who_va_instruments."did_s_he_have_lumps_anywhere_else_on_the_body" is 'Did (s)he have lumps anywhere else on the body?';
comment on column who_va_instruments."did_s_he_have_any_lumps_on_the_neck" is 'Did (s)he have any lumps on the neck?';
comment on column who_va_instruments."did_s_he_have_any_lumps_on_the_armpit" is 'Did (s)he have any lumps on the armpit?';
comment on column who_va_instruments."did_s_he_have_any_lumps_on_the_groin" is 'Did (s)he have any lumps on the groin?';
comment on column who_va_instruments."was_s_he_in_any_way_paralysed" is 'Was (s)he in any way paralysed?';
comment on column who_va_instruments."did_s_he_have_paralysis_of_only_one_side_of_the_body" is 'Did (s)he have paralysis of only one side of the body?';
comment on column who_va_instruments."did_she_have_paralysis_of_both_legs" is 'Did she have paralysis of both legs?';
comment on column who_va_instruments."was_there_difficulty_or_pain_in_swallowing" is 'Was there difficulty or pain in swallowing?';
comment on column who_va_instruments."for_how_long_did_s_he_have_difficulty_or_pain_in_swallowing" is 'For how long did (s)he have difficulty or pain in swallowing?';
comment on column who_va_instruments."enter_how_long_before_death_s_he_had_difficulty_or_pain_in_swal" is 'Enter how long before death (s)he had difficulty or pain in swallowing in days :';
comment on column who_va_instruments."enter_how_long_before_death_s_he_had_difficulty_or_pain_in_sw_2" is 'Enter how long before death (s)he had difficulty or pain in swallowing in months :';
comment on column who_va_instruments."for_how_many_days_before_death_did_s_he_have_difficulty_swallow" is 'For how many days before death did (s)he have difficulty swallowing?';
comment on column who_va_instruments."did_swallowing_become_impossible" is 'Did swallowing become impossible?';
comment on column who_va_instruments."did_s_he_have_yellow_discoloration_of_the_eyes" is 'Did (s)he have yellow discoloration of the eyes?';
comment on column who_va_instruments."for_how_long_did_s_he_have_the_yellow_discoloration" is 'For how long did (s)he have the yellow discoloration?';
comment on column who_va_instruments."enter_how_long_s_he_had_the_yellow_discoloration_in_days" is 'Enter how long (s)he had the yellow discoloration in days :';
comment on column who_va_instruments."enter_how_long_s_he_had_the_yellow_discoloration_in_months" is 'Enter how long (s)he had the yellow discoloration in months :';
comment on column who_va_instruments."for_how_many_days_did_s_he_have_the_yellow_discoloration" is 'For how many days did (s)he have the yellow discoloration?';
comment on column who_va_instruments."did_her_his_hair_change_in_color_to_a_reddish_or_yellowish_colo" is 'Did her/his hair change in color to a reddish or yellowish color?';
comment on column who_va_instruments."did_s_he_look_pale_or_have_pale_palms_eyes_or_nail_beds" is 'Did (s)he look pale or have pale palms, eyes or nail beds?';
comment on column who_va_instruments."did_s_he_have_sunken_eyes" is 'Did (s)he have sunken eyes?';
comment on column who_va_instruments."was_the_baby_able_to_suckle_or_bottle_feed_within_the_first_24" is 'Was the baby able to suckle or bottle-feed within the first 24 hours after birth?';
comment on column who_va_instruments."did_the_baby_ever_suckle_in_a_normal_way" is 'Did the baby ever suckle in a normal way?';
comment on column who_va_instruments."did_the_baby_stop_suckling" is 'Did the baby stop suckling?';
comment on column who_va_instruments."how_many_days_after_birth_did_the_baby_stop_suckling" is 'How many days after birth did the baby stop suckling?';
comment on column who_va_instruments."how_long_after_birth_did_the_baby_stop_suckling" is 'How long after birth did the baby stop suckling?';
comment on column who_va_instruments."enter_how_long_after_birth_the_baby_stopped_suckling_in_days" is 'Enter how long after birth the baby stopped suckling in days :';
comment on column who_va_instruments."enter_how_long_after_birth_the_baby_stopped_suckling_in_months" is 'Enter how long after birth the baby stopped suckling in months :';
comment on column who_va_instruments."how_many_days_after_birth_did_the_baby_stop_suckling_2" is 'How many days after birth did the baby stop suckling?';
comment on column who_va_instruments."did_the_baby_s_body_become_stiff_with_the_back_arched_backwards" is 'Did the baby''s body become stiff, with the back arched backwards?';
comment on column who_va_instruments."did_the_baby_have_a_bulging_or_raised_fontanelle" is 'Did the baby have a bulging or raised fontanelle?';
comment on column who_va_instruments."did_the_baby_have_a_sunken_fontanelle" is 'Did the baby have a sunken fontanelle?';
comment on column who_va_instruments."did_the_baby_become_unresponsive_or_unconscious" is 'Did the baby become unresponsive or unconscious?';
comment on column who_va_instruments."did_the_baby_become_unresponsive_or_unconscious_within_24_hours" is 'Did the baby become unresponsive or unconscious within 24 hours after birth?';
comment on column who_va_instruments."did_the_baby_become_unresponsive_or_unconscious_more_than_24_ho" is 'Did the baby become unresponsive or unconscious more than 24 hours after birth?';
comment on column who_va_instruments."did_the_baby_become_cold_to_touch" is 'Did the baby become cold to touch?';
comment on column who_va_instruments."did_the_baby_become_lethargic_after_a_period_of_normal_activity" is 'Did the baby become lethargic after a period of normal activity?';
comment on column who_va_instruments."did_the_baby_have_redness_or_pus_oozing_from_the_umbilical_cord" is 'Did the baby have redness or pus oozing from the umbilical cord?';
comment on column who_va_instruments."did_the_baby_have_skin_ulcer_s_or_sore_s" is 'Did the baby have skin ulcer(s) or sore(s)?';
comment on column who_va_instruments."did_the_baby_have_yellow_skin_palms_or_soles" is 'Did the baby have yellow skin, palms or soles?';
comment on column who_va_instruments."did_s_h_e_suffer_from_extreme_fatigue" is 'Did s(h)e suffer from extreme fatigue?';
comment on column who_va_instruments."did_s_he_experience_a_new_loss_change_or_decreased_sense_of_sme" is 'Did (s)he experience a new loss, change or decreased sense of smell or taste?';
comment on column who_va_instruments."did_she_have_any_lump_s_and_or_ulcer_s_in_the_breast" is 'Did she have any lump(s) and/or ulcer(s) in the breast?';
comment on column who_va_instruments."did_she_ever_have_a_period_or_menstruate" is 'Did she ever have a period or menstruate?';
comment on column who_va_instruments."did_her_menstrual_period_stop_naturally_because_of_menopause" is 'Did her menstrual period stop naturally because of menopause?';
comment on column who_va_instruments."did_she_have_vaginal_bleeding_after_cessation_of_menstruation" is 'Did she have vaginal bleeding after cessation of menstruation?';
comment on column who_va_instruments."was_there_excessive_vaginal_bleeding_in_the_week_prior_to_death" is 'Was there excessive vaginal bleeding in the week prior to death?';
comment on column who_va_instruments."at_the_time_of_death_was_her_period_overdue" is 'At the time of death was her period overdue?';
comment on column who_va_instruments."for_how_many_weeks_had_her_period_been_overdue" is 'For how many weeks had her period been overdue?';
comment on column who_va_instruments."was_she_pregnant_and_not_yet_in_labour_at_the_time_of_death" is 'Was she pregnant and not yet in labour at the time of death?';
comment on column who_va_instruments."did_she_die_during_labour_or_delivery" is 'Did she die during labour or delivery?';
comment on column who_va_instruments."did_she_die_after_delivering_a_baby" is 'Did she die after delivering a baby?';
comment on column who_va_instruments."did_she_die_within_24_hours_after_delivery" is 'Did she die within 24 hours after delivery?';
comment on column who_va_instruments."did_she_die_within_6_weeks_after_delivery" is 'Did she die within 6 weeks after delivery?';
comment on column who_va_instruments."did_she_have_a_pregnancy_that_ended_in_an_abortion_or_miscarria" is 'Did she have a pregnancy that ended in an abortion or miscarriage within 6 weeks before her death?';
comment on column who_va_instruments."did_she_attempt_to_terminate_the_pregnancy" is 'Did she attempt to terminate the pregnancy?';
comment on column who_va_instruments."did_she_die_less_than_1_year_after_delivery_abortion_or_miscarr" is 'Did she die less than 1 year after delivery, abortion or miscarriage?';
comment on column who_va_instruments."please_confirm_that_in_the_12_months_prior_to_her_death_the_wom" is 'Please confirm that in the 12 months prior to her death, the woman was not pregnant, she did not have a delivery and she also did not have an abortion or miscarriage.';
comment on column who_va_instruments."did_she_have_a_sharp_abdominal_pain_in_the_first_3_months_of_pr" is 'Did she have a sharp abdominal pain in the first 3 months of pregnancy?';
comment on column who_va_instruments."did_she_faint_when_she_had_the_sharp_abdominal_pain" is 'Did she faint when she had the sharp abdominal pain?';
comment on column who_va_instruments."for_how_many_months_was_she_pregnant" is 'For how many months was she pregnant?';
comment on column who_va_instruments."how_many_babies_was_she_pregnant_with" is 'How many babies was she pregnant with?';
comment on column who_va_instruments."during_pregnancy_did_she_suffer_from_high_blood_pressure" is 'During pregnancy, did she suffer from high blood pressure?';
comment on column who_va_instruments."did_she_have_foul_smelling_vaginal_discharge_during_pregnancy" is 'Did she have foul smelling vaginal discharge during pregnancy?';
comment on column who_va_instruments."did_bleeding_occur_while_she_was_pregnant" is 'Did bleeding occur while she was pregnant?';
comment on column who_va_instruments."was_there_vaginal_bleeding_during_the_last_3_months_of_pregnanc" is 'Was there vaginal bleeding during the last 3 months of pregnancy but before labour started?';
comment on column who_va_instruments."did_she_suffer_from_convulsions_during_the_last_3_months_of_pre" is 'Did she suffer from convulsions during the last 3 months of pregnancy and/or after delivery?';
comment on column who_va_instruments."did_she_have_blurred_vision_during_the_last_3_months_of_pregnan" is 'Did she have blurred vision during the last 3 months of pregnancy and/or after delivery?';
comment on column who_va_instruments."did_she_have_excessive_bleeding_during_labour_or_delivery" is 'Did she have excessive bleeding during labour or delivery?';
comment on column who_va_instruments."did_she_have_excessive_bleeding_after_delivery" is 'Did she have excessive bleeding after delivery?';
comment on column who_va_instruments."did_she_have_excessive_bleeding_during_or_after_abortion_or_mis" is 'Did she have excessive bleeding during or after abortion or miscarriage?';
comment on column who_va_instruments."did_she_have_foul_smelling_vaginal_discharge_after_delivery_abo" is 'Did she have foul smelling vaginal discharge after delivery/abortion?';
comment on column who_va_instruments."did_she_deliver_or_try_to_deliver_an_abnormally_positioned_baby" is 'Did she deliver or try to deliver an abnormally positioned baby?';
comment on column who_va_instruments."for_how_many_hours_was_she_in_labour" is 'For how many hours was she in labour?';
comment on column who_va_instruments."was_the_delivery_normal_vaginal_without_forceps_or_vacuum" is 'Was the delivery normal vaginal, without forceps or vacuum?';
comment on column who_va_instruments."was_the_delivery_vaginal_with_forceps_or_vacuum" is 'Was the delivery vaginal, with forceps or vacuum?';
comment on column who_va_instruments."was_the_delivery_a_caesarean_section" is 'Was the delivery a Caesarean section?';
comment on column who_va_instruments."was_the_placenta_completely_delivered" is 'Was the placenta completely delivered?';
comment on column who_va_instruments."where_did_she_give_birth" is 'Where did she give birth?';
comment on column who_va_instruments."how_many_births_including_stillbirths_did_she_the_mother_have_b" is 'How many births, including stillbirths, did she/the mother have before this pregnancy?';
comment on column who_va_instruments."had_she_had_any_previous_caesarean_section" is 'Had she had any previous Caesarean section?';
comment on column who_va_instruments."did_she_have_an_operation_to_remove_her_uterus_shortly_before_d" is 'Did she have an operation to remove her uterus shortly before death?';
comment on column who_va_instruments."was_the_child_part_of_a_multiple_birth" is 'Was the child part of a multiple birth?';
comment on column who_va_instruments."is_the_child_health_card_is_available" is 'is the child health card is available?';
comment on column who_va_instruments."enter_the_birth_weight_from_the_card_record_the_weight_in_gramm" is 'Enter the birth weight from the card. Record the weight in grammes in 4 digits. For data entry, convert to grammes as needed. 1 kilogram=1,000 grammes.';
comment on column who_va_instruments."what_was_the_weight_in_grammes_of_the_deceased_at_birth" is 'What was the weight (in grammes) of the deceased at birth?';
comment on column who_va_instruments."at_birth_was_the_baby_smaller_than_usual_weighing_under_2_5_kg" is 'At birth, was the baby smaller than usual, (weighing under 2.5 kg)?';
comment on column who_va_instruments."at_birth_was_the_baby_larger_than_usual_weighing_over_4_5_kg" is 'At birth, was the baby larger than usual, (weighing over 4.5 kg)?';
comment on column who_va_instruments."how_many_months_long_was_the_pregnancy_before_the_child_was_bor" is 'How many months long was the pregnancy before the child was born?';
comment on column who_va_instruments."were_there_any_complications_during_labour_or_delivery" is 'Were there any complications during labour or delivery?';
comment on column who_va_instruments."was_any_part_of_the_baby_physically_abnormal_at_time_of_deliver" is 'Was any part of the baby physically abnormal at time of delivery? (for example: body part too large or too small, additional growth on body)?';
comment on column who_va_instruments."did_the_baby_child_have_a_swelling_or_defect_on_the_back_at_tim" is 'Did the baby/ child have a swelling or defect on the back at time of birth?';
comment on column who_va_instruments."did_the_baby_child_have_a_very_large_head_at_time_of_birth" is 'Did the baby/ child have a very large head at time of birth?';
comment on column who_va_instruments."did_the_baby_child_have_a_very_small_head_at_time_of_birth" is 'Did the baby/ child have a very small head at time of birth?';
comment on column who_va_instruments."how_many_hours_did_labour_and_delivery_take" is 'How many hours did labour and delivery take?';
comment on column who_va_instruments."was_the_baby_born_24_hours_or_more_after_the_water_broke" is 'Was the baby born 24 hours or more after the water broke?';
comment on column who_va_instruments."was_the_liquor_foul_smelling" is 'Was the liquor foul smelling?';
comment on column who_va_instruments."what_was_the_colour_of_the_liquor_when_the_waters_broke" is 'What was the colour of the liquor when the waters broke?';
comment on column who_va_instruments."was_the_delivery_normal_vaginal_without_forceps_or_vacuum_2" is 'Was the delivery normal vaginal, without forceps or vacuum?';
comment on column who_va_instruments."was_the_delivery_vaginal_with_forceps_or_vacuum_2" is 'Was the delivery vaginal, with forceps or vacuum?';
comment on column who_va_instruments."was_the_delivery_a_caesarean_section_2" is 'Was the delivery a Caesarean section?';
comment on column who_va_instruments."did_you_the_baby_s_mother_receive_any_vaccinations_since_reachi" is 'Did you/the baby''s mother receive any vaccinations since reaching adulthood including during this pregnancy?';
comment on column who_va_instruments."did_you_the_baby_s_mother_receive_tetanus_toxoid_tt_vaccine" is 'Did you/the baby''s mother receive tetanus toxoid (TT) vaccine?';
comment on column who_va_instruments."during_labour_did_the_you_the_baby_s_mother_suffer_from_fever" is 'During labour, did the you/the baby''s mother suffer from fever?';
comment on column who_va_instruments."during_the_last_3_months_of_pregnancy_labour_or_delivery_did_yo" is 'During the last 3 months of pregnancy, labour or delivery, did you/the baby''s mother suffer from high blood pressure?';
comment on column who_va_instruments."did_you_the_baby_s_mother_have_diabetes_mellitus" is 'Did you/the baby''s mother have diabetes mellitus?';
comment on column who_va_instruments."did_you_the_baby_s_mother_have_foul_smelling_vaginal_discharge" is 'Did you/the baby''s mother have foul smelling vaginal discharge during pregnancy or after delivery?';
comment on column who_va_instruments."during_the_last_3_months_of_pregnancy_labour_or_delivery_did_2" is 'During the last 3 months of pregnancy, labour or delivery, did you/the baby''s mother suffer from convulsions?';
comment on column who_va_instruments."during_the_last_3_months_of_pregnancy_did_you_the_baby_s_mother" is 'During the last 3 months of pregnancy did you/the baby''s mother suffer from blurred vision?';
comment on column who_va_instruments."did_you_the_baby_s_mother_have_severe_anemia" is 'Did you/the baby''s mother have severe anemia?';
comment on column who_va_instruments."did_you_the_baby_s_mother_have_vaginal_bleeding_during_the_last" is 'Did you/the baby''s mother have vaginal bleeding during the last 3 months of pregnancy but before labour started?';
comment on column who_va_instruments."did_the_baby_s_bottom_feet_arm_or_hand_come_out_of_the_vagina_b" is 'Did the baby''s bottom, feet, arm or hand come out of the vagina before its head?';
comment on column who_va_instruments."was_the_umbilical_cord_wrapped_more_than_once_around_the_neck_o" is 'Was the umbilical cord wrapped more than once around the neck of the child at birth?';
comment on column who_va_instruments."was_the_umbilical_cord_delivered_first" is 'Was the umbilical cord delivered first?';
comment on column who_va_instruments."was_the_baby_blue_in_colour_at_birth" is 'Was the baby blue in colour at birth?';
comment on column who_va_instruments."did_s_he_drink_alcohol" is 'Did (s)he drink alcohol?';
comment on column who_va_instruments."did_s_he_ever_smoke_tobacco" is 'Did s/he ever smoke tobacco?';
comment on column who_va_instruments."for_how_long_did_s_he_smoke_tobacco" is 'For how long did s/he smoke tobacco?';
comment on column who_va_instruments."how_many_months_years" is 'How many (months/years)';
comment on column who_va_instruments."did_s_he_ever_smoke_daily" is 'Did s/he ever smoke daily?';
comment on column who_va_instruments."did_s_he_ever_chew_and_or_sniff_tobacco" is 'Did s/he ever chew and/or sniff tobacco?';
comment on column who_va_instruments."for_how_long_did_s_he_chew_and_or_sniff_tobacco" is 'For how long did s/he chew and/or sniff tobacco?';
comment on column who_va_instruments."how_many_months_years_2" is 'How many (months/years)';
comment on column who_va_instruments."did_s_he_ever_chew_and_or_sniff_tobacco_daily" is 'Did s/he ever chew and/or sniff tobacco daily?';
comment on column who_va_instruments."did_s_he_receive_any_treatment_for_the_illness_that_led_to_deat" is 'Did (s)he receive any treatment for the illness that led to death?';
comment on column who_va_instruments."did_s_he_receive_oral_rehydration_salts" is 'Did (s)he receive oral rehydration salts?';
comment on column who_va_instruments."did_s_he_receive_or_need_intravenous_fluids_drip_treatment" is 'Did (s)he receive (or need) intravenous fluids (drip) treatment?';
comment on column who_va_instruments."did_s_he_receive_or_need_a_blood_transfusion" is 'Did (s)he receive (or need) a blood transfusion?';
comment on column who_va_instruments."did_s_he_receive_or_need_treatment_food_through_a_tube_passed_t" is 'Did (s)he receive (or need) treatment/food through a tube passed through the nose?';
comment on column who_va_instruments."did_s_he_receive_or_need_injectable_antibiotics" is 'Did (s)he receive (or need) injectable antibiotics?';
comment on column who_va_instruments."did_s_he_receive_or_need_antiretroviral_therapy_art" is 'Did (s)he receive (or need) antiretroviral therapy (ART)?';
comment on column who_va_instruments."did_s_he_have_or_need_an_operation_for_the_illness" is 'Did (s)he have (or need) an operation for the illness?';
comment on column who_va_instruments."did_s_he_have_the_operation_within_1_month_before_death" is 'Did (s)he have the operation within 1 month before death?';
comment on column who_va_instruments."did_a_health_care_worker_tell_you_the_cause_of_death" is 'Did a health care worker tell you the cause of death?';
comment on column who_va_instruments."what_did_the_health_care_worker_say" is 'What did the health care worker say?';
comment on column who_va_instruments."has_the_deceased_s_biological_mother_ever_been_told_she_had_hiv" is 'Has the deceased’s (biological) mother ever been told she had HIV/AIDS by a health worker?';
comment on column who_va_instruments."civil_registration_this_refers_to_the_legal_death_certificate_o" is 'Civil registration: "This refers to the legal death certificate obtained from the civil registration authorities (show image of local death certificate if available)."';
comment on column who_va_instruments."do_you_have_a_death_certificate_from_the_civil_registry" is 'Do you have a Death Certificate from the Civil Registry?';
comment on column who_va_instruments."death_registration_number_certificate" is 'Death registration number/certificate';
comment on column who_va_instruments."is_the_date_of_registration_available" is 'Is the date of registration available?';
comment on column who_va_instruments."date_of_registration" is 'Date of registration';
comment on column who_va_instruments."place_of_registration" is 'Place of registration';
comment on column who_va_instruments."national_number_of_deceased" is 'National number of deceased';
comment on column who_va_instruments."death_certificate_with_cause_of_death_this_refers_to_the_medica" is 'Death certificate with cause of death: "This refers to the medical certificate of cause of death (show image of local medical certificate of cause of death if available)."';
comment on column who_va_instruments."was_a_medical_certificate_of_cause_of_death_issued" is 'Was a medical certificate of cause of death issued?';
comment on column who_va_instruments."can_i_see_the_medical_certificate_of_cause_of_death" is 'Can I see the medical certificate of cause of death?';
comment on column who_va_instruments."record_the_immediate_cause_of_death_from_the_certificate_line_1" is 'Record the immediate cause of death from the certificate (line 1a)';
comment on column who_va_instruments."duration_of_the_immediate_cause_of_death_ia" is 'Duration of the immediate cause of death (Ia):';
comment on column who_va_instruments."record_the_first_antecedent_cause_of_death_from_the_certificate" is 'Record the first antecedent cause of death from the certificate (line 1b)';
comment on column who_va_instruments."duration_of_the_first_antecedent_cause_of_death_ib" is 'Duration of the first antecedent cause of death (Ib):';
comment on column who_va_instruments."record_the_second_antecedent_cause_of_death_from_the_certificat" is 'Record the second antecedent cause of death from the certificate (line 1c)';
comment on column who_va_instruments."duration_of_second_antecedent_cause_of_death_ic" is 'Duration of second antecedent cause of death (Ic):';
comment on column who_va_instruments."record_the_third_antecedent_cause_of_death_from_the_certificate" is 'Record the third antecedent cause of death from the certificate (line 1d)';
comment on column who_va_instruments."duration_of_third_antecedent_cause_of_death" is 'Duration of third antecedent cause of death ( ):';
comment on column who_va_instruments."record_the_contributing_cause_s_of_death_from_the_certificate_p" is 'Record the contributing cause(s) of death from the certificate (part 2)';
comment on column who_va_instruments."duration_of_the_contributing_cause_s_of_death_part2" is 'Duration of the contributing cause(s) of death (part2):';
comment on column who_va_instruments."end_time_of_the_interview" is 'End time of the interview';
comment on column who_va_instruments."inform_the_respondent_that_the_va_interview_has_come_to_an_end" is 'Inform the respondent that the VA interview has come to an end. Thank the respondent for their time and answers, and ask if the respondent has any question(s) or comment(s) to make. Use this section to record any additional details you and/or the respondent have about the interview.';
comment on column who_va_instruments."comment_comment" is '(comment) Comment';

create or replace function sync_who_va_question_answer_row()
returns trigger
language plpgsql
as $$
declare
  answer_data jsonb;
begin
  answer_data := coalesce(NEW.who_va_prefill, '{}'::jsonb) || coalesce(NEW.submission, '{}'::jsonb);
  insert into who_va_instruments (
    entry_uid,
    updated_at,
    "audit",
    "name_of_va_interviewer",
    "age_of_va_interviewer",
    "sex_of_va_interviewer",
    "of_va_interviewer",
    "interview_language",
    "is_this_a_region_of_high_hiv_aids_mortality",
    "is_this_a_region_of_high_malaria_mortality",
    "during_which_season_did_s_he_die",
    "what_is_the_full_name_of_va_respondent",
    "what_is_the_sex_of_va_respondent",
    "what_is_the_age_of_va_respondent",
    "what_is_your_the_respondent_s_relationship_to_the_deceased",
    "did_you_the_respondent_live_with_the_deceased_in_the_period_lea",
    "date_of_the_interview",
    "did_the_respondent_give_consent",
    "start_time_of_the_interview",
    "what_was_the_first_or_given_name_s_of_the_deceased",
    "what_was_the_surname_s_or_family_name_s_of_the_deceased",
    "what_was_the_sex_of_the_deceased",
    "is_the_date_of_birth_known",
    "when_was_the_deceased_born",
    "is_the_date_of_death_known",
    "when_did_s_he_die",
    "when_did_s_he_die_2",
    "when_did_s_he_die_3",
    "please_indicate_the_year_of_death",
    "age_in_days",
    "age_in_days_2",
    "age_in_years",
    "ageinyearsremain",
    "age_in_months",
    "ageinmonthsremain",
    "the_deceased_person_is_a_neonate",
    "the_deceased_person_is_a_child",
    "the_deceased_person_is_an_adult",
    "neonate_was_ageindays_days_old",
    "child_was_ageinyears_years_ageinmonths_months_and_ageinmonthsre",
    "adult_was_ageinyears_years_old",
    "what_age_group_corresponds_to_the_deceased",
    "how_many_days_old_was_the_baby_enter_neonate_s_age_in_days",
    "how_many_hours_was_the_baby_alive",
    "how_old_was_the_child_enter_child_s_age_in",
    "enter_child_s_age_in_days",
    "enter_child_s_age_in_months",
    "enter_child_s_age_in_years",
    "enter_adult_s_age_in_years",
    "age_in_months_2",
    "age_in_years_2",
    "the_deceased_person_is_a_neonate_2",
    "the_deceased_person_is_a_child_2",
    "the_deceased_person_is_an_adult_2",
    "the_deceased_person_is_a_neonate_3",
    "the_deceased_person_is_a_child_3",
    "the_deceased_person_is_an_adult_3",
    "age_in_days_3",
    "it_is_not_possible_to_select_that_the_respondent_is_the_child_o",
    "where_did_the_deceased_die",
    "in_the_two_weeks_before_death_did_s_he_live_with_visit_or_care",
    "is_there_a_need_to_collect_additional_demographic_data_on_the_d",
    "what_was_her_his_citizenship_nationality",
    "what_was_her_his_ethnicity",
    "what_was_her_his_place_of_birth",
    "what_was_her_his_place_of_usual_residence_the_place_where_the_p",
    "where_did_the_death_occur_specify_country_province_district_vil",
    "what_was_her_his_marital_status",
    "what_was_her_his_highest_level_of_schooling",
    "was_s_he_able_to_read_and_or_write",
    "what_was_her_his_economic_activity_status_in_year_prior_to_deat",
    "what_was_her_his_occupation_that_is_what_kind_of_work_did_s_he",
    "what_was_the_full_name_of_the_father",
    "what_was_the_full_name_of_the_mother",
    "record_detailed_notes_of_response_or_audio_record_the_response",
    "thank_you_for_your_information_now_can_you_please_tell_me_in_yo",
    "thank_you_for_your_information_now_can_you_please_tell_me_in_2",
    "select_any_of_the_following_words_that_were_mentioned_as_presen",
    "select_any_of_the_following_words_that_were_mentioned_as_pres_2",
    "select_any_of_the_following_words_that_were_mentioned_as_pres_3",
    "some_of_the_following_questions_may_be_repetetive_or_irrelevant",
    "did_the_baby_ever_cry",
    "did_the_baby_cry_immediately_after_birth_even_if_only_a_little",
    "how_many_minutes_after_birth_did_the_baby_first_cry",
    "did_the_baby_stop_being_able_to_cry",
    "did_the_baby_stop_moving_in_the_womb",
    "did_the_baby_stop_moving_before_or_after_the_onset_of_labour",
    "did_the_baby_ever_move_after_being_delivered",
    "did_the_baby_ever_breathe",
    "did_the_baby_breathe_immediately_after_birth_even_a_little",
    "did_the_baby_have_a_breathing_problem",
    "was_the_baby_given_assistance_to_breathe_at_birth",
    "if_the_baby_didn_t_show_any_sign_of_life_was_it_born_dead",
    "were_there_any_bruises_or_signs_of_injury_on_baby_s_body_after",
    "was_the_baby_s_body_soft_discoloured_and_the_skin_peeling_away",
    "explain_to_the_respondent_that_the_following_section_contains_a",
    "was_there_any_diagnosis_by_a_health_professional_of_tuberculosi",
    "was_an_hiv_test_ever_positive",
    "was_there_any_diagnosis_by_a_health_professional_of_aids",
    "did_s_he_have_a_recent_positive_test_by_a_health_professional_f",
    "did_s_he_have_a_recent_negative_test_by_a_health_professional_f",
    "was_there_any_diagnosis_by_a_health_professional_of_covid_19",
    "did_s_h_e_have_a_recent_test_for_covid_19",
    "what_was_the_result",
    "was_there_any_diagnosis_by_a_health_professional_of_dengue_feve",
    "was_there_any_diagnosis_by_a_health_professional_of_measles",
    "was_there_any_diagnosis_by_a_health_professional_of_high_blood",
    "was_there_any_diagnosis_by_a_health_professional_of_heart_disea",
    "was_there_any_diagnosis_by_a_health_professional_of_diabetes",
    "was_there_any_diagnosis_by_a_health_professional_of_asthma",
    "was_there_any_diagnosis_by_a_health_professional_of_epilepsy",
    "was_there_any_diagnosis_by_a_health_professional_of_cancer",
    "was_there_any_diagnosis_by_a_health_professional_of_chronic_obs",
    "was_there_any_diagnosis_by_a_health_professional_of_dementia",
    "was_there_any_diagnosis_by_a_health_professional_of_depression",
    "was_there_any_diagnosis_by_a_health_professional_of_stroke",
    "was_there_any_diagnosis_by_a_health_professional_of_sickle_cell",
    "was_there_any_diagnosis_by_a_health_professional_of_kidney_dise",
    "was_there_any_diagnosis_by_a_health_professional_of_liver_disea",
    "unless_specified_the_following_questions_on_signs_symptoms_trea",
    "did_s_he_suffer_from_any_injury_or_accident_that_led_to_her_his",
    "how_long_after_the_injury_or_accident_did_s_he_die",
    "interviewer_click_ok_to_confirm_the_answer_she_died_less_than_o",
    "was_it_a_road_transport_injury",
    "was_it_a_non_road_transport_injury",
    "was_s_he_injured_in_a_fall",
    "was_there_any_poisoning",
    "did_s_he_die_of_drowning",
    "was_s_he_injured_by_a_venomous_bite_or_sting_from_an_animal_or",
    "was_s_he_injured_by_an_animal_or_insect_non_venomous",
    "what_was_the_animal_insect",
    "was_s_he_injured_by_burns_fire",
    "was_s_he_injured_by_a_firearm",
    "was_s_he_stabbed_cut_or_pierced",
    "was_s_he_strangled",
    "was_s_h_e_electrocuted",
    "was_s_he_injured_by_a_blunt_force",
    "was_s_he_injured_by_a_force_of_nature",
    "did_s_he_suffer_any_other_injury",
    "was_the_injury_accidental",
    "was_the_injury_self_inflicted",
    "was_the_injury_intentionally_inflicted_by_someone_else",
    "how_many_days_old_was_the_baby_when_the_fatal_illness_started",
    "before_the_illness_that_led_to_death_was_the_baby_the_child_gro",
    "for_how_many_days_was_s_he_ill_before_death",
    "for_how_long_was_s_he_ill_before_death",
    "months",
    "years",
    "days",
    "calculated_number_of_days_with_illness",
    "did_s_he_die_suddenly",
    "did_s_he_have_a_fever",
    "how_many_days_did_the_fever_last",
    "how_long_did_the_fever_last",
    "enter_how_long_the_fever_lasted_in_days",
    "enter_how_long_the_fever_lasted_in_months",
    "how_many_days_did_the_fever_last_2",
    "did_the_fever_continue_until_death",
    "how_severe_was_the_fever",
    "what_was_the_pattern_of_the_fever",
    "did_s_he_have_a_cough",
    "for_how_long_did_s_he_have_a_cough",
    "enter_how_long_s_he_had_a_cough_in_days",
    "enter_how_long_s_he_had_a_cough_in_months",
    "for_how_many_days_did_s_he_have_a_cough",
    "was_the_cough_productive_with_sputum",
    "was_the_cough_very_severe",
    "did_s_he_cough_up_blood",
    "did_s_he_make_a_whooping_sound_when_coughing",
    "did_s_he_have_any_difficulty_breathing_or_breathlessness",
    "for_how_many_days_did_the_difficulty_breathing_or_breathlessnes",
    "for_how_long_did_the_difficulty_breathing_or_breathlessness_las",
    "enter_how_long_the_difficult_breathing_or_breathlessness_lasted",
    "enter_how_long_the_difficult_breathing_or_breathlessness_last_2",
    "enter_how_long_the_difficult_breathing_or_breathlessness_last_3",
    "calculated_number_of_days_with_illness_2",
    "was_the_difficulty_in_breathing_continuous_or_on_and_off",
    "was_s_he_unable_to_carry_out_daily_routines_due_to_breathlessne",
    "was_s_he_breathless_while_lying_flat",
    "did_s_he_have_fast_breathing",
    "for_how_many_days_did_the_fast_breathing_last",
    "how_long_did_the_fast_breathing_last",
    "enter_how_long_the_fast_breathing_lasted_in_days",
    "enter_how_long_the_fast_breathing_lasted_in_months",
    "how_long_did_the_fast_breathing_last_2",
    "did_you_see_the_lower_chest_wall_ribs_being_pulled_in_as_the_ch",
    "did_his_her_breathing_sound_like_any_of_the_following",
    "did_s_he_have_wheezing",
    "during_the_illness_that_led_to_death_did_his_her_breathing_soun",
    "did_s_he_have_chest_pain",
    "was_the_chest_pain_severe",
    "how_many_days_before_death_did_s_he_have_chest_pain",
    "how_long_did_the_chest_pain_last",
    "enter_how_long_the_chest_pain_lasted_in_hours",
    "enter_how_long_the_chest_pain_lasted_in_days",
    "did_s_he_have_diarrhoea",
    "how_long_did_s_he_have_diarrhoea",
    "enter_how_long_s_he_have_diarrhoea_in_days",
    "enter_how_long_s_he_have_diarrhoea_in_months",
    "for_how_many_days_did_s_he_have_diarrhoea",
    "how_many_stools_did_the_baby_or_child_have_on_the_day_that_diar",
    "how_many_days_before_death_did_the_diarrhoea_start",
    "how_long_before_death_did_the_diarrhoea_start",
    "enter_how_long_before_death_the_diarrhoea_started_in_days",
    "enter_how_long_before_death_the_diarrhoea_started_in_months",
    "did_the_diarrhoea_continue_until_death",
    "at_any_time_during_the_final_illness_was_there_blood_in_the_sto",
    "did_s_he_vomit",
    "for_how_long_did_s_he_vomit",
    "enter_how_long_before_death_s_he_vomited_in_days",
    "enter_how_long_before_death_s_he_vomited_in_months",
    "did_s_he_vomit_in_the_week_preceding_the_death",
    "did_s_he_vomit_every_time_s_he_ate_and_or_drank",
    "was_there_blood_in_the_vomit",
    "was_the_vomit_black",
    "did_s_he_have_abdominal_pain",
    "was_the_abdominal_pain_severe",
    "for_how_long_did_s_he_have_abdominal_pain",
    "enter_how_long_s_he_had_abdominal_pain_in_hours",
    "enter_how_long_s_he_had_abdominal_pain_in_days",
    "enter_how_long_s_he_had_abdominal_pain_in_months",
    "calculated_number_of_days_with_abdominal_pain",
    "where_was_the_location_of_the_abdominal_pain",
    "did_s_he_have_a_more_than_usually_protruding_abdomen",
    "for_how_long_before_death_did_s_he_have_a_more_than_usually_pro",
    "enter_how_long_before_death_s_he_had_a_more_than_usually_protru",
    "enter_how_long_before_death_s_he_had_a_more_than_usually_prot_2",
    "calculated_number_of_days_with_protruding_abdomen",
    "how_rapidly_did_s_he_develop_the_protruding_abdomen",
    "did_s_he_have_any_mass_in_the_abdomen",
    "for_how_long_did_s_he_have_a_mass_in_the_abdomen",
    "enter_how_long_s_he_had_a_mass_in_the_abdomen_in_days",
    "enter_how_long_s_he_had_a_mass_in_the_abdomen_in_months",
    "calculated_number_of_days_with_a_mass_in_the_abdomen",
    "did_s_he_have_a_severe_headache",
    "did_s_he_have_a_stiff_or_painful_neck",
    "how_long_before_death_did_s_he_have_a_stiff_or_painful_neck",
    "enter_how_long_before_death_did_s_he_have_stiff_or_painful_neck",
    "enter_how_long_before_death_did_s_he_have_stiff_or_painful_ne_2",
    "for_how_many_days_before_death_did_s_he_have_stiff_or_painful_n",
    "did_s_he_have_mental_confusion",
    "how_long_did_s_he_have_mental_confusion",
    "enter_how_long_s_he_had_mental_confusion_in_days",
    "enter_how_long_s_he_had_mental_confusion_in_months",
    "for_how_many_months_did_s_he_have_mental_confusion",
    "was_s_he_unconscious",
    "how_long_before_death_did_unconsciousness_start",
    "enter_how_long_before_death_unconsciousness_started_in_hours",
    "enter_how_long_before_death_unconsciousness_started_in_days",
    "how_many_hours_before_death_did_unconsciousness_start",
    "did_the_unconsciousness_start_suddenly_quickly_at_least_within",
    "did_s_he_experience_any_generalized_convulsions",
    "did_s_he_become_unconscious_immediately_after_the_convulsion",
    "did_the_baby_have_convulsions_starting_within_the_first_24_hour",
    "did_the_baby_have_convulsions_starting_more_than_24_hours_after",
    "did_s_he_have_any_urine_problems",
    "during_the_final_illness_did_s_he_ever_pass_blood_in_the_urine",
    "did_s_he_stop_urinating",
    "did_s_he_have_an_ulcer_on_the_foot",
    "did_the_ulcer_on_the_foot_have_pus",
    "how_long_did_the_ulcer_on_the_foot_have_pus",
    "enter_how_long_the_ulcer_on_the_foot_had_pus_in_days",
    "enter_how_long_the_ulcer_on_the_foot_had_pus_in_months",
    "for_how_many_days_did_the_ulcer_on_the_foot_ooze_pus",
    "did_s_he_have_ulcers_or_sores_anywhere_else_on_the_body",
    "did_the_ulcers_or_sores_have_pus",
    "did_s_he_have_any_skin_rash",
    "for_how_many_days_did_s_he_have_the_skin_rash",
    "where_was_the_rash",
    "did_s_he_have_measles_rash",
    "did_s_he_ever_have_shingles_or_herpes_zoster",
    "did_her_his_skin_flake_off_in_patches",
    "did_he_she_have_areas_of_the_skin_that_turned_black",
    "did_he_she_have_areas_of_the_skin_with_redness_and_swelling",
    "did_s_he_bleed_from_the_nose_mouth_or_anus",
    "did_s_he_have_noticeable_weight_loss",
    "was_s_he_severely_thin_or_wasted",
    "did_s_he_have_a_whitish_rash_inside_the_mouth_or_on_the_tongue",
    "did_s_he_have_stiffness_of_the_whole_body_or_was_unable_to_open",
    "did_s_he_have_puffiness_of_the_face",
    "how_long_did_s_he_have_puffiness_of_the_face",
    "enter_how_long_s_he_had_puffiness_of_the_face_in_days",
    "enter_how_long_s_he_had_puffiness_of_the_face_in_months",
    "for_how_many_days_did_s_he_have_puffiness_of_the_face",
    "did_s_he_have_swollen_legs_or_feet",
    "how_long_did_the_swelling_last",
    "enter_how_long_the_swelling_lasted_in_days",
    "enter_how_long_the_swelling_lasted_in_months",
    "how_many_days_did_the_swelling_last",
    "did_s_he_have_both_feet_swollen",
    "did_s_he_have_general_swelling_of_the_body",
    "did_s_he_have_any_lumps_or_sores_in_the_mouth",
    "did_s_he_have_lumps_anywhere_else_on_the_body",
    "did_s_he_have_any_lumps_on_the_neck",
    "did_s_he_have_any_lumps_on_the_armpit",
    "did_s_he_have_any_lumps_on_the_groin",
    "was_s_he_in_any_way_paralysed",
    "did_s_he_have_paralysis_of_only_one_side_of_the_body",
    "did_she_have_paralysis_of_both_legs",
    "was_there_difficulty_or_pain_in_swallowing",
    "for_how_long_did_s_he_have_difficulty_or_pain_in_swallowing",
    "enter_how_long_before_death_s_he_had_difficulty_or_pain_in_swal",
    "enter_how_long_before_death_s_he_had_difficulty_or_pain_in_sw_2",
    "for_how_many_days_before_death_did_s_he_have_difficulty_swallow",
    "did_swallowing_become_impossible",
    "did_s_he_have_yellow_discoloration_of_the_eyes",
    "for_how_long_did_s_he_have_the_yellow_discoloration",
    "enter_how_long_s_he_had_the_yellow_discoloration_in_days",
    "enter_how_long_s_he_had_the_yellow_discoloration_in_months",
    "for_how_many_days_did_s_he_have_the_yellow_discoloration",
    "did_her_his_hair_change_in_color_to_a_reddish_or_yellowish_colo",
    "did_s_he_look_pale_or_have_pale_palms_eyes_or_nail_beds",
    "did_s_he_have_sunken_eyes",
    "was_the_baby_able_to_suckle_or_bottle_feed_within_the_first_24",
    "did_the_baby_ever_suckle_in_a_normal_way",
    "did_the_baby_stop_suckling",
    "how_many_days_after_birth_did_the_baby_stop_suckling",
    "how_long_after_birth_did_the_baby_stop_suckling",
    "enter_how_long_after_birth_the_baby_stopped_suckling_in_days",
    "enter_how_long_after_birth_the_baby_stopped_suckling_in_months",
    "how_many_days_after_birth_did_the_baby_stop_suckling_2",
    "did_the_baby_s_body_become_stiff_with_the_back_arched_backwards",
    "did_the_baby_have_a_bulging_or_raised_fontanelle",
    "did_the_baby_have_a_sunken_fontanelle",
    "did_the_baby_become_unresponsive_or_unconscious",
    "did_the_baby_become_unresponsive_or_unconscious_within_24_hours",
    "did_the_baby_become_unresponsive_or_unconscious_more_than_24_ho",
    "did_the_baby_become_cold_to_touch",
    "did_the_baby_become_lethargic_after_a_period_of_normal_activity",
    "did_the_baby_have_redness_or_pus_oozing_from_the_umbilical_cord",
    "did_the_baby_have_skin_ulcer_s_or_sore_s",
    "did_the_baby_have_yellow_skin_palms_or_soles",
    "did_s_h_e_suffer_from_extreme_fatigue",
    "did_s_he_experience_a_new_loss_change_or_decreased_sense_of_sme",
    "did_she_have_any_lump_s_and_or_ulcer_s_in_the_breast",
    "did_she_ever_have_a_period_or_menstruate",
    "did_her_menstrual_period_stop_naturally_because_of_menopause",
    "did_she_have_vaginal_bleeding_after_cessation_of_menstruation",
    "was_there_excessive_vaginal_bleeding_in_the_week_prior_to_death",
    "at_the_time_of_death_was_her_period_overdue",
    "for_how_many_weeks_had_her_period_been_overdue",
    "was_she_pregnant_and_not_yet_in_labour_at_the_time_of_death",
    "did_she_die_during_labour_or_delivery",
    "did_she_die_after_delivering_a_baby",
    "did_she_die_within_24_hours_after_delivery",
    "did_she_die_within_6_weeks_after_delivery",
    "did_she_have_a_pregnancy_that_ended_in_an_abortion_or_miscarria",
    "did_she_attempt_to_terminate_the_pregnancy",
    "did_she_die_less_than_1_year_after_delivery_abortion_or_miscarr",
    "please_confirm_that_in_the_12_months_prior_to_her_death_the_wom",
    "did_she_have_a_sharp_abdominal_pain_in_the_first_3_months_of_pr",
    "did_she_faint_when_she_had_the_sharp_abdominal_pain",
    "for_how_many_months_was_she_pregnant",
    "how_many_babies_was_she_pregnant_with",
    "during_pregnancy_did_she_suffer_from_high_blood_pressure",
    "did_she_have_foul_smelling_vaginal_discharge_during_pregnancy",
    "did_bleeding_occur_while_she_was_pregnant",
    "was_there_vaginal_bleeding_during_the_last_3_months_of_pregnanc",
    "did_she_suffer_from_convulsions_during_the_last_3_months_of_pre",
    "did_she_have_blurred_vision_during_the_last_3_months_of_pregnan",
    "did_she_have_excessive_bleeding_during_labour_or_delivery",
    "did_she_have_excessive_bleeding_after_delivery",
    "did_she_have_excessive_bleeding_during_or_after_abortion_or_mis",
    "did_she_have_foul_smelling_vaginal_discharge_after_delivery_abo",
    "did_she_deliver_or_try_to_deliver_an_abnormally_positioned_baby",
    "for_how_many_hours_was_she_in_labour",
    "was_the_delivery_normal_vaginal_without_forceps_or_vacuum",
    "was_the_delivery_vaginal_with_forceps_or_vacuum",
    "was_the_delivery_a_caesarean_section",
    "was_the_placenta_completely_delivered",
    "where_did_she_give_birth",
    "how_many_births_including_stillbirths_did_she_the_mother_have_b",
    "had_she_had_any_previous_caesarean_section",
    "did_she_have_an_operation_to_remove_her_uterus_shortly_before_d",
    "was_the_child_part_of_a_multiple_birth",
    "is_the_child_health_card_is_available",
    "enter_the_birth_weight_from_the_card_record_the_weight_in_gramm",
    "what_was_the_weight_in_grammes_of_the_deceased_at_birth",
    "at_birth_was_the_baby_smaller_than_usual_weighing_under_2_5_kg",
    "at_birth_was_the_baby_larger_than_usual_weighing_over_4_5_kg",
    "how_many_months_long_was_the_pregnancy_before_the_child_was_bor",
    "were_there_any_complications_during_labour_or_delivery",
    "was_any_part_of_the_baby_physically_abnormal_at_time_of_deliver",
    "did_the_baby_child_have_a_swelling_or_defect_on_the_back_at_tim",
    "did_the_baby_child_have_a_very_large_head_at_time_of_birth",
    "did_the_baby_child_have_a_very_small_head_at_time_of_birth",
    "how_many_hours_did_labour_and_delivery_take",
    "was_the_baby_born_24_hours_or_more_after_the_water_broke",
    "was_the_liquor_foul_smelling",
    "what_was_the_colour_of_the_liquor_when_the_waters_broke",
    "was_the_delivery_normal_vaginal_without_forceps_or_vacuum_2",
    "was_the_delivery_vaginal_with_forceps_or_vacuum_2",
    "was_the_delivery_a_caesarean_section_2",
    "did_you_the_baby_s_mother_receive_any_vaccinations_since_reachi",
    "did_you_the_baby_s_mother_receive_tetanus_toxoid_tt_vaccine",
    "during_labour_did_the_you_the_baby_s_mother_suffer_from_fever",
    "during_the_last_3_months_of_pregnancy_labour_or_delivery_did_yo",
    "did_you_the_baby_s_mother_have_diabetes_mellitus",
    "did_you_the_baby_s_mother_have_foul_smelling_vaginal_discharge",
    "during_the_last_3_months_of_pregnancy_labour_or_delivery_did_2",
    "during_the_last_3_months_of_pregnancy_did_you_the_baby_s_mother",
    "did_you_the_baby_s_mother_have_severe_anemia",
    "did_you_the_baby_s_mother_have_vaginal_bleeding_during_the_last",
    "did_the_baby_s_bottom_feet_arm_or_hand_come_out_of_the_vagina_b",
    "was_the_umbilical_cord_wrapped_more_than_once_around_the_neck_o",
    "was_the_umbilical_cord_delivered_first",
    "was_the_baby_blue_in_colour_at_birth",
    "did_s_he_drink_alcohol",
    "did_s_he_ever_smoke_tobacco",
    "for_how_long_did_s_he_smoke_tobacco",
    "how_many_months_years",
    "did_s_he_ever_smoke_daily",
    "did_s_he_ever_chew_and_or_sniff_tobacco",
    "for_how_long_did_s_he_chew_and_or_sniff_tobacco",
    "how_many_months_years_2",
    "did_s_he_ever_chew_and_or_sniff_tobacco_daily",
    "did_s_he_receive_any_treatment_for_the_illness_that_led_to_deat",
    "did_s_he_receive_oral_rehydration_salts",
    "did_s_he_receive_or_need_intravenous_fluids_drip_treatment",
    "did_s_he_receive_or_need_a_blood_transfusion",
    "did_s_he_receive_or_need_treatment_food_through_a_tube_passed_t",
    "did_s_he_receive_or_need_injectable_antibiotics",
    "did_s_he_receive_or_need_antiretroviral_therapy_art",
    "did_s_he_have_or_need_an_operation_for_the_illness",
    "did_s_he_have_the_operation_within_1_month_before_death",
    "did_a_health_care_worker_tell_you_the_cause_of_death",
    "what_did_the_health_care_worker_say",
    "has_the_deceased_s_biological_mother_ever_been_told_she_had_hiv",
    "civil_registration_this_refers_to_the_legal_death_certificate_o",
    "do_you_have_a_death_certificate_from_the_civil_registry",
    "death_registration_number_certificate",
    "is_the_date_of_registration_available",
    "date_of_registration",
    "place_of_registration",
    "national_number_of_deceased",
    "death_certificate_with_cause_of_death_this_refers_to_the_medica",
    "was_a_medical_certificate_of_cause_of_death_issued",
    "can_i_see_the_medical_certificate_of_cause_of_death",
    "record_the_immediate_cause_of_death_from_the_certificate_line_1",
    "duration_of_the_immediate_cause_of_death_ia",
    "record_the_first_antecedent_cause_of_death_from_the_certificate",
    "duration_of_the_first_antecedent_cause_of_death_ib",
    "record_the_second_antecedent_cause_of_death_from_the_certificat",
    "duration_of_second_antecedent_cause_of_death_ic",
    "record_the_third_antecedent_cause_of_death_from_the_certificate",
    "duration_of_third_antecedent_cause_of_death",
    "record_the_contributing_cause_s_of_death_from_the_certificate_p",
    "duration_of_the_contributing_cause_s_of_death_part2",
    "end_time_of_the_interview",
    "inform_the_respondent_that_the_va_interview_has_come_to_an_end",
    "comment_comment"
  ) values (
    NEW.uid,
    now(),
    answer_data -> 'audit',
    answer_data -> 'Id10010',
    answer_data -> 'Id10010a',
    answer_data -> 'Id10010b',
    answer_data -> 'Id10010c',
    answer_data -> 'language',
    answer_data -> 'Id10002',
    answer_data -> 'Id10003',
    answer_data -> 'Id10004',
    answer_data -> 'Id10007',
    answer_data -> 'Id10007a',
    answer_data -> 'Id10007b',
    answer_data -> 'Id10008',
    answer_data -> 'Id10009',
    answer_data -> 'Id10012',
    answer_data -> 'Id10013',
    answer_data -> 'Id10011',
    answer_data -> 'Id10017',
    answer_data -> 'Id10018',
    answer_data -> 'Id10019',
    answer_data -> 'Id10020',
    answer_data -> 'Id10021',
    answer_data -> 'Id10022',
    answer_data -> 'Id10023_a',
    answer_data -> 'Id10023_b',
    answer_data -> 'Id10023',
    answer_data -> 'Id10024',
    answer_data -> 'ageInDays',
    answer_data -> 'ageInDays2',
    answer_data -> 'ageInYears',
    answer_data -> 'ageInYearsRemain',
    answer_data -> 'ageInMonths',
    answer_data -> 'ageInMonthsRemain',
    answer_data -> 'isNeonatal1',
    answer_data -> 'isChild1',
    answer_data -> 'isAdult1',
    answer_data -> 'displayAgeNeonate',
    answer_data -> 'displayAgeChild',
    answer_data -> 'displayAgeAdult',
    answer_data -> 'age_group',
    answer_data -> 'age_neonate_days',
    answer_data -> 'age_neonate_hours',
    answer_data -> 'age_child_unit',
    answer_data -> 'age_child_days',
    answer_data -> 'age_child_months',
    answer_data -> 'age_child_years',
    answer_data -> 'age_adult',
    answer_data -> 'ageInMonthsByYear',
    answer_data -> 'ageInYears2',
    answer_data -> 'isNeonatal2',
    answer_data -> 'isChild2',
    answer_data -> 'isAdult2',
    answer_data -> 'isNeonatal',
    answer_data -> 'isChild',
    answer_data -> 'isAdult',
    answer_data -> 'ageInDaysNeonate',
    answer_data -> 'Id10008_check',
    answer_data -> 'Id10058',
    answer_data -> 'Id10487',
    answer_data -> 'Id10051',
    answer_data -> 'Id10052',
    answer_data -> 'Id10053',
    answer_data -> 'Id10054',
    answer_data -> 'Id10055',
    answer_data -> 'Id10057',
    answer_data -> 'Id10059',
    answer_data -> 'Id10063',
    answer_data -> 'Id10064',
    answer_data -> 'Id10065',
    answer_data -> 'Id10066',
    answer_data -> 'Id10061',
    answer_data -> 'Id10062',
    answer_data -> 'noteon',
    answer_data -> 'Id10476_audio',
    answer_data -> 'Id10476',
    answer_data -> 'Id10477',
    answer_data -> 'Id10478',
    answer_data -> 'Id10479',
    answer_data -> 'notenarr',
    answer_data -> 'Id10104',
    answer_data -> 'Id10105',
    answer_data -> 'Id10106',
    answer_data -> 'Id10107',
    answer_data -> 'Id10377',
    answer_data -> 'Id10376',
    answer_data -> 'Id10109',
    answer_data -> 'Id10110',
    answer_data -> 'Id10111',
    answer_data -> 'Id10112',
    answer_data -> 'Id10113',
    answer_data -> 'Id10114',
    answer_data -> 'Id10115',
    answer_data -> 'Id10116',
    answer_data -> 'note_s_s',
    answer_data -> 'Id10125',
    answer_data -> 'Id10126',
    answer_data -> 'Id10127',
    answer_data -> 'Id10128',
    answer_data -> 'Id10129',
    answer_data -> 'Id10482',
    answer_data -> 'Id10483',
    answer_data -> 'Id10484',
    answer_data -> 'Id10130',
    answer_data -> 'Id10131',
    answer_data -> 'Id10132',
    answer_data -> 'Id10133',
    answer_data -> 'Id10134',
    answer_data -> 'Id10135',
    answer_data -> 'Id10136',
    answer_data -> 'Id10137',
    answer_data -> 'Id10138',
    answer_data -> 'Id10139',
    answer_data -> 'Id10140',
    answer_data -> 'Id10141',
    answer_data -> 'Id10142',
    answer_data -> 'Id10143',
    answer_data -> 'Id10144',
    answer_data -> 'nmh',
    answer_data -> 'Id10077',
    answer_data -> 'Id10077_a',
    answer_data -> 'Id10077_b',
    answer_data -> 'Id10079',
    answer_data -> 'Id10082',
    answer_data -> 'Id10083',
    answer_data -> 'Id10084',
    answer_data -> 'Id10085',
    answer_data -> 'Id10086',
    answer_data -> 'Id10087',
    answer_data -> 'Id10088',
    answer_data -> 'Id10089',
    answer_data -> 'Id10091',
    answer_data -> 'Id10092',
    answer_data -> 'Id10093',
    answer_data -> 'Id10096',
    answer_data -> 'Id10094',
    answer_data -> 'Id10095',
    answer_data -> 'Id10097',
    answer_data -> 'Id10098',
    answer_data -> 'Id10099',
    answer_data -> 'Id10100',
    answer_data -> 'Id10351',
    answer_data -> 'Id10408',
    answer_data -> 'Id10120_0',
    answer_data -> 'id10120_unit',
    answer_data -> 'Id10121',
    answer_data -> 'Id10122',
    answer_data -> 'Id10120_1',
    answer_data -> 'Id10120',
    answer_data -> 'Id10123',
    answer_data -> 'Id10147',
    answer_data -> 'Id10148_a',
    answer_data -> 'Id10148_units',
    answer_data -> 'Id10148_b',
    answer_data -> 'Id10148_c',
    answer_data -> 'Id10148',
    answer_data -> 'Id10149',
    answer_data -> 'Id10150',
    answer_data -> 'Id10151',
    answer_data -> 'Id10153',
    answer_data -> 'Id10154_units',
    answer_data -> 'Id10154_a',
    answer_data -> 'Id10154_b',
    answer_data -> 'Id10154',
    answer_data -> 'Id10155',
    answer_data -> 'Id10156',
    answer_data -> 'Id10157',
    answer_data -> 'Id10158',
    answer_data -> 'Id10159',
    answer_data -> 'Id10161_0',
    answer_data -> 'id10161_unit',
    answer_data -> 'Id10161_1',
    answer_data -> 'Id10162',
    answer_data -> 'Id10163',
    answer_data -> 'Id10161',
    answer_data -> 'Id10165',
    answer_data -> 'Id10170',
    answer_data -> 'Id10171',
    answer_data -> 'Id10166',
    answer_data -> 'Id10167_a',
    answer_data -> 'Id10167_units',
    answer_data -> 'Id10167_b',
    answer_data -> 'Id10167_c',
    answer_data -> 'Id10167',
    answer_data -> 'Id10172',
    answer_data -> 'Id10173_nc',
    answer_data -> 'Id10173_a',
    answer_data -> 'Id10173',
    answer_data -> 'Id10174',
    answer_data -> 'Id10175',
    answer_data -> 'Id10176',
    answer_data -> 'Id10178_unit',
    answer_data -> 'Id10179',
    answer_data -> 'Id10179_1',
    answer_data -> 'Id10181',
    answer_data -> 'Id10182_units',
    answer_data -> 'Id10182_a',
    answer_data -> 'Id10182_b',
    answer_data -> 'Id10182',
    answer_data -> 'Id10183',
    answer_data -> 'Id10184_a',
    answer_data -> 'Id10184_units',
    answer_data -> 'Id10184_b',
    answer_data -> 'Id10184_c',
    answer_data -> 'Id10185',
    answer_data -> 'Id10186',
    answer_data -> 'Id10188',
    answer_data -> 'Id10190_units',
    answer_data -> 'Id10190_a',
    answer_data -> 'Id10190_b',
    answer_data -> 'Id10189',
    answer_data -> 'Id10189_1',
    answer_data -> 'Id10191',
    answer_data -> 'Id10192',
    answer_data -> 'Id10194',
    answer_data -> 'Id10195',
    answer_data -> 'id10196_unit',
    answer_data -> 'Id10196',
    answer_data -> 'Id10197_a',
    answer_data -> 'Id10198',
    answer_data -> 'Id10197',
    answer_data -> 'Id10199',
    answer_data -> 'Id10200',
    answer_data -> 'Id10201_unit',
    answer_data -> 'Id10201_a',
    answer_data -> 'Id10202',
    answer_data -> 'Id10201',
    answer_data -> 'Id10203',
    answer_data -> 'Id10204',
    answer_data -> 'Id10205_unit',
    answer_data -> 'Id10205_a',
    answer_data -> 'Id10206',
    answer_data -> 'Id10205',
    answer_data -> 'Id10207',
    answer_data -> 'Id10208',
    answer_data -> 'Id10209_units',
    answer_data -> 'Id10209_a',
    answer_data -> 'Id10209_b',
    answer_data -> 'Id10209',
    answer_data -> 'Id10212',
    answer_data -> 'Id10213_units',
    answer_data -> 'Id10213_a',
    answer_data -> 'Id10213_b',
    answer_data -> 'Id10213',
    answer_data -> 'Id10214',
    answer_data -> 'Id10216_units',
    answer_data -> 'Id10216_a',
    answer_data -> 'Id10216_b',
    answer_data -> 'Id10216',
    answer_data -> 'Id10217',
    answer_data -> 'Id10220',
    answer_data -> 'Id10222',
    answer_data -> 'Id10275',
    answer_data -> 'Id10276',
    answer_data -> 'Id10223',
    answer_data -> 'Id10226',
    answer_data -> 'Id10224',
    answer_data -> 'Id10230',
    answer_data -> 'Id10231',
    answer_data -> 'Id10232_units',
    answer_data -> 'Id10232_a',
    answer_data -> 'Id10232_b',
    answer_data -> 'Id10232',
    answer_data -> 'Id10227',
    answer_data -> 'Id10229',
    answer_data -> 'Id10233',
    answer_data -> 'Id10234',
    answer_data -> 'Id10235',
    answer_data -> 'Id10236',
    answer_data -> 'Id10237',
    answer_data -> 'Id10238',
    answer_data -> 'Id10239',
    answer_data -> 'Id10240',
    answer_data -> 'Id10242',
    answer_data -> 'Id10243',
    answer_data -> 'Id10244',
    answer_data -> 'Id10245',
    answer_data -> 'Id10246',
    answer_data -> 'Id10247',
    answer_data -> 'Id10248_units',
    answer_data -> 'Id10248_a',
    answer_data -> 'Id10248_b',
    answer_data -> 'Id10248',
    answer_data -> 'Id10249',
    answer_data -> 'Id10250_units',
    answer_data -> 'Id10250_a',
    answer_data -> 'Id10250_b',
    answer_data -> 'Id10250',
    answer_data -> 'Id10251',
    answer_data -> 'Id10252',
    answer_data -> 'Id10254',
    answer_data -> 'Id10253',
    answer_data -> 'Id10255',
    answer_data -> 'Id10256',
    answer_data -> 'Id10257',
    answer_data -> 'Id10258',
    answer_data -> 'Id10259',
    answer_data -> 'Id10260',
    answer_data -> 'Id10261',
    answer_data -> 'Id10262_units',
    answer_data -> 'Id10262_a',
    answer_data -> 'Id10262_b',
    answer_data -> 'Id10262',
    answer_data -> 'Id10262_c',
    answer_data -> 'Id10265',
    answer_data -> 'Id10266_units',
    answer_data -> 'Id10266_a',
    answer_data -> 'Id10266_b',
    answer_data -> 'Id10266',
    answer_data -> 'Id10267',
    answer_data -> 'Id10268',
    answer_data -> 'Id10269',
    answer_data -> 'Id10271',
    answer_data -> 'Id10272',
    answer_data -> 'Id10273',
    answer_data -> 'Id10274_a',
    answer_data -> 'Id10274_units',
    answer_data -> 'Id10274_b',
    answer_data -> 'Id10274_c',
    answer_data -> 'Id10274',
    answer_data -> 'Id10277',
    answer_data -> 'Id10278',
    answer_data -> 'Id10279',
    answer_data -> 'Id10281',
    answer_data -> 'Id10282',
    answer_data -> 'Id10283',
    answer_data -> 'Id10284',
    answer_data -> 'Id10286',
    answer_data -> 'Id10287',
    answer_data -> 'Id10288',
    answer_data -> 'Id10289',
    answer_data -> 'Id10485',
    answer_data -> 'Id10486',
    answer_data -> 'Id10294',
    answer_data -> 'Id10296',
    answer_data -> 'Id10299',
    answer_data -> 'Id10300',
    answer_data -> 'Id10301',
    answer_data -> 'Id10302',
    answer_data -> 'Id10303',
    answer_data -> 'Id10305',
    answer_data -> 'Id10312',
    answer_data -> 'Id10313',
    answer_data -> 'Id10314',
    answer_data -> 'Id10306',
    answer_data -> 'Id10334',
    answer_data -> 'Id10333',
    answer_data -> 'Id10308',
    answer_data -> 'Id10310',
    answer_data -> 'Id10304',
    answer_data -> 'Id10304_a',
    answer_data -> 'Id10309',
    answer_data -> 'Id10317',
    answer_data -> 'Id10321',
    answer_data -> 'Id10322_a',
    answer_data -> 'Id10325',
    answer_data -> 'Id10327',
    answer_data -> 'Id10323',
    answer_data -> 'Id10324',
    answer_data -> 'Id10328',
    answer_data -> 'Id10329_a',
    answer_data -> 'Id10329_b',
    answer_data -> 'Id10322_b',
    answer_data -> 'Id10331',
    answer_data -> 'Id10332',
    answer_data -> 'Id10342',
    answer_data -> 'Id10343',
    answer_data -> 'Id10344',
    answer_data -> 'Id10330',
    answer_data -> 'Id10337',
    answer_data -> 'Id10319',
    answer_data -> 'Id10320',
    answer_data -> 'Id10340',
    answer_data -> 'Id10354',
    answer_data -> 'Id10366_check',
    answer_data -> 'n10366',
    answer_data -> 'Id10366',
    answer_data -> 'Id10363',
    answer_data -> 'Id10365',
    answer_data -> 'Id10367',
    answer_data -> 'Id10369',
    answer_data -> 'Id10370',
    answer_data -> 'Id10371',
    answer_data -> 'Id10372',
    answer_data -> 'Id10373',
    answer_data -> 'Id10382',
    answer_data -> 'Id10383',
    answer_data -> 'Id10384',
    answer_data -> 'Id10385',
    answer_data -> 'Id10387',
    answer_data -> 'Id10388',
    answer_data -> 'Id10389',
    answer_data -> 'Id10391',
    answer_data -> 'Id10393',
    answer_data -> 'Id10395',
    answer_data -> 'Id10396',
    answer_data -> 'Id10397',
    answer_data -> 'Id10398',
    answer_data -> 'Id10399',
    answer_data -> 'Id10400',
    answer_data -> 'Id10401',
    answer_data -> 'Id10402',
    answer_data -> 'Id10403',
    answer_data -> 'Id10404',
    answer_data -> 'Id10405',
    answer_data -> 'Id10406',
    answer_data -> 'Id10411',
    answer_data -> 'Id10413',
    answer_data -> 'Id10413_a',
    answer_data -> 'Id10413_d',
    answer_data -> 'Id10413_b',
    answer_data -> 'Id10414',
    answer_data -> 'Id10414_a',
    answer_data -> 'Id10414_d',
    answer_data -> 'Id10414_b',
    answer_data -> 'Id10418',
    answer_data -> 'Id10419',
    answer_data -> 'Id10420',
    answer_data -> 'Id10421',
    answer_data -> 'Id10422',
    answer_data -> 'Id10423',
    answer_data -> 'Id10424',
    answer_data -> 'Id10425',
    answer_data -> 'Id10426',
    answer_data -> 'Id10435',
    answer_data -> 'Id10436',
    answer_data -> 'Id10446',
    answer_data -> 'botecrn',
    answer_data -> 'Id10069_a',
    answer_data -> 'Id10070',
    answer_data -> 'Id10071_check',
    answer_data -> 'Id10071',
    answer_data -> 'Id10072',
    answer_data -> 'Id10073',
    answer_data -> 'noteccd',
    answer_data -> 'Id10462',
    answer_data -> 'Id10463',
    answer_data -> 'Id10464',
    answer_data -> 'Id10465',
    answer_data -> 'Id10466',
    answer_data -> 'Id10467',
    answer_data -> 'Id10468',
    answer_data -> 'Id10469',
    answer_data -> 'Id10470',
    answer_data -> 'Id10471',
    answer_data -> 'Id10472',
    answer_data -> 'Id10473',
    answer_data -> 'Id10481',
    answer_data -> 'noteend',
    answer_data -> 'comment'
  )
  on conflict (entry_uid) do update set
    updated_at = now(),
    "audit" = excluded."audit",
    "name_of_va_interviewer" = excluded."name_of_va_interviewer",
    "age_of_va_interviewer" = excluded."age_of_va_interviewer",
    "sex_of_va_interviewer" = excluded."sex_of_va_interviewer",
    "of_va_interviewer" = excluded."of_va_interviewer",
    "interview_language" = excluded."interview_language",
    "is_this_a_region_of_high_hiv_aids_mortality" = excluded."is_this_a_region_of_high_hiv_aids_mortality",
    "is_this_a_region_of_high_malaria_mortality" = excluded."is_this_a_region_of_high_malaria_mortality",
    "during_which_season_did_s_he_die" = excluded."during_which_season_did_s_he_die",
    "what_is_the_full_name_of_va_respondent" = excluded."what_is_the_full_name_of_va_respondent",
    "what_is_the_sex_of_va_respondent" = excluded."what_is_the_sex_of_va_respondent",
    "what_is_the_age_of_va_respondent" = excluded."what_is_the_age_of_va_respondent",
    "what_is_your_the_respondent_s_relationship_to_the_deceased" = excluded."what_is_your_the_respondent_s_relationship_to_the_deceased",
    "did_you_the_respondent_live_with_the_deceased_in_the_period_lea" = excluded."did_you_the_respondent_live_with_the_deceased_in_the_period_lea",
    "date_of_the_interview" = excluded."date_of_the_interview",
    "did_the_respondent_give_consent" = excluded."did_the_respondent_give_consent",
    "start_time_of_the_interview" = excluded."start_time_of_the_interview",
    "what_was_the_first_or_given_name_s_of_the_deceased" = excluded."what_was_the_first_or_given_name_s_of_the_deceased",
    "what_was_the_surname_s_or_family_name_s_of_the_deceased" = excluded."what_was_the_surname_s_or_family_name_s_of_the_deceased",
    "what_was_the_sex_of_the_deceased" = excluded."what_was_the_sex_of_the_deceased",
    "is_the_date_of_birth_known" = excluded."is_the_date_of_birth_known",
    "when_was_the_deceased_born" = excluded."when_was_the_deceased_born",
    "is_the_date_of_death_known" = excluded."is_the_date_of_death_known",
    "when_did_s_he_die" = excluded."when_did_s_he_die",
    "when_did_s_he_die_2" = excluded."when_did_s_he_die_2",
    "when_did_s_he_die_3" = excluded."when_did_s_he_die_3",
    "please_indicate_the_year_of_death" = excluded."please_indicate_the_year_of_death",
    "age_in_days" = excluded."age_in_days",
    "age_in_days_2" = excluded."age_in_days_2",
    "age_in_years" = excluded."age_in_years",
    "ageinyearsremain" = excluded."ageinyearsremain",
    "age_in_months" = excluded."age_in_months",
    "ageinmonthsremain" = excluded."ageinmonthsremain",
    "the_deceased_person_is_a_neonate" = excluded."the_deceased_person_is_a_neonate",
    "the_deceased_person_is_a_child" = excluded."the_deceased_person_is_a_child",
    "the_deceased_person_is_an_adult" = excluded."the_deceased_person_is_an_adult",
    "neonate_was_ageindays_days_old" = excluded."neonate_was_ageindays_days_old",
    "child_was_ageinyears_years_ageinmonths_months_and_ageinmonthsre" = excluded."child_was_ageinyears_years_ageinmonths_months_and_ageinmonthsre",
    "adult_was_ageinyears_years_old" = excluded."adult_was_ageinyears_years_old",
    "what_age_group_corresponds_to_the_deceased" = excluded."what_age_group_corresponds_to_the_deceased",
    "how_many_days_old_was_the_baby_enter_neonate_s_age_in_days" = excluded."how_many_days_old_was_the_baby_enter_neonate_s_age_in_days",
    "how_many_hours_was_the_baby_alive" = excluded."how_many_hours_was_the_baby_alive",
    "how_old_was_the_child_enter_child_s_age_in" = excluded."how_old_was_the_child_enter_child_s_age_in",
    "enter_child_s_age_in_days" = excluded."enter_child_s_age_in_days",
    "enter_child_s_age_in_months" = excluded."enter_child_s_age_in_months",
    "enter_child_s_age_in_years" = excluded."enter_child_s_age_in_years",
    "enter_adult_s_age_in_years" = excluded."enter_adult_s_age_in_years",
    "age_in_months_2" = excluded."age_in_months_2",
    "age_in_years_2" = excluded."age_in_years_2",
    "the_deceased_person_is_a_neonate_2" = excluded."the_deceased_person_is_a_neonate_2",
    "the_deceased_person_is_a_child_2" = excluded."the_deceased_person_is_a_child_2",
    "the_deceased_person_is_an_adult_2" = excluded."the_deceased_person_is_an_adult_2",
    "the_deceased_person_is_a_neonate_3" = excluded."the_deceased_person_is_a_neonate_3",
    "the_deceased_person_is_a_child_3" = excluded."the_deceased_person_is_a_child_3",
    "the_deceased_person_is_an_adult_3" = excluded."the_deceased_person_is_an_adult_3",
    "age_in_days_3" = excluded."age_in_days_3",
    "it_is_not_possible_to_select_that_the_respondent_is_the_child_o" = excluded."it_is_not_possible_to_select_that_the_respondent_is_the_child_o",
    "where_did_the_deceased_die" = excluded."where_did_the_deceased_die",
    "in_the_two_weeks_before_death_did_s_he_live_with_visit_or_care" = excluded."in_the_two_weeks_before_death_did_s_he_live_with_visit_or_care",
    "is_there_a_need_to_collect_additional_demographic_data_on_the_d" = excluded."is_there_a_need_to_collect_additional_demographic_data_on_the_d",
    "what_was_her_his_citizenship_nationality" = excluded."what_was_her_his_citizenship_nationality",
    "what_was_her_his_ethnicity" = excluded."what_was_her_his_ethnicity",
    "what_was_her_his_place_of_birth" = excluded."what_was_her_his_place_of_birth",
    "what_was_her_his_place_of_usual_residence_the_place_where_the_p" = excluded."what_was_her_his_place_of_usual_residence_the_place_where_the_p",
    "where_did_the_death_occur_specify_country_province_district_vil" = excluded."where_did_the_death_occur_specify_country_province_district_vil",
    "what_was_her_his_marital_status" = excluded."what_was_her_his_marital_status",
    "what_was_her_his_highest_level_of_schooling" = excluded."what_was_her_his_highest_level_of_schooling",
    "was_s_he_able_to_read_and_or_write" = excluded."was_s_he_able_to_read_and_or_write",
    "what_was_her_his_economic_activity_status_in_year_prior_to_deat" = excluded."what_was_her_his_economic_activity_status_in_year_prior_to_deat",
    "what_was_her_his_occupation_that_is_what_kind_of_work_did_s_he" = excluded."what_was_her_his_occupation_that_is_what_kind_of_work_did_s_he",
    "what_was_the_full_name_of_the_father" = excluded."what_was_the_full_name_of_the_father",
    "what_was_the_full_name_of_the_mother" = excluded."what_was_the_full_name_of_the_mother",
    "record_detailed_notes_of_response_or_audio_record_the_response" = excluded."record_detailed_notes_of_response_or_audio_record_the_response",
    "thank_you_for_your_information_now_can_you_please_tell_me_in_yo" = excluded."thank_you_for_your_information_now_can_you_please_tell_me_in_yo",
    "thank_you_for_your_information_now_can_you_please_tell_me_in_2" = excluded."thank_you_for_your_information_now_can_you_please_tell_me_in_2",
    "select_any_of_the_following_words_that_were_mentioned_as_presen" = excluded."select_any_of_the_following_words_that_were_mentioned_as_presen",
    "select_any_of_the_following_words_that_were_mentioned_as_pres_2" = excluded."select_any_of_the_following_words_that_were_mentioned_as_pres_2",
    "select_any_of_the_following_words_that_were_mentioned_as_pres_3" = excluded."select_any_of_the_following_words_that_were_mentioned_as_pres_3",
    "some_of_the_following_questions_may_be_repetetive_or_irrelevant" = excluded."some_of_the_following_questions_may_be_repetetive_or_irrelevant",
    "did_the_baby_ever_cry" = excluded."did_the_baby_ever_cry",
    "did_the_baby_cry_immediately_after_birth_even_if_only_a_little" = excluded."did_the_baby_cry_immediately_after_birth_even_if_only_a_little",
    "how_many_minutes_after_birth_did_the_baby_first_cry" = excluded."how_many_minutes_after_birth_did_the_baby_first_cry",
    "did_the_baby_stop_being_able_to_cry" = excluded."did_the_baby_stop_being_able_to_cry",
    "did_the_baby_stop_moving_in_the_womb" = excluded."did_the_baby_stop_moving_in_the_womb",
    "did_the_baby_stop_moving_before_or_after_the_onset_of_labour" = excluded."did_the_baby_stop_moving_before_or_after_the_onset_of_labour",
    "did_the_baby_ever_move_after_being_delivered" = excluded."did_the_baby_ever_move_after_being_delivered",
    "did_the_baby_ever_breathe" = excluded."did_the_baby_ever_breathe",
    "did_the_baby_breathe_immediately_after_birth_even_a_little" = excluded."did_the_baby_breathe_immediately_after_birth_even_a_little",
    "did_the_baby_have_a_breathing_problem" = excluded."did_the_baby_have_a_breathing_problem",
    "was_the_baby_given_assistance_to_breathe_at_birth" = excluded."was_the_baby_given_assistance_to_breathe_at_birth",
    "if_the_baby_didn_t_show_any_sign_of_life_was_it_born_dead" = excluded."if_the_baby_didn_t_show_any_sign_of_life_was_it_born_dead",
    "were_there_any_bruises_or_signs_of_injury_on_baby_s_body_after" = excluded."were_there_any_bruises_or_signs_of_injury_on_baby_s_body_after",
    "was_the_baby_s_body_soft_discoloured_and_the_skin_peeling_away" = excluded."was_the_baby_s_body_soft_discoloured_and_the_skin_peeling_away",
    "explain_to_the_respondent_that_the_following_section_contains_a" = excluded."explain_to_the_respondent_that_the_following_section_contains_a",
    "was_there_any_diagnosis_by_a_health_professional_of_tuberculosi" = excluded."was_there_any_diagnosis_by_a_health_professional_of_tuberculosi",
    "was_an_hiv_test_ever_positive" = excluded."was_an_hiv_test_ever_positive",
    "was_there_any_diagnosis_by_a_health_professional_of_aids" = excluded."was_there_any_diagnosis_by_a_health_professional_of_aids",
    "did_s_he_have_a_recent_positive_test_by_a_health_professional_f" = excluded."did_s_he_have_a_recent_positive_test_by_a_health_professional_f",
    "did_s_he_have_a_recent_negative_test_by_a_health_professional_f" = excluded."did_s_he_have_a_recent_negative_test_by_a_health_professional_f",
    "was_there_any_diagnosis_by_a_health_professional_of_covid_19" = excluded."was_there_any_diagnosis_by_a_health_professional_of_covid_19",
    "did_s_h_e_have_a_recent_test_for_covid_19" = excluded."did_s_h_e_have_a_recent_test_for_covid_19",
    "what_was_the_result" = excluded."what_was_the_result",
    "was_there_any_diagnosis_by_a_health_professional_of_dengue_feve" = excluded."was_there_any_diagnosis_by_a_health_professional_of_dengue_feve",
    "was_there_any_diagnosis_by_a_health_professional_of_measles" = excluded."was_there_any_diagnosis_by_a_health_professional_of_measles",
    "was_there_any_diagnosis_by_a_health_professional_of_high_blood" = excluded."was_there_any_diagnosis_by_a_health_professional_of_high_blood",
    "was_there_any_diagnosis_by_a_health_professional_of_heart_disea" = excluded."was_there_any_diagnosis_by_a_health_professional_of_heart_disea",
    "was_there_any_diagnosis_by_a_health_professional_of_diabetes" = excluded."was_there_any_diagnosis_by_a_health_professional_of_diabetes",
    "was_there_any_diagnosis_by_a_health_professional_of_asthma" = excluded."was_there_any_diagnosis_by_a_health_professional_of_asthma",
    "was_there_any_diagnosis_by_a_health_professional_of_epilepsy" = excluded."was_there_any_diagnosis_by_a_health_professional_of_epilepsy",
    "was_there_any_diagnosis_by_a_health_professional_of_cancer" = excluded."was_there_any_diagnosis_by_a_health_professional_of_cancer",
    "was_there_any_diagnosis_by_a_health_professional_of_chronic_obs" = excluded."was_there_any_diagnosis_by_a_health_professional_of_chronic_obs",
    "was_there_any_diagnosis_by_a_health_professional_of_dementia" = excluded."was_there_any_diagnosis_by_a_health_professional_of_dementia",
    "was_there_any_diagnosis_by_a_health_professional_of_depression" = excluded."was_there_any_diagnosis_by_a_health_professional_of_depression",
    "was_there_any_diagnosis_by_a_health_professional_of_stroke" = excluded."was_there_any_diagnosis_by_a_health_professional_of_stroke",
    "was_there_any_diagnosis_by_a_health_professional_of_sickle_cell" = excluded."was_there_any_diagnosis_by_a_health_professional_of_sickle_cell",
    "was_there_any_diagnosis_by_a_health_professional_of_kidney_dise" = excluded."was_there_any_diagnosis_by_a_health_professional_of_kidney_dise",
    "was_there_any_diagnosis_by_a_health_professional_of_liver_disea" = excluded."was_there_any_diagnosis_by_a_health_professional_of_liver_disea",
    "unless_specified_the_following_questions_on_signs_symptoms_trea" = excluded."unless_specified_the_following_questions_on_signs_symptoms_trea",
    "did_s_he_suffer_from_any_injury_or_accident_that_led_to_her_his" = excluded."did_s_he_suffer_from_any_injury_or_accident_that_led_to_her_his",
    "how_long_after_the_injury_or_accident_did_s_he_die" = excluded."how_long_after_the_injury_or_accident_did_s_he_die",
    "interviewer_click_ok_to_confirm_the_answer_she_died_less_than_o" = excluded."interviewer_click_ok_to_confirm_the_answer_she_died_less_than_o",
    "was_it_a_road_transport_injury" = excluded."was_it_a_road_transport_injury",
    "was_it_a_non_road_transport_injury" = excluded."was_it_a_non_road_transport_injury",
    "was_s_he_injured_in_a_fall" = excluded."was_s_he_injured_in_a_fall",
    "was_there_any_poisoning" = excluded."was_there_any_poisoning",
    "did_s_he_die_of_drowning" = excluded."did_s_he_die_of_drowning",
    "was_s_he_injured_by_a_venomous_bite_or_sting_from_an_animal_or" = excluded."was_s_he_injured_by_a_venomous_bite_or_sting_from_an_animal_or",
    "was_s_he_injured_by_an_animal_or_insect_non_venomous" = excluded."was_s_he_injured_by_an_animal_or_insect_non_venomous",
    "what_was_the_animal_insect" = excluded."what_was_the_animal_insect",
    "was_s_he_injured_by_burns_fire" = excluded."was_s_he_injured_by_burns_fire",
    "was_s_he_injured_by_a_firearm" = excluded."was_s_he_injured_by_a_firearm",
    "was_s_he_stabbed_cut_or_pierced" = excluded."was_s_he_stabbed_cut_or_pierced",
    "was_s_he_strangled" = excluded."was_s_he_strangled",
    "was_s_h_e_electrocuted" = excluded."was_s_h_e_electrocuted",
    "was_s_he_injured_by_a_blunt_force" = excluded."was_s_he_injured_by_a_blunt_force",
    "was_s_he_injured_by_a_force_of_nature" = excluded."was_s_he_injured_by_a_force_of_nature",
    "did_s_he_suffer_any_other_injury" = excluded."did_s_he_suffer_any_other_injury",
    "was_the_injury_accidental" = excluded."was_the_injury_accidental",
    "was_the_injury_self_inflicted" = excluded."was_the_injury_self_inflicted",
    "was_the_injury_intentionally_inflicted_by_someone_else" = excluded."was_the_injury_intentionally_inflicted_by_someone_else",
    "how_many_days_old_was_the_baby_when_the_fatal_illness_started" = excluded."how_many_days_old_was_the_baby_when_the_fatal_illness_started",
    "before_the_illness_that_led_to_death_was_the_baby_the_child_gro" = excluded."before_the_illness_that_led_to_death_was_the_baby_the_child_gro",
    "for_how_many_days_was_s_he_ill_before_death" = excluded."for_how_many_days_was_s_he_ill_before_death",
    "for_how_long_was_s_he_ill_before_death" = excluded."for_how_long_was_s_he_ill_before_death",
    "months" = excluded."months",
    "years" = excluded."years",
    "days" = excluded."days",
    "calculated_number_of_days_with_illness" = excluded."calculated_number_of_days_with_illness",
    "did_s_he_die_suddenly" = excluded."did_s_he_die_suddenly",
    "did_s_he_have_a_fever" = excluded."did_s_he_have_a_fever",
    "how_many_days_did_the_fever_last" = excluded."how_many_days_did_the_fever_last",
    "how_long_did_the_fever_last" = excluded."how_long_did_the_fever_last",
    "enter_how_long_the_fever_lasted_in_days" = excluded."enter_how_long_the_fever_lasted_in_days",
    "enter_how_long_the_fever_lasted_in_months" = excluded."enter_how_long_the_fever_lasted_in_months",
    "how_many_days_did_the_fever_last_2" = excluded."how_many_days_did_the_fever_last_2",
    "did_the_fever_continue_until_death" = excluded."did_the_fever_continue_until_death",
    "how_severe_was_the_fever" = excluded."how_severe_was_the_fever",
    "what_was_the_pattern_of_the_fever" = excluded."what_was_the_pattern_of_the_fever",
    "did_s_he_have_a_cough" = excluded."did_s_he_have_a_cough",
    "for_how_long_did_s_he_have_a_cough" = excluded."for_how_long_did_s_he_have_a_cough",
    "enter_how_long_s_he_had_a_cough_in_days" = excluded."enter_how_long_s_he_had_a_cough_in_days",
    "enter_how_long_s_he_had_a_cough_in_months" = excluded."enter_how_long_s_he_had_a_cough_in_months",
    "for_how_many_days_did_s_he_have_a_cough" = excluded."for_how_many_days_did_s_he_have_a_cough",
    "was_the_cough_productive_with_sputum" = excluded."was_the_cough_productive_with_sputum",
    "was_the_cough_very_severe" = excluded."was_the_cough_very_severe",
    "did_s_he_cough_up_blood" = excluded."did_s_he_cough_up_blood",
    "did_s_he_make_a_whooping_sound_when_coughing" = excluded."did_s_he_make_a_whooping_sound_when_coughing",
    "did_s_he_have_any_difficulty_breathing_or_breathlessness" = excluded."did_s_he_have_any_difficulty_breathing_or_breathlessness",
    "for_how_many_days_did_the_difficulty_breathing_or_breathlessnes" = excluded."for_how_many_days_did_the_difficulty_breathing_or_breathlessnes",
    "for_how_long_did_the_difficulty_breathing_or_breathlessness_las" = excluded."for_how_long_did_the_difficulty_breathing_or_breathlessness_las",
    "enter_how_long_the_difficult_breathing_or_breathlessness_lasted" = excluded."enter_how_long_the_difficult_breathing_or_breathlessness_lasted",
    "enter_how_long_the_difficult_breathing_or_breathlessness_last_2" = excluded."enter_how_long_the_difficult_breathing_or_breathlessness_last_2",
    "enter_how_long_the_difficult_breathing_or_breathlessness_last_3" = excluded."enter_how_long_the_difficult_breathing_or_breathlessness_last_3",
    "calculated_number_of_days_with_illness_2" = excluded."calculated_number_of_days_with_illness_2",
    "was_the_difficulty_in_breathing_continuous_or_on_and_off" = excluded."was_the_difficulty_in_breathing_continuous_or_on_and_off",
    "was_s_he_unable_to_carry_out_daily_routines_due_to_breathlessne" = excluded."was_s_he_unable_to_carry_out_daily_routines_due_to_breathlessne",
    "was_s_he_breathless_while_lying_flat" = excluded."was_s_he_breathless_while_lying_flat",
    "did_s_he_have_fast_breathing" = excluded."did_s_he_have_fast_breathing",
    "for_how_many_days_did_the_fast_breathing_last" = excluded."for_how_many_days_did_the_fast_breathing_last",
    "how_long_did_the_fast_breathing_last" = excluded."how_long_did_the_fast_breathing_last",
    "enter_how_long_the_fast_breathing_lasted_in_days" = excluded."enter_how_long_the_fast_breathing_lasted_in_days",
    "enter_how_long_the_fast_breathing_lasted_in_months" = excluded."enter_how_long_the_fast_breathing_lasted_in_months",
    "how_long_did_the_fast_breathing_last_2" = excluded."how_long_did_the_fast_breathing_last_2",
    "did_you_see_the_lower_chest_wall_ribs_being_pulled_in_as_the_ch" = excluded."did_you_see_the_lower_chest_wall_ribs_being_pulled_in_as_the_ch",
    "did_his_her_breathing_sound_like_any_of_the_following" = excluded."did_his_her_breathing_sound_like_any_of_the_following",
    "did_s_he_have_wheezing" = excluded."did_s_he_have_wheezing",
    "during_the_illness_that_led_to_death_did_his_her_breathing_soun" = excluded."during_the_illness_that_led_to_death_did_his_her_breathing_soun",
    "did_s_he_have_chest_pain" = excluded."did_s_he_have_chest_pain",
    "was_the_chest_pain_severe" = excluded."was_the_chest_pain_severe",
    "how_many_days_before_death_did_s_he_have_chest_pain" = excluded."how_many_days_before_death_did_s_he_have_chest_pain",
    "how_long_did_the_chest_pain_last" = excluded."how_long_did_the_chest_pain_last",
    "enter_how_long_the_chest_pain_lasted_in_hours" = excluded."enter_how_long_the_chest_pain_lasted_in_hours",
    "enter_how_long_the_chest_pain_lasted_in_days" = excluded."enter_how_long_the_chest_pain_lasted_in_days",
    "did_s_he_have_diarrhoea" = excluded."did_s_he_have_diarrhoea",
    "how_long_did_s_he_have_diarrhoea" = excluded."how_long_did_s_he_have_diarrhoea",
    "enter_how_long_s_he_have_diarrhoea_in_days" = excluded."enter_how_long_s_he_have_diarrhoea_in_days",
    "enter_how_long_s_he_have_diarrhoea_in_months" = excluded."enter_how_long_s_he_have_diarrhoea_in_months",
    "for_how_many_days_did_s_he_have_diarrhoea" = excluded."for_how_many_days_did_s_he_have_diarrhoea",
    "how_many_stools_did_the_baby_or_child_have_on_the_day_that_diar" = excluded."how_many_stools_did_the_baby_or_child_have_on_the_day_that_diar",
    "how_many_days_before_death_did_the_diarrhoea_start" = excluded."how_many_days_before_death_did_the_diarrhoea_start",
    "how_long_before_death_did_the_diarrhoea_start" = excluded."how_long_before_death_did_the_diarrhoea_start",
    "enter_how_long_before_death_the_diarrhoea_started_in_days" = excluded."enter_how_long_before_death_the_diarrhoea_started_in_days",
    "enter_how_long_before_death_the_diarrhoea_started_in_months" = excluded."enter_how_long_before_death_the_diarrhoea_started_in_months",
    "did_the_diarrhoea_continue_until_death" = excluded."did_the_diarrhoea_continue_until_death",
    "at_any_time_during_the_final_illness_was_there_blood_in_the_sto" = excluded."at_any_time_during_the_final_illness_was_there_blood_in_the_sto",
    "did_s_he_vomit" = excluded."did_s_he_vomit",
    "for_how_long_did_s_he_vomit" = excluded."for_how_long_did_s_he_vomit",
    "enter_how_long_before_death_s_he_vomited_in_days" = excluded."enter_how_long_before_death_s_he_vomited_in_days",
    "enter_how_long_before_death_s_he_vomited_in_months" = excluded."enter_how_long_before_death_s_he_vomited_in_months",
    "did_s_he_vomit_in_the_week_preceding_the_death" = excluded."did_s_he_vomit_in_the_week_preceding_the_death",
    "did_s_he_vomit_every_time_s_he_ate_and_or_drank" = excluded."did_s_he_vomit_every_time_s_he_ate_and_or_drank",
    "was_there_blood_in_the_vomit" = excluded."was_there_blood_in_the_vomit",
    "was_the_vomit_black" = excluded."was_the_vomit_black",
    "did_s_he_have_abdominal_pain" = excluded."did_s_he_have_abdominal_pain",
    "was_the_abdominal_pain_severe" = excluded."was_the_abdominal_pain_severe",
    "for_how_long_did_s_he_have_abdominal_pain" = excluded."for_how_long_did_s_he_have_abdominal_pain",
    "enter_how_long_s_he_had_abdominal_pain_in_hours" = excluded."enter_how_long_s_he_had_abdominal_pain_in_hours",
    "enter_how_long_s_he_had_abdominal_pain_in_days" = excluded."enter_how_long_s_he_had_abdominal_pain_in_days",
    "enter_how_long_s_he_had_abdominal_pain_in_months" = excluded."enter_how_long_s_he_had_abdominal_pain_in_months",
    "calculated_number_of_days_with_abdominal_pain" = excluded."calculated_number_of_days_with_abdominal_pain",
    "where_was_the_location_of_the_abdominal_pain" = excluded."where_was_the_location_of_the_abdominal_pain",
    "did_s_he_have_a_more_than_usually_protruding_abdomen" = excluded."did_s_he_have_a_more_than_usually_protruding_abdomen",
    "for_how_long_before_death_did_s_he_have_a_more_than_usually_pro" = excluded."for_how_long_before_death_did_s_he_have_a_more_than_usually_pro",
    "enter_how_long_before_death_s_he_had_a_more_than_usually_protru" = excluded."enter_how_long_before_death_s_he_had_a_more_than_usually_protru",
    "enter_how_long_before_death_s_he_had_a_more_than_usually_prot_2" = excluded."enter_how_long_before_death_s_he_had_a_more_than_usually_prot_2",
    "calculated_number_of_days_with_protruding_abdomen" = excluded."calculated_number_of_days_with_protruding_abdomen",
    "how_rapidly_did_s_he_develop_the_protruding_abdomen" = excluded."how_rapidly_did_s_he_develop_the_protruding_abdomen",
    "did_s_he_have_any_mass_in_the_abdomen" = excluded."did_s_he_have_any_mass_in_the_abdomen",
    "for_how_long_did_s_he_have_a_mass_in_the_abdomen" = excluded."for_how_long_did_s_he_have_a_mass_in_the_abdomen",
    "enter_how_long_s_he_had_a_mass_in_the_abdomen_in_days" = excluded."enter_how_long_s_he_had_a_mass_in_the_abdomen_in_days",
    "enter_how_long_s_he_had_a_mass_in_the_abdomen_in_months" = excluded."enter_how_long_s_he_had_a_mass_in_the_abdomen_in_months",
    "calculated_number_of_days_with_a_mass_in_the_abdomen" = excluded."calculated_number_of_days_with_a_mass_in_the_abdomen",
    "did_s_he_have_a_severe_headache" = excluded."did_s_he_have_a_severe_headache",
    "did_s_he_have_a_stiff_or_painful_neck" = excluded."did_s_he_have_a_stiff_or_painful_neck",
    "how_long_before_death_did_s_he_have_a_stiff_or_painful_neck" = excluded."how_long_before_death_did_s_he_have_a_stiff_or_painful_neck",
    "enter_how_long_before_death_did_s_he_have_stiff_or_painful_neck" = excluded."enter_how_long_before_death_did_s_he_have_stiff_or_painful_neck",
    "enter_how_long_before_death_did_s_he_have_stiff_or_painful_ne_2" = excluded."enter_how_long_before_death_did_s_he_have_stiff_or_painful_ne_2",
    "for_how_many_days_before_death_did_s_he_have_stiff_or_painful_n" = excluded."for_how_many_days_before_death_did_s_he_have_stiff_or_painful_n",
    "did_s_he_have_mental_confusion" = excluded."did_s_he_have_mental_confusion",
    "how_long_did_s_he_have_mental_confusion" = excluded."how_long_did_s_he_have_mental_confusion",
    "enter_how_long_s_he_had_mental_confusion_in_days" = excluded."enter_how_long_s_he_had_mental_confusion_in_days",
    "enter_how_long_s_he_had_mental_confusion_in_months" = excluded."enter_how_long_s_he_had_mental_confusion_in_months",
    "for_how_many_months_did_s_he_have_mental_confusion" = excluded."for_how_many_months_did_s_he_have_mental_confusion",
    "was_s_he_unconscious" = excluded."was_s_he_unconscious",
    "how_long_before_death_did_unconsciousness_start" = excluded."how_long_before_death_did_unconsciousness_start",
    "enter_how_long_before_death_unconsciousness_started_in_hours" = excluded."enter_how_long_before_death_unconsciousness_started_in_hours",
    "enter_how_long_before_death_unconsciousness_started_in_days" = excluded."enter_how_long_before_death_unconsciousness_started_in_days",
    "how_many_hours_before_death_did_unconsciousness_start" = excluded."how_many_hours_before_death_did_unconsciousness_start",
    "did_the_unconsciousness_start_suddenly_quickly_at_least_within" = excluded."did_the_unconsciousness_start_suddenly_quickly_at_least_within",
    "did_s_he_experience_any_generalized_convulsions" = excluded."did_s_he_experience_any_generalized_convulsions",
    "did_s_he_become_unconscious_immediately_after_the_convulsion" = excluded."did_s_he_become_unconscious_immediately_after_the_convulsion",
    "did_the_baby_have_convulsions_starting_within_the_first_24_hour" = excluded."did_the_baby_have_convulsions_starting_within_the_first_24_hour",
    "did_the_baby_have_convulsions_starting_more_than_24_hours_after" = excluded."did_the_baby_have_convulsions_starting_more_than_24_hours_after",
    "did_s_he_have_any_urine_problems" = excluded."did_s_he_have_any_urine_problems",
    "during_the_final_illness_did_s_he_ever_pass_blood_in_the_urine" = excluded."during_the_final_illness_did_s_he_ever_pass_blood_in_the_urine",
    "did_s_he_stop_urinating" = excluded."did_s_he_stop_urinating",
    "did_s_he_have_an_ulcer_on_the_foot" = excluded."did_s_he_have_an_ulcer_on_the_foot",
    "did_the_ulcer_on_the_foot_have_pus" = excluded."did_the_ulcer_on_the_foot_have_pus",
    "how_long_did_the_ulcer_on_the_foot_have_pus" = excluded."how_long_did_the_ulcer_on_the_foot_have_pus",
    "enter_how_long_the_ulcer_on_the_foot_had_pus_in_days" = excluded."enter_how_long_the_ulcer_on_the_foot_had_pus_in_days",
    "enter_how_long_the_ulcer_on_the_foot_had_pus_in_months" = excluded."enter_how_long_the_ulcer_on_the_foot_had_pus_in_months",
    "for_how_many_days_did_the_ulcer_on_the_foot_ooze_pus" = excluded."for_how_many_days_did_the_ulcer_on_the_foot_ooze_pus",
    "did_s_he_have_ulcers_or_sores_anywhere_else_on_the_body" = excluded."did_s_he_have_ulcers_or_sores_anywhere_else_on_the_body",
    "did_the_ulcers_or_sores_have_pus" = excluded."did_the_ulcers_or_sores_have_pus",
    "did_s_he_have_any_skin_rash" = excluded."did_s_he_have_any_skin_rash",
    "for_how_many_days_did_s_he_have_the_skin_rash" = excluded."for_how_many_days_did_s_he_have_the_skin_rash",
    "where_was_the_rash" = excluded."where_was_the_rash",
    "did_s_he_have_measles_rash" = excluded."did_s_he_have_measles_rash",
    "did_s_he_ever_have_shingles_or_herpes_zoster" = excluded."did_s_he_ever_have_shingles_or_herpes_zoster",
    "did_her_his_skin_flake_off_in_patches" = excluded."did_her_his_skin_flake_off_in_patches",
    "did_he_she_have_areas_of_the_skin_that_turned_black" = excluded."did_he_she_have_areas_of_the_skin_that_turned_black",
    "did_he_she_have_areas_of_the_skin_with_redness_and_swelling" = excluded."did_he_she_have_areas_of_the_skin_with_redness_and_swelling",
    "did_s_he_bleed_from_the_nose_mouth_or_anus" = excluded."did_s_he_bleed_from_the_nose_mouth_or_anus",
    "did_s_he_have_noticeable_weight_loss" = excluded."did_s_he_have_noticeable_weight_loss",
    "was_s_he_severely_thin_or_wasted" = excluded."was_s_he_severely_thin_or_wasted",
    "did_s_he_have_a_whitish_rash_inside_the_mouth_or_on_the_tongue" = excluded."did_s_he_have_a_whitish_rash_inside_the_mouth_or_on_the_tongue",
    "did_s_he_have_stiffness_of_the_whole_body_or_was_unable_to_open" = excluded."did_s_he_have_stiffness_of_the_whole_body_or_was_unable_to_open",
    "did_s_he_have_puffiness_of_the_face" = excluded."did_s_he_have_puffiness_of_the_face",
    "how_long_did_s_he_have_puffiness_of_the_face" = excluded."how_long_did_s_he_have_puffiness_of_the_face",
    "enter_how_long_s_he_had_puffiness_of_the_face_in_days" = excluded."enter_how_long_s_he_had_puffiness_of_the_face_in_days",
    "enter_how_long_s_he_had_puffiness_of_the_face_in_months" = excluded."enter_how_long_s_he_had_puffiness_of_the_face_in_months",
    "for_how_many_days_did_s_he_have_puffiness_of_the_face" = excluded."for_how_many_days_did_s_he_have_puffiness_of_the_face",
    "did_s_he_have_swollen_legs_or_feet" = excluded."did_s_he_have_swollen_legs_or_feet",
    "how_long_did_the_swelling_last" = excluded."how_long_did_the_swelling_last",
    "enter_how_long_the_swelling_lasted_in_days" = excluded."enter_how_long_the_swelling_lasted_in_days",
    "enter_how_long_the_swelling_lasted_in_months" = excluded."enter_how_long_the_swelling_lasted_in_months",
    "how_many_days_did_the_swelling_last" = excluded."how_many_days_did_the_swelling_last",
    "did_s_he_have_both_feet_swollen" = excluded."did_s_he_have_both_feet_swollen",
    "did_s_he_have_general_swelling_of_the_body" = excluded."did_s_he_have_general_swelling_of_the_body",
    "did_s_he_have_any_lumps_or_sores_in_the_mouth" = excluded."did_s_he_have_any_lumps_or_sores_in_the_mouth",
    "did_s_he_have_lumps_anywhere_else_on_the_body" = excluded."did_s_he_have_lumps_anywhere_else_on_the_body",
    "did_s_he_have_any_lumps_on_the_neck" = excluded."did_s_he_have_any_lumps_on_the_neck",
    "did_s_he_have_any_lumps_on_the_armpit" = excluded."did_s_he_have_any_lumps_on_the_armpit",
    "did_s_he_have_any_lumps_on_the_groin" = excluded."did_s_he_have_any_lumps_on_the_groin",
    "was_s_he_in_any_way_paralysed" = excluded."was_s_he_in_any_way_paralysed",
    "did_s_he_have_paralysis_of_only_one_side_of_the_body" = excluded."did_s_he_have_paralysis_of_only_one_side_of_the_body",
    "did_she_have_paralysis_of_both_legs" = excluded."did_she_have_paralysis_of_both_legs",
    "was_there_difficulty_or_pain_in_swallowing" = excluded."was_there_difficulty_or_pain_in_swallowing",
    "for_how_long_did_s_he_have_difficulty_or_pain_in_swallowing" = excluded."for_how_long_did_s_he_have_difficulty_or_pain_in_swallowing",
    "enter_how_long_before_death_s_he_had_difficulty_or_pain_in_swal" = excluded."enter_how_long_before_death_s_he_had_difficulty_or_pain_in_swal",
    "enter_how_long_before_death_s_he_had_difficulty_or_pain_in_sw_2" = excluded."enter_how_long_before_death_s_he_had_difficulty_or_pain_in_sw_2",
    "for_how_many_days_before_death_did_s_he_have_difficulty_swallow" = excluded."for_how_many_days_before_death_did_s_he_have_difficulty_swallow",
    "did_swallowing_become_impossible" = excluded."did_swallowing_become_impossible",
    "did_s_he_have_yellow_discoloration_of_the_eyes" = excluded."did_s_he_have_yellow_discoloration_of_the_eyes",
    "for_how_long_did_s_he_have_the_yellow_discoloration" = excluded."for_how_long_did_s_he_have_the_yellow_discoloration",
    "enter_how_long_s_he_had_the_yellow_discoloration_in_days" = excluded."enter_how_long_s_he_had_the_yellow_discoloration_in_days",
    "enter_how_long_s_he_had_the_yellow_discoloration_in_months" = excluded."enter_how_long_s_he_had_the_yellow_discoloration_in_months",
    "for_how_many_days_did_s_he_have_the_yellow_discoloration" = excluded."for_how_many_days_did_s_he_have_the_yellow_discoloration",
    "did_her_his_hair_change_in_color_to_a_reddish_or_yellowish_colo" = excluded."did_her_his_hair_change_in_color_to_a_reddish_or_yellowish_colo",
    "did_s_he_look_pale_or_have_pale_palms_eyes_or_nail_beds" = excluded."did_s_he_look_pale_or_have_pale_palms_eyes_or_nail_beds",
    "did_s_he_have_sunken_eyes" = excluded."did_s_he_have_sunken_eyes",
    "was_the_baby_able_to_suckle_or_bottle_feed_within_the_first_24" = excluded."was_the_baby_able_to_suckle_or_bottle_feed_within_the_first_24",
    "did_the_baby_ever_suckle_in_a_normal_way" = excluded."did_the_baby_ever_suckle_in_a_normal_way",
    "did_the_baby_stop_suckling" = excluded."did_the_baby_stop_suckling",
    "how_many_days_after_birth_did_the_baby_stop_suckling" = excluded."how_many_days_after_birth_did_the_baby_stop_suckling",
    "how_long_after_birth_did_the_baby_stop_suckling" = excluded."how_long_after_birth_did_the_baby_stop_suckling",
    "enter_how_long_after_birth_the_baby_stopped_suckling_in_days" = excluded."enter_how_long_after_birth_the_baby_stopped_suckling_in_days",
    "enter_how_long_after_birth_the_baby_stopped_suckling_in_months" = excluded."enter_how_long_after_birth_the_baby_stopped_suckling_in_months",
    "how_many_days_after_birth_did_the_baby_stop_suckling_2" = excluded."how_many_days_after_birth_did_the_baby_stop_suckling_2",
    "did_the_baby_s_body_become_stiff_with_the_back_arched_backwards" = excluded."did_the_baby_s_body_become_stiff_with_the_back_arched_backwards",
    "did_the_baby_have_a_bulging_or_raised_fontanelle" = excluded."did_the_baby_have_a_bulging_or_raised_fontanelle",
    "did_the_baby_have_a_sunken_fontanelle" = excluded."did_the_baby_have_a_sunken_fontanelle",
    "did_the_baby_become_unresponsive_or_unconscious" = excluded."did_the_baby_become_unresponsive_or_unconscious",
    "did_the_baby_become_unresponsive_or_unconscious_within_24_hours" = excluded."did_the_baby_become_unresponsive_or_unconscious_within_24_hours",
    "did_the_baby_become_unresponsive_or_unconscious_more_than_24_ho" = excluded."did_the_baby_become_unresponsive_or_unconscious_more_than_24_ho",
    "did_the_baby_become_cold_to_touch" = excluded."did_the_baby_become_cold_to_touch",
    "did_the_baby_become_lethargic_after_a_period_of_normal_activity" = excluded."did_the_baby_become_lethargic_after_a_period_of_normal_activity",
    "did_the_baby_have_redness_or_pus_oozing_from_the_umbilical_cord" = excluded."did_the_baby_have_redness_or_pus_oozing_from_the_umbilical_cord",
    "did_the_baby_have_skin_ulcer_s_or_sore_s" = excluded."did_the_baby_have_skin_ulcer_s_or_sore_s",
    "did_the_baby_have_yellow_skin_palms_or_soles" = excluded."did_the_baby_have_yellow_skin_palms_or_soles",
    "did_s_h_e_suffer_from_extreme_fatigue" = excluded."did_s_h_e_suffer_from_extreme_fatigue",
    "did_s_he_experience_a_new_loss_change_or_decreased_sense_of_sme" = excluded."did_s_he_experience_a_new_loss_change_or_decreased_sense_of_sme",
    "did_she_have_any_lump_s_and_or_ulcer_s_in_the_breast" = excluded."did_she_have_any_lump_s_and_or_ulcer_s_in_the_breast",
    "did_she_ever_have_a_period_or_menstruate" = excluded."did_she_ever_have_a_period_or_menstruate",
    "did_her_menstrual_period_stop_naturally_because_of_menopause" = excluded."did_her_menstrual_period_stop_naturally_because_of_menopause",
    "did_she_have_vaginal_bleeding_after_cessation_of_menstruation" = excluded."did_she_have_vaginal_bleeding_after_cessation_of_menstruation",
    "was_there_excessive_vaginal_bleeding_in_the_week_prior_to_death" = excluded."was_there_excessive_vaginal_bleeding_in_the_week_prior_to_death",
    "at_the_time_of_death_was_her_period_overdue" = excluded."at_the_time_of_death_was_her_period_overdue",
    "for_how_many_weeks_had_her_period_been_overdue" = excluded."for_how_many_weeks_had_her_period_been_overdue",
    "was_she_pregnant_and_not_yet_in_labour_at_the_time_of_death" = excluded."was_she_pregnant_and_not_yet_in_labour_at_the_time_of_death",
    "did_she_die_during_labour_or_delivery" = excluded."did_she_die_during_labour_or_delivery",
    "did_she_die_after_delivering_a_baby" = excluded."did_she_die_after_delivering_a_baby",
    "did_she_die_within_24_hours_after_delivery" = excluded."did_she_die_within_24_hours_after_delivery",
    "did_she_die_within_6_weeks_after_delivery" = excluded."did_she_die_within_6_weeks_after_delivery",
    "did_she_have_a_pregnancy_that_ended_in_an_abortion_or_miscarria" = excluded."did_she_have_a_pregnancy_that_ended_in_an_abortion_or_miscarria",
    "did_she_attempt_to_terminate_the_pregnancy" = excluded."did_she_attempt_to_terminate_the_pregnancy",
    "did_she_die_less_than_1_year_after_delivery_abortion_or_miscarr" = excluded."did_she_die_less_than_1_year_after_delivery_abortion_or_miscarr",
    "please_confirm_that_in_the_12_months_prior_to_her_death_the_wom" = excluded."please_confirm_that_in_the_12_months_prior_to_her_death_the_wom",
    "did_she_have_a_sharp_abdominal_pain_in_the_first_3_months_of_pr" = excluded."did_she_have_a_sharp_abdominal_pain_in_the_first_3_months_of_pr",
    "did_she_faint_when_she_had_the_sharp_abdominal_pain" = excluded."did_she_faint_when_she_had_the_sharp_abdominal_pain",
    "for_how_many_months_was_she_pregnant" = excluded."for_how_many_months_was_she_pregnant",
    "how_many_babies_was_she_pregnant_with" = excluded."how_many_babies_was_she_pregnant_with",
    "during_pregnancy_did_she_suffer_from_high_blood_pressure" = excluded."during_pregnancy_did_she_suffer_from_high_blood_pressure",
    "did_she_have_foul_smelling_vaginal_discharge_during_pregnancy" = excluded."did_she_have_foul_smelling_vaginal_discharge_during_pregnancy",
    "did_bleeding_occur_while_she_was_pregnant" = excluded."did_bleeding_occur_while_she_was_pregnant",
    "was_there_vaginal_bleeding_during_the_last_3_months_of_pregnanc" = excluded."was_there_vaginal_bleeding_during_the_last_3_months_of_pregnanc",
    "did_she_suffer_from_convulsions_during_the_last_3_months_of_pre" = excluded."did_she_suffer_from_convulsions_during_the_last_3_months_of_pre",
    "did_she_have_blurred_vision_during_the_last_3_months_of_pregnan" = excluded."did_she_have_blurred_vision_during_the_last_3_months_of_pregnan",
    "did_she_have_excessive_bleeding_during_labour_or_delivery" = excluded."did_she_have_excessive_bleeding_during_labour_or_delivery",
    "did_she_have_excessive_bleeding_after_delivery" = excluded."did_she_have_excessive_bleeding_after_delivery",
    "did_she_have_excessive_bleeding_during_or_after_abortion_or_mis" = excluded."did_she_have_excessive_bleeding_during_or_after_abortion_or_mis",
    "did_she_have_foul_smelling_vaginal_discharge_after_delivery_abo" = excluded."did_she_have_foul_smelling_vaginal_discharge_after_delivery_abo",
    "did_she_deliver_or_try_to_deliver_an_abnormally_positioned_baby" = excluded."did_she_deliver_or_try_to_deliver_an_abnormally_positioned_baby",
    "for_how_many_hours_was_she_in_labour" = excluded."for_how_many_hours_was_she_in_labour",
    "was_the_delivery_normal_vaginal_without_forceps_or_vacuum" = excluded."was_the_delivery_normal_vaginal_without_forceps_or_vacuum",
    "was_the_delivery_vaginal_with_forceps_or_vacuum" = excluded."was_the_delivery_vaginal_with_forceps_or_vacuum",
    "was_the_delivery_a_caesarean_section" = excluded."was_the_delivery_a_caesarean_section",
    "was_the_placenta_completely_delivered" = excluded."was_the_placenta_completely_delivered",
    "where_did_she_give_birth" = excluded."where_did_she_give_birth",
    "how_many_births_including_stillbirths_did_she_the_mother_have_b" = excluded."how_many_births_including_stillbirths_did_she_the_mother_have_b",
    "had_she_had_any_previous_caesarean_section" = excluded."had_she_had_any_previous_caesarean_section",
    "did_she_have_an_operation_to_remove_her_uterus_shortly_before_d" = excluded."did_she_have_an_operation_to_remove_her_uterus_shortly_before_d",
    "was_the_child_part_of_a_multiple_birth" = excluded."was_the_child_part_of_a_multiple_birth",
    "is_the_child_health_card_is_available" = excluded."is_the_child_health_card_is_available",
    "enter_the_birth_weight_from_the_card_record_the_weight_in_gramm" = excluded."enter_the_birth_weight_from_the_card_record_the_weight_in_gramm",
    "what_was_the_weight_in_grammes_of_the_deceased_at_birth" = excluded."what_was_the_weight_in_grammes_of_the_deceased_at_birth",
    "at_birth_was_the_baby_smaller_than_usual_weighing_under_2_5_kg" = excluded."at_birth_was_the_baby_smaller_than_usual_weighing_under_2_5_kg",
    "at_birth_was_the_baby_larger_than_usual_weighing_over_4_5_kg" = excluded."at_birth_was_the_baby_larger_than_usual_weighing_over_4_5_kg",
    "how_many_months_long_was_the_pregnancy_before_the_child_was_bor" = excluded."how_many_months_long_was_the_pregnancy_before_the_child_was_bor",
    "were_there_any_complications_during_labour_or_delivery" = excluded."were_there_any_complications_during_labour_or_delivery",
    "was_any_part_of_the_baby_physically_abnormal_at_time_of_deliver" = excluded."was_any_part_of_the_baby_physically_abnormal_at_time_of_deliver",
    "did_the_baby_child_have_a_swelling_or_defect_on_the_back_at_tim" = excluded."did_the_baby_child_have_a_swelling_or_defect_on_the_back_at_tim",
    "did_the_baby_child_have_a_very_large_head_at_time_of_birth" = excluded."did_the_baby_child_have_a_very_large_head_at_time_of_birth",
    "did_the_baby_child_have_a_very_small_head_at_time_of_birth" = excluded."did_the_baby_child_have_a_very_small_head_at_time_of_birth",
    "how_many_hours_did_labour_and_delivery_take" = excluded."how_many_hours_did_labour_and_delivery_take",
    "was_the_baby_born_24_hours_or_more_after_the_water_broke" = excluded."was_the_baby_born_24_hours_or_more_after_the_water_broke",
    "was_the_liquor_foul_smelling" = excluded."was_the_liquor_foul_smelling",
    "what_was_the_colour_of_the_liquor_when_the_waters_broke" = excluded."what_was_the_colour_of_the_liquor_when_the_waters_broke",
    "was_the_delivery_normal_vaginal_without_forceps_or_vacuum_2" = excluded."was_the_delivery_normal_vaginal_without_forceps_or_vacuum_2",
    "was_the_delivery_vaginal_with_forceps_or_vacuum_2" = excluded."was_the_delivery_vaginal_with_forceps_or_vacuum_2",
    "was_the_delivery_a_caesarean_section_2" = excluded."was_the_delivery_a_caesarean_section_2",
    "did_you_the_baby_s_mother_receive_any_vaccinations_since_reachi" = excluded."did_you_the_baby_s_mother_receive_any_vaccinations_since_reachi",
    "did_you_the_baby_s_mother_receive_tetanus_toxoid_tt_vaccine" = excluded."did_you_the_baby_s_mother_receive_tetanus_toxoid_tt_vaccine",
    "during_labour_did_the_you_the_baby_s_mother_suffer_from_fever" = excluded."during_labour_did_the_you_the_baby_s_mother_suffer_from_fever",
    "during_the_last_3_months_of_pregnancy_labour_or_delivery_did_yo" = excluded."during_the_last_3_months_of_pregnancy_labour_or_delivery_did_yo",
    "did_you_the_baby_s_mother_have_diabetes_mellitus" = excluded."did_you_the_baby_s_mother_have_diabetes_mellitus",
    "did_you_the_baby_s_mother_have_foul_smelling_vaginal_discharge" = excluded."did_you_the_baby_s_mother_have_foul_smelling_vaginal_discharge",
    "during_the_last_3_months_of_pregnancy_labour_or_delivery_did_2" = excluded."during_the_last_3_months_of_pregnancy_labour_or_delivery_did_2",
    "during_the_last_3_months_of_pregnancy_did_you_the_baby_s_mother" = excluded."during_the_last_3_months_of_pregnancy_did_you_the_baby_s_mother",
    "did_you_the_baby_s_mother_have_severe_anemia" = excluded."did_you_the_baby_s_mother_have_severe_anemia",
    "did_you_the_baby_s_mother_have_vaginal_bleeding_during_the_last" = excluded."did_you_the_baby_s_mother_have_vaginal_bleeding_during_the_last",
    "did_the_baby_s_bottom_feet_arm_or_hand_come_out_of_the_vagina_b" = excluded."did_the_baby_s_bottom_feet_arm_or_hand_come_out_of_the_vagina_b",
    "was_the_umbilical_cord_wrapped_more_than_once_around_the_neck_o" = excluded."was_the_umbilical_cord_wrapped_more_than_once_around_the_neck_o",
    "was_the_umbilical_cord_delivered_first" = excluded."was_the_umbilical_cord_delivered_first",
    "was_the_baby_blue_in_colour_at_birth" = excluded."was_the_baby_blue_in_colour_at_birth",
    "did_s_he_drink_alcohol" = excluded."did_s_he_drink_alcohol",
    "did_s_he_ever_smoke_tobacco" = excluded."did_s_he_ever_smoke_tobacco",
    "for_how_long_did_s_he_smoke_tobacco" = excluded."for_how_long_did_s_he_smoke_tobacco",
    "how_many_months_years" = excluded."how_many_months_years",
    "did_s_he_ever_smoke_daily" = excluded."did_s_he_ever_smoke_daily",
    "did_s_he_ever_chew_and_or_sniff_tobacco" = excluded."did_s_he_ever_chew_and_or_sniff_tobacco",
    "for_how_long_did_s_he_chew_and_or_sniff_tobacco" = excluded."for_how_long_did_s_he_chew_and_or_sniff_tobacco",
    "how_many_months_years_2" = excluded."how_many_months_years_2",
    "did_s_he_ever_chew_and_or_sniff_tobacco_daily" = excluded."did_s_he_ever_chew_and_or_sniff_tobacco_daily",
    "did_s_he_receive_any_treatment_for_the_illness_that_led_to_deat" = excluded."did_s_he_receive_any_treatment_for_the_illness_that_led_to_deat",
    "did_s_he_receive_oral_rehydration_salts" = excluded."did_s_he_receive_oral_rehydration_salts",
    "did_s_he_receive_or_need_intravenous_fluids_drip_treatment" = excluded."did_s_he_receive_or_need_intravenous_fluids_drip_treatment",
    "did_s_he_receive_or_need_a_blood_transfusion" = excluded."did_s_he_receive_or_need_a_blood_transfusion",
    "did_s_he_receive_or_need_treatment_food_through_a_tube_passed_t" = excluded."did_s_he_receive_or_need_treatment_food_through_a_tube_passed_t",
    "did_s_he_receive_or_need_injectable_antibiotics" = excluded."did_s_he_receive_or_need_injectable_antibiotics",
    "did_s_he_receive_or_need_antiretroviral_therapy_art" = excluded."did_s_he_receive_or_need_antiretroviral_therapy_art",
    "did_s_he_have_or_need_an_operation_for_the_illness" = excluded."did_s_he_have_or_need_an_operation_for_the_illness",
    "did_s_he_have_the_operation_within_1_month_before_death" = excluded."did_s_he_have_the_operation_within_1_month_before_death",
    "did_a_health_care_worker_tell_you_the_cause_of_death" = excluded."did_a_health_care_worker_tell_you_the_cause_of_death",
    "what_did_the_health_care_worker_say" = excluded."what_did_the_health_care_worker_say",
    "has_the_deceased_s_biological_mother_ever_been_told_she_had_hiv" = excluded."has_the_deceased_s_biological_mother_ever_been_told_she_had_hiv",
    "civil_registration_this_refers_to_the_legal_death_certificate_o" = excluded."civil_registration_this_refers_to_the_legal_death_certificate_o",
    "do_you_have_a_death_certificate_from_the_civil_registry" = excluded."do_you_have_a_death_certificate_from_the_civil_registry",
    "death_registration_number_certificate" = excluded."death_registration_number_certificate",
    "is_the_date_of_registration_available" = excluded."is_the_date_of_registration_available",
    "date_of_registration" = excluded."date_of_registration",
    "place_of_registration" = excluded."place_of_registration",
    "national_number_of_deceased" = excluded."national_number_of_deceased",
    "death_certificate_with_cause_of_death_this_refers_to_the_medica" = excluded."death_certificate_with_cause_of_death_this_refers_to_the_medica",
    "was_a_medical_certificate_of_cause_of_death_issued" = excluded."was_a_medical_certificate_of_cause_of_death_issued",
    "can_i_see_the_medical_certificate_of_cause_of_death" = excluded."can_i_see_the_medical_certificate_of_cause_of_death",
    "record_the_immediate_cause_of_death_from_the_certificate_line_1" = excluded."record_the_immediate_cause_of_death_from_the_certificate_line_1",
    "duration_of_the_immediate_cause_of_death_ia" = excluded."duration_of_the_immediate_cause_of_death_ia",
    "record_the_first_antecedent_cause_of_death_from_the_certificate" = excluded."record_the_first_antecedent_cause_of_death_from_the_certificate",
    "duration_of_the_first_antecedent_cause_of_death_ib" = excluded."duration_of_the_first_antecedent_cause_of_death_ib",
    "record_the_second_antecedent_cause_of_death_from_the_certificat" = excluded."record_the_second_antecedent_cause_of_death_from_the_certificat",
    "duration_of_second_antecedent_cause_of_death_ic" = excluded."duration_of_second_antecedent_cause_of_death_ic",
    "record_the_third_antecedent_cause_of_death_from_the_certificate" = excluded."record_the_third_antecedent_cause_of_death_from_the_certificate",
    "duration_of_third_antecedent_cause_of_death" = excluded."duration_of_third_antecedent_cause_of_death",
    "record_the_contributing_cause_s_of_death_from_the_certificate_p" = excluded."record_the_contributing_cause_s_of_death_from_the_certificate_p",
    "duration_of_the_contributing_cause_s_of_death_part2" = excluded."duration_of_the_contributing_cause_s_of_death_part2",
    "end_time_of_the_interview" = excluded."end_time_of_the_interview",
    "inform_the_respondent_that_the_va_interview_has_come_to_an_end" = excluded."inform_the_respondent_that_the_va_interview_has_come_to_an_end",
    "comment_comment" = excluded."comment_comment"
  ;
  return NEW;
end;
$$;

drop trigger if exists sync_who_va_question_answers_after_save on who_va_form_entries;
create trigger sync_who_va_question_answers_after_save
after insert or update of who_va_prefill, submission
on who_va_form_entries
for each row
execute function sync_who_va_question_answer_row();

-- Backfill wide answer rows for entries saved before this migration.
update who_va_form_entries set who_va_prefill = who_va_prefill;
