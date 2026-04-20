from pathlib import Path
import unittest

from jinja2 import Environment, FileSystemLoader


class TestAttachmentsSectionTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template_root = (
            Path(__file__).resolve().parents[1] / "app" / "templates"
        )
        cls.env = Environment(loader=FileSystemLoader(str(template_root)))

    def test_narration_section_renders_audio_image_and_text(self):
        rendered = self.env.get_template(
            "va_formcategory_partials/_attachments_section.html"
        ).render(
            section_code="narration",
            section_title="Narration",
            section_index=0,
            section_data={
                "Audio Note": "/media/audio.mp3",
                "Narrative Image": "/media/image.jpg",
                "Narrative Text": "Free text narrative",
            },
            flip_list=[],
            info_list=[],
            subcategory_render_modes={},
        )

        self.assertIn("<audio controls", rendered)
        self.assertIn('src="/media/image.jpg"', rendered)
        self.assertIn("Free text narrative", rendered)

    def test_document_gallery_section_renders_carousel(self):
        rendered = self.env.get_template(
            "va_formcategory_partials/_attachments_section.html"
        ).render(
            section_code="medical_documents",
            section_title="Medical Documents",
            section_index=1,
            section_data={
                "Doc 1": "/media/doc1.jpg",
                "Doc 2": "/media/doc2.jpg",
            },
            flip_list=[],
            info_list=[],
            subcategory_render_modes={"medical_documents": "media_gallery"},
        )

        self.assertIn('id="medical_documentsCarousel"', rendered)
        self.assertIn('data-bs-target="#medical_documentsCarousel"', rendered)
        self.assertIn('src="/media/doc1.jpg"', rendered)

    def test_non_gallery_section_with_images_renders_table_row(self):
        rendered = self.env.get_template(
            "va_formcategory_partials/_attachments_section.html"
        ).render(
            section_code="narration",
            section_title="Narration",
            section_index=0,
            section_data={
                "Narrative Image": "/media/image.jpg",
            },
            flip_list=[],
            info_list=[],
            subcategory_render_modes={"narration": "default"},
        )

        self.assertNotIn('id="narrationCarousel"', rendered)
        self.assertIn('src="/media/image.jpg"', rendered)

    def test_workflow_panels_no_longer_embed_cod_assessment_panel(self):
        rendered = self.env.get_template(
            "va_formcategory_partials/_attachments_workflow_panels.html"
        ).render(
            summary=[],
            va_action="vacode",
            va_actiontype="vademo_start_coding",
            narrative_qa_enabled=False,
            da_va_coder_review=None,
            da_va_initial_assess=None,
            da_va_final_assess=None,
            vafinexists=False,
            vaerrexists=False,
            vainiexists=False,
            va_initial_assess=None,
            va_final_assess=None,
            va_coder_review=None,
            smartva=None,
            reviewobject=None,
            va_sid="SID-1",
            url_for=lambda *args, **kwargs: "/stub",
            csrf_token=lambda: "token",
        )

        self.assertNotIn("Initial Cause of Death Assessment", rendered)
        self.assertNotIn("Final Cause of Death Assessment", rendered)

    def test_cod_assessment_category_renders_dedicated_panel(self):
        category_config = type(
            "CategoryConfig",
            (),
            {
                "icon_name": "fa-stethoscope",
                "display_label": "VA COD Assessment",
            },
        )()

        rendered = self.env.get_template(
            "va_formcategory_partials/category_va_cod_assessment.html"
        ).render(
            category_config=category_config,
            va_action="vacode",
            va_actiontype="vademo_start_coding",
            va_sid="SID-1",
            vafinexists=False,
            vaerrexists=False,
            vainiexists=False,
            summary_items=["Fever", "Cough"],
            cod_attachments_data={
                "narration": {
                    "Narrative Image": "/media/image.jpg",
                    "Narrative Text": "Free text narrative",
                }
            },
            cod_attachments_labels={"narration": "Narration"},
            cod_attachments_render_modes={"narration": "default"},
            cod_health_history_data={
                "medical_history": {
                    "Tuberculosis": "Yes",
                    "HIV": "No",
                    "Malaria test": "Pending",
                }
            },
            cod_health_history_labels={"medical_history": "Disease / Co-Morbidity"},
            va_usernote=type("UserNote", (), {"note_content": "Important coder note"})(),
            flip_list=[],
            info_list=[],
            va_initial_assess=None,
            va_final_assess=None,
            smartva=None,
            va_previouscategory="vanarrationanddocuments",
            url_for=lambda *args, **kwargs: "/stub",
        )

        self.assertIn("VA COD ASSESSMENT", rendered)
        self.assertIn("Symptoms on VA Interview", rendered)
        self.assertIn("Narration and Documents", rendered)
        self.assertIn("Disease / Co-Morbidity", rendered)
        self.assertIn("Diagnosed by Health Professional", rendered)
        self.assertIn("Notes", rendered)
        self.assertIn("Important coder note", rendered)
        self.assertIn('id="form-container2"', rendered)
        self.assertIn('data-lightbox="narration"', rendered)
        self.assertIn('id="attachmentsLightbox"', rendered)
        self.assertIn("Previous Category", rendered)
        self.assertNotIn("Assign COD", rendered)

    def test_attachments_category_uses_assign_cod_for_workflow_next_step(self):
        category_config = type(
            "CategoryConfig",
            (),
            {
                "icon_name": "fa-file-medical-alt",
                "display_label": "Narration and Documents",
            },
        )()

        rendered = self.env.get_template(
            "va_formcategory_partials/category_attachments.html"
        ).render(
            category_config=category_config,
            category_data={"narration": {"Narrative Text": "Free text narrative"}},
            subcategory_labels={"narration": "Narration"},
            summary=[],
            flip_list=[],
            info_list=[],
            subcategory_render_modes={},
            instance_name="CASE-1",
            va_action="vacode",
            va_actiontype="vademo_start_coding",
            va_sid="SID-1",
            va_previouscategory="social_autopsy",
            va_nextcategory="vacodassessment",
            next_block_message=None,
            narrative_qa_enabled=False,
            da_va_coder_review=None,
            da_va_initial_assess=None,
            da_va_final_assess=None,
            vafinexists=False,
            vaerrexists=False,
            vainiexists=False,
            va_initial_assess=None,
            va_final_assess=None,
            va_coder_review=None,
            smartva=None,
            reviewobject=None,
            url_for=lambda *args, **kwargs: "/stub",
            csrf_token=lambda: "token",
        )

        self.assertIn("Assign COD", rendered)

    def test_cod_assessment_panel_shows_initial_form_on_resume_recode_with_existing_final(self):
        rendered = self.env.get_template(
            "va_formcategory_partials/_va_cod_assessment_panel.html"
        ).render(
            va_action="vacode",
            va_actiontype="varesumecoding",
            va_sid="SID-1",
            vafinexists=True,
            vaerrexists=False,
            vainiexists=False,
            url_for=lambda *args, **kwargs: "/vaform/SID-1/vainitialasses",
        )

        self.assertIn("vainitialasses", rendered)
        self.assertNotIn("vafinalasses", rendered)

    def test_cod_assessment_panel_view_uses_step1_other_conditions_label(self):
        rendered = self.env.get_template(
            "va_formcategory_partials/_va_cod_assessment_panel.html"
        ).render(
            va_action="vacode",
            va_actiontype="vaview",
            va_initial_assess=type(
                "InitialAssess",
                (),
                {
                    "va_immediate_cod": "Immediate Test COD",
                    "va_antecedent_cod": "Antecedent Test COD",
                    "va_other_conditions": "Condition A | Condition B",
                },
            )(),
            va_final_assess=type(
                "FinalAssess",
                (),
                {
                    "va_conclusive_cod": "Final Test COD",
                    "va_finassess_remark": "Technical note for review",
                },
            )(),
            smartva=None,
        )

        self.assertIn("Other significant conditions (if any)", rendered)
        self.assertIn("Condition A | Condition B", rendered)

    def test_coding_dashboard_template_filters_pick_table_by_selected_project(self):
        rendered = self.env.get_template("va_frontpages/va_code.html").render(
            current_user=type("User", (), {"name": "Tester", "timezone": "Asia/Kolkata"})(),
            demo_projects=["SADEMO"],
            get_flashed_messages=lambda with_categories=False: [],
            csrf_token=lambda: "token",
            url_for=lambda *args, **kwargs: "/stub",
        )

        self.assertIn("let ALL_PICK_FORMS = [];", rendered)
        self.assertIn("function applyProjectFilterToPick(hasAllocation)", rendered)
        self.assertIn("ALL_PICK_FORMS.filter", rendered)
        self.assertIn("applyProjectFilterToPick(!!allocData.allocation);", rendered)
