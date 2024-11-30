import shutil
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from documents import tasks
from documents.models import Correspondent
from documents.models import Document
from documents.models import DocumentType
from documents.models import Tag
from documents.sanity_checker import SanityCheckFailedException
from documents.sanity_checker import SanityCheckMessages
from documents.tests.test_classifier import dummy_preprocess
from documents.tests.utils import DirectoriesMixin
from documents.tests.utils import FileSystemAssertsMixin


class TestIndexReindex(DirectoriesMixin, TestCase):
    def test_index_reindex(self):
        Document.objects.create(
            title="test",
            content="my document",
            checksum="wow",
            added=timezone.now(),
            created=timezone.now(),
            modified=timezone.now(),
        )

        tasks.index_reindex()

    def test_index_optimize(self):
        Document.objects.create(
            title="test",
            content="my document",
            checksum="wow",
            added=timezone.now(),
            created=timezone.now(),
            modified=timezone.now(),
        )

        tasks.index_optimize()


class TestClassifier(DirectoriesMixin, FileSystemAssertsMixin, TestCase):
    @mock.patch("documents.tasks.load_classifier")
    def test_train_classifier_no_auto_matching(self, load_classifier):
        tasks.train_classifier()
        load_classifier.assert_not_called()

    @mock.patch("documents.tasks.load_classifier")
    def test_train_classifier_with_auto_tag(self, load_classifier):
        load_classifier.return_value = None
        Tag.objects.create(matching_algorithm=Tag.MATCH_AUTO, name="test")
        tasks.train_classifier()
        load_classifier.assert_called_once()
        self.assertIsNotFile(settings.MODEL_FILE)

    @mock.patch("documents.tasks.load_classifier")
    def test_train_classifier_with_auto_type(self, load_classifier):
        load_classifier.return_value = None
        DocumentType.objects.create(matching_algorithm=Tag.MATCH_AUTO, name="test")
        tasks.train_classifier()
        load_classifier.assert_called_once()
        self.assertIsNotFile(settings.MODEL_FILE)

    @mock.patch("documents.tasks.load_classifier")
    def test_train_classifier_with_auto_correspondent(self, load_classifier):
        load_classifier.return_value = None
        Correspondent.objects.create(matching_algorithm=Tag.MATCH_AUTO, name="test")
        tasks.train_classifier()
        load_classifier.assert_called_once()
        self.assertIsNotFile(settings.MODEL_FILE)

    def test_train_classifier(self):
        c = Correspondent.objects.create(matching_algorithm=Tag.MATCH_AUTO, name="test")
        doc = Document.objects.create(correspondent=c, content="test", title="test")
        self.assertIsNotFile(settings.MODEL_FILE)

        with mock.patch(
            "documents.classifier.DocumentClassifier.preprocess_content",
        ) as pre_proc_mock:
            pre_proc_mock.side_effect = dummy_preprocess

            tasks.train_classifier()
            self.assertIsFile(settings.MODEL_FILE)
            mtime = Path(settings.MODEL_FILE).stat().st_mtime

            tasks.train_classifier()
            self.assertIsFile(settings.MODEL_FILE)
            mtime2 = Path(settings.MODEL_FILE).stat().st_mtime
            self.assertEqual(mtime, mtime2)

            doc.content = "test2"
            doc.save()
            tasks.train_classifier()
            self.assertIsFile(settings.MODEL_FILE)
            mtime3 = Path(settings.MODEL_FILE).stat().st_mtime
            self.assertNotEqual(mtime2, mtime3)


class TestSanityCheck(DirectoriesMixin, TestCase):
    @mock.patch("documents.tasks.sanity_checker.check_sanity")
    def test_sanity_check_success(self, m):
        m.return_value = SanityCheckMessages()
        self.assertEqual(tasks.sanity_check(), "No issues detected.")
        m.assert_called_once()

    @mock.patch("documents.tasks.sanity_checker.check_sanity")
    def test_sanity_check_error(self, m):
        messages = SanityCheckMessages()
        messages.error(None, "Some error")
        m.return_value = messages
        self.assertRaises(SanityCheckFailedException, tasks.sanity_check)
        m.assert_called_once()

    @mock.patch("documents.tasks.sanity_checker.check_sanity")
    def test_sanity_check_warning(self, m):
        messages = SanityCheckMessages()
        messages.warning(None, "Some warning")
        m.return_value = messages
        self.assertEqual(
            tasks.sanity_check(),
            "Sanity check exited with warnings. See log.",
        )
        m.assert_called_once()

    @mock.patch("documents.tasks.sanity_checker.check_sanity")
    def test_sanity_check_info(self, m):
        messages = SanityCheckMessages()
        messages.info(None, "Some info")
        m.return_value = messages
        self.assertEqual(
            tasks.sanity_check(),
            "Sanity check exited with infos. See log.",
        )
        m.assert_called_once()


class TestBulkUpdate(DirectoriesMixin, TestCase):
    def test_bulk_update_documents(self):
        doc1 = Document.objects.create(
            title="test",
            content="my document",
            checksum="wow",
            added=timezone.now(),
            created=timezone.now(),
            modified=timezone.now(),
        )

        tasks.bulk_update_documents([doc1.pk])


class TestEmptyTrashTask(DirectoriesMixin, FileSystemAssertsMixin, TestCase):
    """
    GIVEN:
        - Existing document in trash
    WHEN:
        - Empty trash task is called without doc_ids
    THEN:
        - Document is only deleted if it has been in trash for more than delay (default 30 days)
    """

    def test_empty_trash(self):
        doc = Document.objects.create(
            title="test",
            content="my document",
            checksum="wow",
            added=timezone.now(),
            created=timezone.now(),
            modified=timezone.now(),
        )

        doc.delete()
        self.assertEqual(Document.global_objects.count(), 1)
        self.assertEqual(Document.objects.count(), 0)
        tasks.empty_trash()
        self.assertEqual(Document.global_objects.count(), 1)

        doc.deleted_at = timezone.now() - timedelta(days=31)
        doc.save()

        tasks.empty_trash()
        self.assertEqual(Document.global_objects.count(), 0)


class TestUpdateContent(DirectoriesMixin, TestCase):
    def test_update_content_maybe_archive_file(self):
        """
        GIVEN:
            - Existing document with archive file
        WHEN:
            - Update content task is called
        THEN:
            - Document is reprocessed, content and checksum are updated
        """
        sample1 = self.dirs.scratch_dir / "sample.pdf"
        shutil.copy(
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000001.pdf",
            sample1,
        )
        sample1_archive = self.dirs.archive_dir / "sample_archive.pdf"
        shutil.copy(
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000001.pdf",
            sample1_archive,
        )
        doc = Document.objects.create(
            title="test",
            content="my document",
            checksum="wow",
            archive_checksum="wow",
            filename=sample1,
            mime_type="application/pdf",
            archive_filename=sample1_archive,
        )

        tasks.update_document_content_maybe_archive_file(doc.pk)
        self.assertNotEqual(Document.objects.get(pk=doc.pk).content, "test")
        self.assertNotEqual(Document.objects.get(pk=doc.pk).archive_checksum, "wow")

    def test_update_content_maybe_archive_file_no_archive(self):
        """
        GIVEN:
            - Existing document without archive file
        WHEN:
            - Update content task is called
        THEN:
            - Document is reprocessed, content is updated
        """
        sample1 = self.dirs.scratch_dir / "sample.pdf"
        shutil.copy(
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000001.pdf",
            sample1,
        )
        doc = Document.objects.create(
            title="test",
            content="my document",
            checksum="wow",
            filename=sample1,
            mime_type="application/pdf",
        )

        tasks.update_document_content_maybe_archive_file(doc.pk)
        self.assertNotEqual(Document.objects.get(pk=doc.pk).content, "test")
