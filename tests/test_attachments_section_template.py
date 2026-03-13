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
