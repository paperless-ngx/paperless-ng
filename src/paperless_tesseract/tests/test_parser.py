import os
import uuid
from typing import ContextManager
from unittest import mock

from django.test import TestCase, override_settings

from documents.parsers import ParseError, run_convert
from documents.tests.utils import DirectoriesMixin
from paperless_tesseract.parsers import RasterisedDocumentParser, get_text_from_pdf, strip_excess_whitespace

image_to_string_calls = []


def fake_convert(input_file, output_file, **kwargs):
    with open(input_file) as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        with open(output_file % i, "w") as f2:
            f2.write(line.strip())


class FakeImageFile(ContextManager):
    def __init__(self, fname):
        self.fname = fname

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def __enter__(self):
        return os.path.basename(self.fname)




class TestParser(DirectoriesMixin, TestCase):

    def assertContainsStrings(self, content, strings):
        # Asserts that all strings appear in content, in the given order.
        indices = [content.index(s) for s in strings]
        self.assertListEqual(indices, sorted(indices))

    text_cases = [
        ("simple     string", "simple string"),
        (
            "simple    newline\n   testing string",
            "simple newline\ntesting string"
        ),
        (
            "utf-8   строка с пробелами в конце  ",
            "utf-8 строка с пробелами в конце"
        )
    ]

    def test_strip_excess_whitespace(self):
        for source, result in self.text_cases:
            actual_result = strip_excess_whitespace(source)
            self.assertEqual(
                result,
                actual_result,
                "strip_exceess_whitespace({}) != '{}', but '{}'".format(
                    source,
                    result,
                    actual_result
                )
            )

    SAMPLE_FILES = os.path.join(os.path.dirname(__file__), "samples")

    def test_get_text_from_pdf(self):
        text = get_text_from_pdf(os.path.join(self.SAMPLE_FILES, 'simple-digital.pdf'))

        self.assertContainsStrings(text.strip(), ["This is a test document."])

    def test_thumbnail(self):
        parser = RasterisedDocumentParser(uuid.uuid4())
        parser.get_thumbnail(os.path.join(self.SAMPLE_FILES, 'simple-digital.pdf'), "application/pdf")
        # dont really know how to test it, just call it and assert that it does not raise anything.

    @mock.patch("documents.parsers.run_convert")
    def test_thumbnail_fallback(self, m):

        def call_convert(input_file, output_file, **kwargs):
            if ".pdf" in input_file:
                raise ParseError("Does not compute.")
            else:
                run_convert(input_file=input_file, output_file=output_file, **kwargs)

        m.side_effect = call_convert

        parser = RasterisedDocumentParser(uuid.uuid4())
        parser.get_thumbnail(os.path.join(self.SAMPLE_FILES, 'simple-digital.pdf'), "application/pdf")
        # dont really know how to test it, just call it and assert that it does not raise anything.

    def test_get_dpi(self):
        parser = RasterisedDocumentParser(None)

        dpi = parser.get_dpi(os.path.join(self.SAMPLE_FILES, "simple-no-dpi.png"))
        self.assertEqual(dpi, None)

        dpi = parser.get_dpi(os.path.join(self.SAMPLE_FILES, "simple.png"))
        self.assertEqual(dpi, 72)

    def test_simple_digital(self):
        parser = RasterisedDocumentParser(None)

        parser.parse(os.path.join(self.SAMPLE_FILES, "simple-digital.pdf"), "application/pdf")

        self.assertTrue(os.path.isfile(parser.archive_path))

        self.assertContainsStrings(parser.get_text(), ["This is a test document."])

    def test_with_form(self):
        parser = RasterisedDocumentParser(None)

        parser.parse(os.path.join(self.SAMPLE_FILES, "with-form.pdf"), "application/pdf")

        self.assertTrue(os.path.isfile(parser.archive_path))

        self.assertContainsStrings(parser.get_text(), ["Please enter your name in here:", "This is a PDF document with a form."])

    @override_settings(OCR_MODE="redo")
    def test_with_form_error(self):
        parser = RasterisedDocumentParser(None)

        parser.parse(os.path.join(self.SAMPLE_FILES, "with-form.pdf"), "application/pdf")

        self.assertIsNone(parser.archive_path)
        self.assertContainsStrings(parser.get_text(), ["Please enter your name in here:", "This is a PDF document with a form."])

    @override_settings(OCR_MODE="redo")
    @mock.patch("paperless_tesseract.parsers.get_text_from_pdf", lambda _: None)
    def test_with_form_error_notext(self):
        parser = RasterisedDocumentParser(None)

        def f():
            parser.parse(os.path.join(self.SAMPLE_FILES, "with-form.pdf"), "application/pdf")

        self.assertRaises(ParseError, f)

    @override_settings(OCR_MODE="force")
    def test_with_form_force(self):
        parser = RasterisedDocumentParser(None)

        parser.parse(os.path.join(self.SAMPLE_FILES, "with-form.pdf"), "application/pdf")

        self.assertContainsStrings(parser.get_text(), ["Please enter your name in here:", "This is a PDF document with a form."])

    def test_image_simple(self):
        parser = RasterisedDocumentParser(None)

        parser.parse(os.path.join(self.SAMPLE_FILES, "simple.png"), "image/png")

        self.assertTrue(os.path.isfile(parser.archive_path))

        self.assertContainsStrings(parser.get_text(), ["This is a test document."])

    def test_image_simple_alpha_fail(self):
        parser = RasterisedDocumentParser(None)

        def f():
            parser.parse(os.path.join(self.SAMPLE_FILES, "simple-alpha.png"), "image/png")

        self.assertRaises(ParseError, f)

    @mock.patch("paperless_tesseract.parsers.ocrmypdf.ocr")
    def test_image_calc_a4_dpi(self, m):
        parser = RasterisedDocumentParser(None)

        parser.parse(os.path.join(self.SAMPLE_FILES, "simple-no-dpi.png"), "image/png")

        m.assert_called_once()

        args, kwargs = m.call_args

        self.assertEqual(kwargs['image_dpi'], 62)

    @mock.patch("paperless_tesseract.parsers.RasterisedDocumentParser.calculate_a4_dpi")
    def test_image_dpi_fail(self, m):
        m.return_value = None
        parser = RasterisedDocumentParser(None)

        def f():
            parser.parse(os.path.join(self.SAMPLE_FILES, "simple-no-dpi.png"), "image/png")

        self.assertRaises(ParseError, f)

    @override_settings(OCR_IMAGE_DPI=72)
    def test_image_no_dpi_default(self):
        parser = RasterisedDocumentParser(None)

        parser.parse(os.path.join(self.SAMPLE_FILES, "simple-no-dpi.png"), "image/png")

        self.assertTrue(os.path.isfile(parser.archive_path))

        self.assertContainsStrings(parser.get_text().lower(), ["this is a test document."])

    def test_multi_page(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "multi-page-digital.pdf"), "application/pdf")
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(parser.get_text().lower(), ["page 1", "page 2", "page 3"])

    @override_settings(OCR_PAGES=2, OCR_MODE="skip")
    def test_multi_page_pages_skip(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "multi-page-digital.pdf"), "application/pdf")
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(parser.get_text().lower(), ["page 1", "page 2", "page 3"])

    @override_settings(OCR_PAGES=2, OCR_MODE="redo")
    def test_multi_page_pages_redo(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "multi-page-digital.pdf"), "application/pdf")
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(parser.get_text().lower(), ["page 1", "page 2", "page 3"])

    @override_settings(OCR_PAGES=2, OCR_MODE="force")
    def test_multi_page_pages_force(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "multi-page-digital.pdf"), "application/pdf")
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(parser.get_text().lower(), ["page 1", "page 2", "page 3"])

    @override_settings(OOCR_MODE="skip")
    def test_multi_page_analog_pages_skip(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "multi-page-images.pdf"), "application/pdf")
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(parser.get_text().lower(), ["page 1", "page 2", "page 3"])

    @override_settings(OCR_PAGES=2, OCR_MODE="redo")
    def test_multi_page_analog_pages_redo(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "multi-page-images.pdf"), "application/pdf")
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(parser.get_text().lower(), ["page 1", "page 2"])
        self.assertFalse("page 3" in parser.get_text().lower())

    @override_settings(OCR_PAGES=1, OCR_MODE="force")
    def test_multi_page_analog_pages_force(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "multi-page-images.pdf"), "application/pdf")
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(parser.get_text().lower(), ["page 1"])
        self.assertFalse("page 2" in parser.get_text().lower())
        self.assertFalse("page 3" in parser.get_text().lower())

    @override_settings(OCR_MODE="skip_noarchive")
    def test_skip_noarchive_withtext(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "multi-page-digital.pdf"), "application/pdf")
        self.assertIsNone(parser.archive_path)
        self.assertContainsStrings(parser.get_text().lower(), ["page 1", "page 2", "page 3"])

    @override_settings(OCR_MODE="skip_noarchive")
    def test_skip_noarchive_notext(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "multi-page-images.pdf"), "application/pdf")
        self.assertTrue(os.path.join(parser.archive_path))
        self.assertContainsStrings(parser.get_text().lower(), ["page 1", "page 2", "page 3"])


class TestParserFileTypes(DirectoriesMixin, TestCase):

    SAMPLE_FILES = os.path.join(os.path.dirname(__file__), "samples")

    def test_bmp(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "simple.bmp"), "image/bmp")
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertTrue("this is a test document" in parser.get_text().lower())

    def test_jpg(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "simple.jpg"), "image/jpeg")
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertTrue("this is a test document" in parser.get_text().lower())

    @override_settings(OCR_IMAGE_DPI=200)
    def test_gif(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "simple.gif"), "image/gif")
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertTrue("this is a test document" in parser.get_text().lower())

    def test_tiff(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "simple.tif"), "image/tiff")
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertTrue("this is a test document" in parser.get_text().lower())
