import datetime
import os
import shutil
import stat
import tempfile
import zoneinfo
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

from dateutil import tz
from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from guardian.core import ObjectPermissionChecker

from documents.consumer import ConsumerError
from documents.data_models import DocumentMetadataOverrides
from documents.models import Correspondent
from documents.models import CustomField
from documents.models import Document
from documents.models import DocumentType
from documents.models import StoragePath
from documents.models import Tag
from documents.parsers import DocumentParser
from documents.parsers import ParseError
from documents.plugins.helpers import ProgressStatusOptions
from documents.tasks import sanity_check
from documents.tests.utils import DirectoriesMixin
from documents.tests.utils import FileSystemAssertsMixin
from documents.tests.utils import GetConsumerMixin


class _BaseTestParser(DocumentParser):
    def get_settings(self):
        """
        This parser does not implement additional settings yet
        """
        return None


class DummyParser(_BaseTestParser):
    def __init__(self, logging_group, scratch_dir, archive_path):
        super().__init__(logging_group, None)
        _, self.fake_thumb = tempfile.mkstemp(suffix=".webp", dir=scratch_dir)
        self.archive_path = archive_path

    def get_thumbnail(self, document_path, mime_type, file_name=None):
        return self.fake_thumb

    def parse(self, document_path, mime_type, file_name=None):
        self.text = "The Text"


class CopyParser(_BaseTestParser):
    def get_thumbnail(self, document_path, mime_type, file_name=None):
        return self.fake_thumb

    def __init__(self, logging_group, progress_callback=None):
        super().__init__(logging_group, progress_callback)
        _, self.fake_thumb = tempfile.mkstemp(suffix=".webp", dir=self.tempdir)

    def parse(self, document_path, mime_type, file_name=None):
        self.text = "The text"
        self.archive_path = os.path.join(self.tempdir, "archive.pdf")
        shutil.copy(document_path, self.archive_path)


class FaultyParser(_BaseTestParser):
    def __init__(self, logging_group, scratch_dir):
        super().__init__(logging_group)
        _, self.fake_thumb = tempfile.mkstemp(suffix=".webp", dir=scratch_dir)

    def get_thumbnail(self, document_path, mime_type, file_name=None):
        return self.fake_thumb

    def parse(self, document_path, mime_type, file_name=None):
        raise ParseError("Does not compute.")


class FaultyGenericExceptionParser(_BaseTestParser):
    def __init__(self, logging_group, scratch_dir):
        super().__init__(logging_group)
        _, self.fake_thumb = tempfile.mkstemp(suffix=".webp", dir=scratch_dir)

    def get_thumbnail(self, document_path, mime_type, file_name=None):
        return self.fake_thumb

    def parse(self, document_path, mime_type, file_name=None):
        raise Exception("Generic exception.")


def fake_magic_from_file(file, mime=False):
    if mime:
        if file.name.startswith("invalid_pdf"):
            return "application/octet-stream"
        if os.path.splitext(file)[1] == ".pdf":
            return "application/pdf"
        elif os.path.splitext(file)[1] == ".png":
            return "image/png"
        elif os.path.splitext(file)[1] == ".webp":
            return "image/webp"
        else:
            return "unknown"
    else:
        return "A verbose string that describes the contents of the file"


@mock.patch("documents.consumer.magic.from_file", fake_magic_from_file)
class TestConsumer(
    DirectoriesMixin,
    FileSystemAssertsMixin,
    GetConsumerMixin,
    TestCase,
):
    def _assert_first_last_send_progress(
        self,
        first_status=ProgressStatusOptions.STARTED,
        last_status=ProgressStatusOptions.SUCCESS,
        first_progress=0,
        first_progress_max=100,
        last_progress=100,
        last_progress_max=100,
    ):
        self.assertGreaterEqual(len(self.status.payloads), 2)

        payload = self.status.payloads[0]
        self.assertEqual(payload["data"]["current_progress"], first_progress)
        self.assertEqual(payload["data"]["max_progress"], first_progress_max)
        self.assertEqual(payload["data"]["status"], first_status)

        payload = self.status.payloads[-1]

        self.assertEqual(payload["data"]["current_progress"], last_progress)
        self.assertEqual(payload["data"]["max_progress"], last_progress_max)
        self.assertEqual(payload["data"]["status"], last_status)

    def make_dummy_parser(self, logging_group, progress_callback=None):
        return DummyParser(
            logging_group,
            self.dirs.scratch_dir,
            self.get_test_archive_file(),
        )

    def make_faulty_parser(self, logging_group, progress_callback=None):
        return FaultyParser(logging_group, self.dirs.scratch_dir)

    def make_faulty_generic_exception_parser(
        self,
        logging_group,
        progress_callback=None,
    ):
        return FaultyGenericExceptionParser(logging_group, self.dirs.scratch_dir)

    def setUp(self):
        super().setUp()

        patcher = mock.patch("documents.parsers.document_consumer_declaration.send")
        m = patcher.start()
        m.return_value = [
            (
                None,
                {
                    "parser": self.make_dummy_parser,
                    "mime_types": {"application/pdf": ".pdf"},
                    "weight": 0,
                },
            ),
        ]
        self.addCleanup(patcher.stop)

    def get_test_file(self):
        src = (
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000001.pdf"
        )
        dst = self.dirs.scratch_dir / "sample.pdf"
        shutil.copy(src, dst)
        return dst

    def get_test_file2(self):
        src = (
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000002.pdf"
        )
        dst = self.dirs.scratch_dir / "sample2.pdf"
        shutil.copy(src, dst)
        return dst

    def get_test_archive_file(self):
        src = (
            Path(__file__).parent / "samples" / "documents" / "archive" / "0000001.pdf"
        )
        dst = self.dirs.scratch_dir / "sample_archive.pdf"
        shutil.copy(src, dst)
        return dst

    @override_settings(FILENAME_FORMAT=None, TIME_ZONE="America/Chicago")
    def testNormalOperation(self):
        filename = self.get_test_file()

        # Get the local time, as an aware datetime
        # Roughly equal to file modification time
        rough_create_date_local = timezone.localtime(timezone.now())

        with self.get_consumer(filename) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertIsNotNone(document)

        self.assertEqual(document.content, "The Text")
        self.assertEqual(
            document.title,
            os.path.splitext(os.path.basename(filename))[0],
        )
        self.assertIsNone(document.correspondent)
        self.assertIsNone(document.document_type)
        self.assertEqual(document.filename, "0000001.pdf")
        self.assertEqual(document.archive_filename, "0000001.pdf")

        self.assertIsFile(document.source_path)

        self.assertIsFile(document.thumbnail_path)

        self.assertIsFile(document.archive_path)

        self.assertEqual(document.checksum, "42995833e01aea9b3edee44bbfdd7ce1")
        self.assertEqual(document.archive_checksum, "62acb0bcbfbcaa62ca6ad3668e4e404b")

        self.assertIsNotFile(filename)

        self._assert_first_last_send_progress()

        # Convert UTC time from DB to local time
        document_date_local = timezone.localtime(document.created)

        self.assertEqual(
            document_date_local.tzinfo,
            zoneinfo.ZoneInfo("America/Chicago"),
        )
        self.assertEqual(document_date_local.tzinfo, rough_create_date_local.tzinfo)
        self.assertEqual(document_date_local.year, rough_create_date_local.year)
        self.assertEqual(document_date_local.month, rough_create_date_local.month)
        self.assertEqual(document_date_local.day, rough_create_date_local.day)
        self.assertEqual(document_date_local.hour, rough_create_date_local.hour)
        self.assertEqual(document_date_local.minute, rough_create_date_local.minute)
        # Skipping seconds and more precise

    @override_settings(FILENAME_FORMAT=None)
    def testDeleteMacFiles(self):
        # https://github.com/jonaswinkler/paperless-ng/discussions/1037

        filename = self.get_test_file()
        shadow_file = os.path.join(self.dirs.scratch_dir, "._sample.pdf")

        shutil.copy(filename, shadow_file)

        self.assertIsFile(shadow_file)

        with self.get_consumer(filename) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertIsNotNone(document)

        self.assertIsFile(document.source_path)

        self.assertIsNotFile(shadow_file)
        self.assertIsNotFile(filename)

    def testOverrideFilename(self):
        filename = self.get_test_file()
        override_filename = "Statement for November.pdf"

        with self.get_consumer(
            filename,
            DocumentMetadataOverrides(filename=override_filename),
        ) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertIsNotNone(document)

        self.assertEqual(document.title, "Statement for November")

        self._assert_first_last_send_progress()

    def testOverrideTitle(self):
        with self.get_consumer(
            self.get_test_file(),
            DocumentMetadataOverrides(title="Override Title"),
        ) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertIsNotNone(document)

        self.assertEqual(document.title, "Override Title")
        self._assert_first_last_send_progress()

    def testOverrideTitleInvalidPlaceholders(self):
        with self.assertLogs("paperless.consumer", level="ERROR") as cm:
            with self.get_consumer(
                self.get_test_file(),
                DocumentMetadataOverrides(title="Override {correspondent]"),
            ) as consumer:
                consumer.run()

                document = Document.objects.first()

            self.assertIsNotNone(document)

            self.assertEqual(document.title, "sample")
            expected_str = "Error occurred parsing title override 'Override {correspondent]', falling back to original"
            self.assertIn(expected_str, cm.output[0])

    def testOverrideCorrespondent(self):
        c = Correspondent.objects.create(name="test")

        with self.get_consumer(
            self.get_test_file(),
            DocumentMetadataOverrides(correspondent_id=c.pk),
        ) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertIsNotNone(document)

        self.assertEqual(document.correspondent.id, c.id)
        self._assert_first_last_send_progress()

    def testOverrideDocumentType(self):
        dt = DocumentType.objects.create(name="test")

        with self.get_consumer(
            self.get_test_file(),
            DocumentMetadataOverrides(document_type_id=dt.pk),
        ) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertEqual(document.document_type.id, dt.id)
        self._assert_first_last_send_progress()

    def testOverrideStoragePath(self):
        sp = StoragePath.objects.create(name="test")

        with self.get_consumer(
            self.get_test_file(),
            DocumentMetadataOverrides(storage_path_id=sp.pk),
        ) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertEqual(document.storage_path.id, sp.id)
        self._assert_first_last_send_progress()

    def testOverrideTags(self):
        t1 = Tag.objects.create(name="t1")
        t2 = Tag.objects.create(name="t2")
        t3 = Tag.objects.create(name="t3")

        with self.get_consumer(
            self.get_test_file(),
            DocumentMetadataOverrides(tag_ids=[t1.id, t3.id]),
        ) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertIn(t1, document.tags.all())
        self.assertNotIn(t2, document.tags.all())
        self.assertIn(t3, document.tags.all())
        self._assert_first_last_send_progress()

    def testOverrideCustomFields(self):
        cf1 = CustomField.objects.create(name="Custom Field 1", data_type="string")
        cf2 = CustomField.objects.create(
            name="Custom Field 2",
            data_type="integer",
        )
        cf3 = CustomField.objects.create(
            name="Custom Field 3",
            data_type="url",
        )

        with self.get_consumer(
            self.get_test_file(),
            DocumentMetadataOverrides(custom_field_ids=[cf1.id, cf3.id]),
        ) as consumer:
            consumer.run()

            document = Document.objects.first()

        fields_used = [
            field_instance.field for field_instance in document.custom_fields.all()
        ]
        self.assertIn(cf1, fields_used)
        self.assertNotIn(cf2, fields_used)
        self.assertIn(cf3, fields_used)
        self._assert_first_last_send_progress()

    def testOverrideAsn(self):
        with self.get_consumer(
            self.get_test_file(),
            DocumentMetadataOverrides(asn=123),
        ) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertEqual(document.archive_serial_number, 123)
        self._assert_first_last_send_progress()

    def testOverrideTitlePlaceholders(self):
        c = Correspondent.objects.create(name="Correspondent Name")
        dt = DocumentType.objects.create(name="DocType Name")

        with self.get_consumer(
            self.get_test_file(),
            DocumentMetadataOverrides(
                correspondent_id=c.pk,
                document_type_id=dt.pk,
                title="{correspondent}{document_type} {added_month}-{added_year_short}",
            ),
        ) as consumer:
            consumer.run()

            document = Document.objects.first()

        now = timezone.now()
        self.assertEqual(document.title, f"{c.name}{dt.name} {now.strftime('%m-%y')}")
        self._assert_first_last_send_progress()

    def testOverrideOwner(self):
        testuser = User.objects.create(username="testuser")

        with self.get_consumer(
            self.get_test_file(),
            DocumentMetadataOverrides(owner_id=testuser.pk),
        ) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertEqual(document.owner, testuser)
        self._assert_first_last_send_progress()

    def testOverridePermissions(self):
        testuser = User.objects.create(username="testuser")
        testgroup = Group.objects.create(name="testgroup")

        with self.get_consumer(
            self.get_test_file(),
            DocumentMetadataOverrides(
                view_users=[testuser.pk],
                view_groups=[testgroup.pk],
            ),
        ) as consumer:
            consumer.run()

            document = Document.objects.first()

        user_checker = ObjectPermissionChecker(testuser)
        self.assertTrue(user_checker.has_perm("view_document", document))
        group_checker = ObjectPermissionChecker(testgroup)
        self.assertTrue(group_checker.has_perm("view_document", document))
        self._assert_first_last_send_progress()

    def testNotAFile(self):
        with self.get_consumer(Path("non-existing-file")) as consumer:
            with self.assertRaisesMessage(ConsumerError, "File not found"):
                consumer.run()
        self._assert_first_last_send_progress(last_status="FAILED")

    def testDuplicates1(self):
        with self.get_consumer(self.get_test_file()) as consumer:
            consumer.run()

        with self.get_consumer(self.get_test_file()) as consumer:
            with self.assertRaisesMessage(ConsumerError, "It is a duplicate"):
                consumer.run()

        self._assert_first_last_send_progress(last_status="FAILED")

    def testDuplicates2(self):
        with self.get_consumer(self.get_test_file()) as consumer:
            consumer.run()

        with self.get_consumer(self.get_test_archive_file()) as consumer:
            with self.assertRaisesMessage(ConsumerError, "It is a duplicate"):
                consumer.run()

        self._assert_first_last_send_progress(last_status="FAILED")

    def testDuplicates3(self):
        with self.get_consumer(self.get_test_archive_file()) as consumer:
            consumer.run()
        with self.get_consumer(self.get_test_file()) as consumer:
            consumer.run()

    def testDuplicateInTrash(self):
        with self.get_consumer(self.get_test_file()) as consumer:
            consumer.run()

        Document.objects.all().delete()

        with self.get_consumer(self.get_test_file()) as consumer:
            with self.assertRaisesMessage(ConsumerError, "document is in the trash"):
                consumer.run()

    def testAsnExists(self):
        with self.get_consumer(
            self.get_test_file(),
            DocumentMetadataOverrides(asn=123),
        ) as consumer:
            consumer.run()

        with self.get_consumer(
            self.get_test_file2(),
            DocumentMetadataOverrides(asn=123),
        ) as consumer:
            with self.assertRaisesMessage(ConsumerError, "ASN 123 already exists"):
                consumer.run()

    def testAsnExistsInTrash(self):
        with self.get_consumer(
            self.get_test_file(),
            DocumentMetadataOverrides(asn=123),
        ) as consumer:
            consumer.run()

            document = Document.objects.first()
            document.delete()

        with self.get_consumer(
            self.get_test_file2(),
            DocumentMetadataOverrides(asn=123),
        ) as consumer:
            with self.assertRaisesMessage(ConsumerError, "document is in the trash"):
                consumer.run()

    @mock.patch("documents.parsers.document_consumer_declaration.send")
    def testNoParsers(self, m):
        m.return_value = []

        with self.get_consumer(self.get_test_file()) as consumer:
            with self.assertRaisesMessage(
                ConsumerError,
                "sample.pdf: Unsupported mime type application/pdf",
            ):
                consumer.run()

        self._assert_first_last_send_progress(last_status="FAILED")

    @mock.patch("documents.parsers.document_consumer_declaration.send")
    def testFaultyParser(self, m):
        m.return_value = [
            (
                None,
                {
                    "parser": self.make_faulty_parser,
                    "mime_types": {"application/pdf": ".pdf"},
                    "weight": 0,
                },
            ),
        ]

        with self.get_consumer(self.get_test_file()) as consumer:
            with self.assertRaisesMessage(
                ConsumerError,
                "sample.pdf: Error occurred while consuming document sample.pdf: Does not compute.",
            ):
                consumer.run()

        self._assert_first_last_send_progress(last_status="FAILED")

    @mock.patch("documents.parsers.document_consumer_declaration.send")
    def testGenericParserException(self, m):
        m.return_value = [
            (
                None,
                {
                    "parser": self.make_faulty_generic_exception_parser,
                    "mime_types": {"application/pdf": ".pdf"},
                    "weight": 0,
                },
            ),
        ]

        with self.get_consumer(self.get_test_file()) as consumer:
            with self.assertRaisesMessage(
                ConsumerError,
                "sample.pdf: Unexpected error while consuming document sample.pdf: Generic exception.",
            ):
                consumer.run()

        self._assert_first_last_send_progress(last_status="FAILED")

    @mock.patch("documents.consumer.ConsumerPlugin._write")
    def testPostSaveError(self, m):
        filename = self.get_test_file()
        m.side_effect = OSError("NO.")

        with self.get_consumer(self.get_test_file()) as consumer:
            with self.assertRaisesMessage(
                ConsumerError,
                "sample.pdf: The following error occurred while storing document sample.pdf after parsing: NO.",
            ):
                consumer.run()

        self._assert_first_last_send_progress(last_status="FAILED")

        # file not deleted
        self.assertIsFile(filename)

        # Database empty
        self.assertEqual(Document.objects.all().count(), 0)

    @override_settings(FILENAME_FORMAT="{correspondent}/{title}")
    def testFilenameHandling(self):
        with self.get_consumer(
            self.get_test_file(),
            DocumentMetadataOverrides(title="new docs"),
        ) as consumer:
            consumer.run()

        document = Document.objects.first()

        self.assertEqual(document.title, "new docs")
        self.assertEqual(document.filename, "none/new docs.pdf")
        self.assertEqual(document.archive_filename, "none/new docs.pdf")

        self._assert_first_last_send_progress()

    @override_settings(FILENAME_FORMAT="{correspondent}/{title}")
    @mock.patch("documents.signals.handlers.generate_unique_filename")
    def testFilenameHandlingUnstableFormat(self, m):
        filenames = ["this", "that", "now this", "i cannot decide"]

        def get_filename():
            f = filenames.pop()
            filenames.insert(0, f)
            return f

        m.side_effect = lambda f, archive_filename=False: get_filename()

        Tag.objects.create(name="test", is_inbox_tag=True)

        with self.get_consumer(
            self.get_test_file(),
            DocumentMetadataOverrides(title="new docs"),
        ) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertEqual(document.title, "new docs")
        self.assertIsNotNone(document.title)
        self.assertIsFile(document.source_path)
        self.assertIsFile(document.archive_path)

        self._assert_first_last_send_progress()

    @mock.patch("documents.consumer.load_classifier")
    def testClassifyDocument(self, m):
        correspondent = Correspondent.objects.create(
            name="test",
            matching_algorithm=Correspondent.MATCH_AUTO,
        )
        dtype = DocumentType.objects.create(
            name="test",
            matching_algorithm=DocumentType.MATCH_AUTO,
        )
        t1 = Tag.objects.create(name="t1", matching_algorithm=Tag.MATCH_AUTO)
        t2 = Tag.objects.create(name="t2", matching_algorithm=Tag.MATCH_AUTO)

        m.return_value = MagicMock()
        m.return_value.predict_correspondent.return_value = correspondent.pk
        m.return_value.predict_document_type.return_value = dtype.pk
        m.return_value.predict_tags.return_value = [t1.pk]

        with self.get_consumer(self.get_test_file()) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertEqual(document.correspondent, correspondent)
        self.assertEqual(document.document_type, dtype)
        self.assertIn(t1, document.tags.all())
        self.assertNotIn(t2, document.tags.all())

        self._assert_first_last_send_progress()

    @override_settings(CONSUMER_DELETE_DUPLICATES=True)
    def test_delete_duplicate(self):
        dst = self.get_test_file()
        self.assertIsFile(dst)

        with self.get_consumer(dst) as consumer:
            consumer.run()

            document = Document.objects.first()

        self._assert_first_last_send_progress()

        self.assertIsNotFile(dst)
        self.assertIsNotNone(document)

        dst = self.get_test_file()
        self.assertIsFile(dst)

        with self.get_consumer(dst) as consumer:
            with self.assertRaises(ConsumerError):
                consumer.run()

        self.assertIsNotFile(dst)
        self._assert_first_last_send_progress(last_status="FAILED")

    @override_settings(CONSUMER_DELETE_DUPLICATES=False)
    def test_no_delete_duplicate(self):
        dst = self.get_test_file()
        self.assertIsFile(dst)

        with self.get_consumer(dst) as consumer:
            consumer.run()

            document = Document.objects.first()

        self._assert_first_last_send_progress()

        self.assertIsNotFile(dst)
        self.assertIsNotNone(document)

        dst = self.get_test_file()
        self.assertIsFile(dst)

        with self.get_consumer(dst) as consumer:
            with self.assertRaisesRegex(
                ConsumerError,
                r"sample\.pdf: Not consuming sample\.pdf: It is a duplicate of sample \(#\d+\)",
            ):
                consumer.run()

        self.assertIsFile(dst)
        self._assert_first_last_send_progress(last_status="FAILED")

    @override_settings(FILENAME_FORMAT="{title}")
    @mock.patch("documents.parsers.document_consumer_declaration.send")
    def test_similar_filenames(self, m):
        shutil.copy(
            Path(__file__).parent / "samples" / "simple.pdf",
            settings.CONSUMPTION_DIR / "simple.pdf",
        )
        shutil.copy(
            Path(__file__).parent / "samples" / "simple.png",
            settings.CONSUMPTION_DIR / "simple.png",
        )
        shutil.copy(
            Path(__file__).parent / "samples" / "simple-noalpha.png",
            settings.CONSUMPTION_DIR / "simple.png.pdf",
        )
        m.return_value = [
            (
                None,
                {
                    "parser": CopyParser,
                    "mime_types": {"application/pdf": ".pdf", "image/png": ".png"},
                    "weight": 0,
                },
            ),
        ]

        with self.get_consumer(settings.CONSUMPTION_DIR / "simple.png") as consumer:
            consumer.run()

            doc1 = Document.objects.filter(pk=1).first()

        with self.get_consumer(settings.CONSUMPTION_DIR / "simple.pdf") as consumer:
            consumer.run()

            doc2 = Document.objects.filter(pk=2).first()

        with self.get_consumer(settings.CONSUMPTION_DIR / "simple.png.pdf") as consumer:
            consumer.run()

            doc3 = Document.objects.filter(pk=3).first()

        self.assertEqual(doc1.filename, "simple.png")
        self.assertEqual(doc1.archive_filename, "simple.pdf")

        self.assertEqual(doc2.filename, "simple.pdf")
        self.assertEqual(doc2.archive_filename, "simple_01.pdf")

        self.assertEqual(doc3.filename, "simple.png.pdf")
        self.assertEqual(doc3.archive_filename, "simple.png.pdf")

        sanity_check()

    @mock.patch("documents.consumer.run_subprocess")
    def test_try_to_clean_invalid_pdf(self, m):
        shutil.copy(
            Path(__file__).parent / "samples" / "invalid_pdf.pdf",
            settings.CONSUMPTION_DIR / "invalid_pdf.pdf",
        )
        with self.get_consumer(
            settings.CONSUMPTION_DIR / "invalid_pdf.pdf",
        ) as consumer:
            # fails because no qpdf
            self.assertRaises(ConsumerError, consumer.run)

            m.assert_called_once()

            args, _ = m.call_args

            command = args[0]

            self.assertEqual(command[0], "qpdf")
            self.assertEqual(command[1], "--replace-input")


@mock.patch("documents.consumer.magic.from_file", fake_magic_from_file)
class TestConsumerCreatedDate(DirectoriesMixin, GetConsumerMixin, TestCase):
    def setUp(self):
        super().setUp()

    def test_consume_date_from_content(self):
        """
        GIVEN:
            - File content with date in DMY (default) format

        THEN:
            - Should parse the date from the file content
        """
        src = (
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000005.pdf"
        )
        dst = self.dirs.scratch_dir / "sample.pdf"
        shutil.copy(src, dst)

        with self.get_consumer(dst) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertEqual(
            document.created,
            datetime.datetime(1996, 2, 20, tzinfo=tz.gettz(settings.TIME_ZONE)),
        )

    @override_settings(FILENAME_DATE_ORDER="YMD")
    def test_consume_date_from_filename(self):
        """
        GIVEN:
            - File content with date in DMY (default) format
            - Filename with date in YMD format

        THEN:
            - Should parse the date from the filename
        """
        src = (
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000005.pdf"
        )
        dst = self.dirs.scratch_dir / "Scan - 2022-02-01.pdf"
        shutil.copy(src, dst)

        with self.get_consumer(dst) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertEqual(
            document.created,
            datetime.datetime(2022, 2, 1, tzinfo=tz.gettz(settings.TIME_ZONE)),
        )

    def test_consume_date_filename_date_use_content(self):
        """
        GIVEN:
            - File content with date in DMY (default) format
            - Filename date parsing disabled
            - Filename with date in YMD format

        THEN:
            - Should parse the date from the content
        """
        src = (
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000005.pdf"
        )
        dst = self.dirs.scratch_dir / "Scan - 2022-02-01.pdf"
        shutil.copy(src, dst)

        with self.get_consumer(dst) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertEqual(
            document.created,
            datetime.datetime(1996, 2, 20, tzinfo=tz.gettz(settings.TIME_ZONE)),
        )

    @override_settings(
        IGNORE_DATES=(datetime.date(2010, 12, 13), datetime.date(2011, 11, 12)),
    )
    def test_consume_date_use_content_with_ignore(self):
        """
        GIVEN:
            - File content with dates in DMY (default) format
            - File content includes ignored dates

        THEN:
            - Should parse the date from the filename
        """
        src = (
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000006.pdf"
        )
        dst = self.dirs.scratch_dir / "0000006.pdf"
        shutil.copy(src, dst)

        with self.get_consumer(dst) as consumer:
            consumer.run()

            document = Document.objects.first()

        self.assertEqual(
            document.created,
            datetime.datetime(1997, 2, 20, tzinfo=tz.gettz(settings.TIME_ZONE)),
        )


class PreConsumeTestCase(DirectoriesMixin, GetConsumerMixin, TestCase):
    def setUp(self) -> None:
        super().setUp()
        src = (
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000005.pdf"
        )
        self.test_file = self.dirs.scratch_dir / "sample.pdf"
        shutil.copy(src, self.test_file)

    @mock.patch("documents.consumer.run_subprocess")
    @override_settings(PRE_CONSUME_SCRIPT=None)
    def test_no_pre_consume_script(self, m):
        with self.get_consumer(self.test_file) as c:
            c.run()
            m.assert_not_called()

    @mock.patch("documents.consumer.run_subprocess")
    @override_settings(PRE_CONSUME_SCRIPT="does-not-exist")
    def test_pre_consume_script_not_found(self, m):
        with self.get_consumer(self.test_file) as c:
            self.assertRaises(ConsumerError, c.run)
            m.assert_not_called()

    @mock.patch("documents.consumer.run_subprocess")
    def test_pre_consume_script(self, m):
        with tempfile.NamedTemporaryFile() as script:
            with override_settings(PRE_CONSUME_SCRIPT=script.name):
                with self.get_consumer(self.test_file) as c:
                    c.run()

                    m.assert_called_once()

                    args, _ = m.call_args

                    command = args[0]
                    environment = args[1]

                    self.assertEqual(command[0], script.name)
                    self.assertEqual(command[1], str(self.test_file))

                    subset = {
                        "DOCUMENT_SOURCE_PATH": str(c.input_doc.original_file),
                        "DOCUMENT_WORKING_PATH": str(c.working_copy),
                        "TASK_ID": c.task_id,
                    }
                    self.assertDictEqual(environment, {**environment, **subset})

    def test_script_with_output(self):
        """
        GIVEN:
            - A script which outputs to stdout and stderr
        WHEN:
            - The script is executed as a consume script
        THEN:
            - The script's outputs are logged
        """
        with tempfile.NamedTemporaryFile(mode="w") as script:
            # Write up a little script
            with script.file as outfile:
                outfile.write("#!/usr/bin/env bash\n")
                outfile.write("echo This message goes to stdout\n")
                outfile.write("echo This message goes to stderr >&2")

            # Make the file executable
            st = os.stat(script.name)
            os.chmod(script.name, st.st_mode | stat.S_IEXEC)

            with override_settings(PRE_CONSUME_SCRIPT=script.name):
                with self.assertLogs("paperless.consumer", level="INFO") as cm:
                    with self.get_consumer(self.test_file) as c:
                        c.run()
                    self.assertIn(
                        "INFO:paperless.consumer:This message goes to stdout",
                        cm.output,
                    )
                    self.assertIn(
                        "WARNING:paperless.consumer:This message goes to stderr",
                        cm.output,
                    )

    def test_script_exit_non_zero(self):
        """
        GIVEN:
            - A script which exits with a non-zero exit code
        WHEN:
            - The script is executed as a pre-consume script
        THEN:
            - A ConsumerError is raised
        """
        with tempfile.NamedTemporaryFile(mode="w") as script:
            # Write up a little script
            with script.file as outfile:
                outfile.write("#!/usr/bin/env bash\n")
                outfile.write("exit 100\n")

            # Make the file executable
            st = os.stat(script.name)
            os.chmod(script.name, st.st_mode | stat.S_IEXEC)

            with override_settings(PRE_CONSUME_SCRIPT=script.name):
                with self.get_consumer(self.test_file) as c:
                    self.assertRaises(
                        ConsumerError,
                        c.run,
                    )


class PostConsumeTestCase(DirectoriesMixin, GetConsumerMixin, TestCase):
    def setUp(self) -> None:
        super().setUp()
        src = (
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000005.pdf"
        )
        self.test_file = self.dirs.scratch_dir / "sample.pdf"
        shutil.copy(src, self.test_file)

    @mock.patch("documents.consumer.run_subprocess")
    @override_settings(POST_CONSUME_SCRIPT=None)
    def test_no_post_consume_script(self, m):
        doc = Document.objects.create(title="Test", mime_type="application/pdf")
        tag1 = Tag.objects.create(name="a")
        tag2 = Tag.objects.create(name="b")
        doc.tags.add(tag1)
        doc.tags.add(tag2)

        with self.get_consumer(self.test_file) as consumer:
            consumer.run_post_consume_script(doc)
        m.assert_not_called()

    @override_settings(POST_CONSUME_SCRIPT="does-not-exist")
    def test_post_consume_script_not_found(self):
        doc = Document.objects.create(title="Test", mime_type="application/pdf")

        with self.get_consumer(self.test_file) as consumer:
            with self.assertRaisesMessage(
                ConsumerError,
                "sample.pdf: Configured post-consume script does-not-exist does not exist",
            ):
                consumer.run_post_consume_script(doc)

    @mock.patch("documents.consumer.run_subprocess")
    def test_post_consume_script_simple(self, m):
        with tempfile.NamedTemporaryFile() as script:
            with override_settings(POST_CONSUME_SCRIPT=script.name):
                doc = Document.objects.create(title="Test", mime_type="application/pdf")

                with self.get_consumer(self.test_file) as consumer:
                    consumer.run_post_consume_script(doc)

                m.assert_called_once()

    @mock.patch("documents.consumer.run_subprocess")
    def test_post_consume_script_with_correspondent(self, m):
        with tempfile.NamedTemporaryFile() as script:
            with override_settings(POST_CONSUME_SCRIPT=script.name):
                c = Correspondent.objects.create(name="my_bank")
                doc = Document.objects.create(
                    title="Test",
                    mime_type="application/pdf",
                    correspondent=c,
                )
                tag1 = Tag.objects.create(name="a")
                tag2 = Tag.objects.create(name="b")
                doc.tags.add(tag1)
                doc.tags.add(tag2)

                with self.get_consumer(self.test_file) as consumer:
                    consumer.run_post_consume_script(doc)

                m.assert_called_once()

                args, _ = m.call_args

                command = args[0]
                environment = args[1]

                self.assertEqual(command[0], script.name)
                self.assertEqual(command[1], str(doc.pk))
                self.assertEqual(command[5], f"/api/documents/{doc.pk}/download/")
                self.assertEqual(command[6], f"/api/documents/{doc.pk}/thumb/")
                self.assertEqual(command[7], "my_bank")
                self.assertCountEqual(command[8].split(","), ["a", "b"])

                subset = {
                    "DOCUMENT_ID": str(doc.pk),
                    "DOCUMENT_DOWNLOAD_URL": f"/api/documents/{doc.pk}/download/",
                    "DOCUMENT_THUMBNAIL_URL": f"/api/documents/{doc.pk}/thumb/",
                    "DOCUMENT_CORRESPONDENT": "my_bank",
                    "DOCUMENT_TAGS": "a,b",
                    "TASK_ID": consumer.task_id,
                }

                self.assertDictEqual(environment, {**environment, **subset})

    def test_script_exit_non_zero(self):
        """
        GIVEN:
            - A script which exits with a non-zero exit code
        WHEN:
            - The script is executed as a post-consume script
        THEN:
            - A ConsumerError is raised
        """
        with tempfile.NamedTemporaryFile(mode="w") as script:
            # Write up a little script
            with script.file as outfile:
                outfile.write("#!/usr/bin/env bash\n")
                outfile.write("exit -500\n")

            # Make the file executable
            st = os.stat(script.name)
            os.chmod(script.name, st.st_mode | stat.S_IEXEC)

            with override_settings(POST_CONSUME_SCRIPT=script.name):
                doc = Document.objects.create(title="Test", mime_type="application/pdf")
                with self.get_consumer(self.test_file) as consumer:
                    with self.assertRaisesRegex(
                        ConsumerError,
                        r"sample\.pdf: Error while executing post-consume script: Command '\[.*\]' returned non-zero exit status \d+\.",
                    ):
                        consumer.run_post_consume_script(doc)
