import shutil
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from documents.management.commands.document_thumbnails import _process_document
from documents.models import Document
from documents.parsers import get_default_thumbnail
from documents.tests.utils import DirectoriesMixin
from documents.tests.utils import FileSystemAssertsMixin


class TestMakeThumbnails(DirectoriesMixin, FileSystemAssertsMixin, TestCase):
    def make_models(self):
        self.d1 = Document.objects.create(
            checksum="A",
            title="A",
            content="first document",
            mime_type="application/pdf",
            filename="test.pdf",
        )
        shutil.copy(
            Path(__file__).parent / "samples" / "simple.pdf",
            self.d1.source_path,
        )

        self.d2 = Document.objects.create(
            checksum="B",
            title="B",
            content="second document",
            mime_type="application/pdf",
            filename="test2.pdf",
        )
        shutil.copy(
            Path(__file__).parent / "samples" / "simple.pdf",
            self.d2.source_path,
        )

        self.d3 = Document.objects.create(
            checksum="C",
            title="C",
            content="third document",
            mime_type="application/pdf",
            filename="test3.pdf",
        )
        shutil.copy(
            Path(__file__).parent / "samples" / "password-is-test.pdf",
            self.d3.source_path,
        )

    def setUp(self) -> None:
        super().setUp()
        self.make_models()

    def test_process_document(self):
        self.assertIsNotFile(self.d1.thumbnail_path)
        _process_document(self.d1.id)
        self.assertIsFile(self.d1.thumbnail_path)

    def test_process_document_password_protected(self):
        self.assertIsFile(get_default_thumbnail())
        self.assertIsNotFile(self.d3.thumbnail_path)
        _process_document(self.d3.id)
        # Ensure default thumbnail is still there
        self.assertIsFile(get_default_thumbnail())
        self.assertIsFile(self.d3.thumbnail_path)

    @mock.patch("documents.management.commands.document_thumbnails.shutil.move")
    def test_process_document_invalid_mime_type(self, m: mock.Mock):
        self.d1.mime_type = "asdasdasd"
        self.d1.save()

        # .save() triggers filename handling
        m.reset_mock()

        _process_document(self.d1.id)

        # Not called during processing of document
        m.assert_not_called()

    def test_command(self):
        self.assertIsNotFile(self.d1.thumbnail_path)
        self.assertIsNotFile(self.d2.thumbnail_path)
        call_command("document_thumbnails", "--processes", "1")
        self.assertIsFile(self.d1.thumbnail_path)
        self.assertIsFile(self.d2.thumbnail_path)

    def test_command_documentid(self):
        self.assertIsNotFile(self.d1.thumbnail_path)
        self.assertIsNotFile(self.d2.thumbnail_path)
        call_command("document_thumbnails", "--processes", "1", "-d", f"{self.d1.id}")
        self.assertIsFile(self.d1.thumbnail_path)
        self.assertIsNotFile(self.d2.thumbnail_path)
