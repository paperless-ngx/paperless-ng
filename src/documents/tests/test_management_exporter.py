import hashlib
import json
import os
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock
from zipfile import ZipFile

from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.models import SocialToken
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from guardian.models import GroupObjectPermission
from guardian.models import UserObjectPermission
from guardian.shortcuts import assign_perm

from documents.management.commands import document_exporter
from documents.models import Correspondent
from documents.models import CustomField
from documents.models import CustomFieldInstance
from documents.models import Document
from documents.models import DocumentType
from documents.models import Note
from documents.models import StoragePath
from documents.models import Tag
from documents.models import User
from documents.models import Workflow
from documents.models import WorkflowAction
from documents.models import WorkflowTrigger
from documents.sanity_checker import check_sanity
from documents.settings import EXPORTER_FILE_NAME
from documents.tests.utils import DirectoriesMixin
from documents.tests.utils import FileSystemAssertsMixin
from documents.tests.utils import SampleDirMixin
from documents.tests.utils import paperless_environment
from paperless_mail.models import MailAccount


class TestExportImport(
    DirectoriesMixin,
    FileSystemAssertsMixin,
    SampleDirMixin,
    TestCase,
):
    def setUp(self) -> None:
        self.target = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.target)

        self.user = User.objects.create(username="temp_admin")
        self.user2 = User.objects.create(username="user2")
        self.group1 = Group.objects.create(name="group1")

        self.d1 = Document.objects.create(
            content="Content",
            checksum="42995833e01aea9b3edee44bbfdd7ce1",
            archive_checksum="62acb0bcbfbcaa62ca6ad3668e4e404b",
            title="wow1",
            filename="0000001.pdf",
            mime_type="application/pdf",
            archive_filename="0000001.pdf",
        )
        self.d2 = Document.objects.create(
            content="Content",
            checksum="9c9691e51741c1f4f41a20896af31770",
            title="wow2",
            filename="0000002.pdf",
            mime_type="application/pdf",
        )
        self.d3 = Document.objects.create(
            content="Content",
            checksum="d38d7ed02e988e072caf924e0f3fcb76",
            title="wow2",
            filename="0000003.pdf",
            mime_type="application/pdf",
        )
        self.d4 = Document.objects.create(
            content="Content",
            checksum="82186aaa94f0b98697d704b90fd1c072",
            title="wow_dec",
            filename="0000004.pdf.gpg",
            mime_type="application/pdf",
            storage_type=Document.STORAGE_TYPE_GPG,
        )

        self.note = Note.objects.create(
            note="This is a note. amaze.",
            document=self.d1,
            user=self.user,
        )

        assign_perm("view_document", self.user2, self.d2)
        assign_perm("view_document", self.group1, self.d3)

        self.t1 = Tag.objects.create(name="t")
        self.dt1 = DocumentType.objects.create(name="dt")
        self.c1 = Correspondent.objects.create(name="c")
        self.sp1 = StoragePath.objects.create(path="{created_year}-{title}")
        self.cf1 = CustomField.objects.create(
            name="Custom Field 1",
            data_type=CustomField.FieldDataType.STRING,
        )
        self.cfi1 = CustomFieldInstance.objects.create(
            field=self.cf1,
            value_text="cf instance 1",
            document=self.d1,
        )

        self.d1.tags.add(self.t1)
        self.d1.correspondent = self.c1
        self.d1.document_type = self.dt1
        self.d1.save()
        self.d4.storage_path = self.sp1
        self.d4.save()

        self.trigger = WorkflowTrigger.objects.create(
            type=WorkflowTrigger.WorkflowTriggerType.CONSUMPTION,
            sources=[1],
            filter_filename="*",
        )
        self.action = WorkflowAction.objects.create(assign_title="new title")
        self.workflow = Workflow.objects.create(name="Workflow 1", order="0")
        self.workflow.triggers.add(self.trigger)
        self.workflow.actions.add(self.action)
        self.workflow.save()

        super().setUp()

    def _get_document_from_manifest(self, manifest, id):
        f = list(
            filter(
                lambda d: d["model"] == "documents.document" and d["pk"] == id,
                manifest,
            ),
        )
        if len(f) == 1:
            return f[0]
        else:
            raise ValueError(f"document with id {id} does not exist in manifest")

    @override_settings(PASSPHRASE="test")
    def _do_export(
        self,
        *,
        use_filename_format=False,
        compare_checksums=False,
        compare_json=False,
        delete=False,
        no_archive=False,
        no_thumbnail=False,
        split_manifest=False,
        use_folder_prefix=False,
        data_only=False,
    ):
        args = ["document_exporter", self.target]
        if use_filename_format:
            args += ["--use-filename-format"]
        if compare_checksums:
            args += ["--compare-checksums"]
        if compare_json:
            args += ["--compare-json"]
        if delete:
            args += ["--delete"]
        if no_archive:
            args += ["--no-archive"]
        if no_thumbnail:
            args += ["--no-thumbnail"]
        if split_manifest:
            args += ["--split-manifest"]
        if use_folder_prefix:
            args += ["--use-folder-prefix"]
        if data_only:
            args += ["--data-only"]

        call_command(*args)

        with open(os.path.join(self.target, "manifest.json")) as f:
            manifest = json.load(f)

        return manifest

    def test_exporter(self, *, use_filename_format=False):
        shutil.rmtree(os.path.join(self.dirs.media_dir, "documents"))
        shutil.copytree(
            os.path.join(os.path.dirname(__file__), "samples", "documents"),
            os.path.join(self.dirs.media_dir, "documents"),
        )

        num_permission_objects = Permission.objects.count()

        manifest = self._do_export(use_filename_format=use_filename_format)

        # dont include consumer or AnonymousUser users
        self.assertEqual(
            len(list(filter(lambda e: e["model"] == "auth.user", manifest))),
            2,
        )

        self.assertEqual(
            len(list(filter(lambda e: e["model"] == "documents.document", manifest))),
            4,
        )

        self.assertIsFile(os.path.join(self.target, "manifest.json"))

        self.assertEqual(
            self._get_document_from_manifest(manifest, self.d1.id)["fields"]["title"],
            "wow1",
        )
        self.assertEqual(
            self._get_document_from_manifest(manifest, self.d2.id)["fields"]["title"],
            "wow2",
        )
        self.assertEqual(
            self._get_document_from_manifest(manifest, self.d3.id)["fields"]["title"],
            "wow2",
        )
        self.assertEqual(
            self._get_document_from_manifest(manifest, self.d4.id)["fields"]["title"],
            "wow_dec",
        )

        for element in manifest:
            if element["model"] == "documents.document":
                fname = os.path.join(
                    self.target,
                    element[document_exporter.EXPORTER_FILE_NAME],
                )
                self.assertIsFile(fname)
                self.assertIsFile(
                    os.path.join(
                        self.target,
                        element[document_exporter.EXPORTER_THUMBNAIL_NAME],
                    ),
                )

                with open(fname, "rb") as f:
                    checksum = hashlib.md5(f.read()).hexdigest()
                self.assertEqual(checksum, element["fields"]["checksum"])

                self.assertEqual(
                    element["fields"]["storage_type"],
                    Document.STORAGE_TYPE_UNENCRYPTED,
                )

                if document_exporter.EXPORTER_ARCHIVE_NAME in element:
                    fname = os.path.join(
                        self.target,
                        element[document_exporter.EXPORTER_ARCHIVE_NAME],
                    )
                    self.assertIsFile(fname)

                    with open(fname, "rb") as f:
                        checksum = hashlib.md5(f.read()).hexdigest()
                    self.assertEqual(checksum, element["fields"]["archive_checksum"])

            elif element["model"] == "documents.note":
                self.assertEqual(element["fields"]["note"], self.note.note)
                self.assertEqual(element["fields"]["document"], self.d1.id)
                self.assertEqual(element["fields"]["user"], self.user.id)

        with paperless_environment():
            self.assertEqual(Document.objects.count(), 4)
            Document.objects.all().delete()
            Correspondent.objects.all().delete()
            DocumentType.objects.all().delete()
            Tag.objects.all().delete()
            Permission.objects.all().delete()
            UserObjectPermission.objects.all().delete()
            GroupObjectPermission.objects.all().delete()
            self.assertEqual(Document.objects.count(), 0)

            call_command("document_importer", "--no-progress-bar", self.target)
            self.assertEqual(Document.objects.count(), 4)
            self.assertEqual(Tag.objects.count(), 1)
            self.assertEqual(Correspondent.objects.count(), 1)
            self.assertEqual(DocumentType.objects.count(), 1)
            self.assertEqual(StoragePath.objects.count(), 1)
            self.assertEqual(Document.objects.get(id=self.d1.id).title, "wow1")
            self.assertEqual(Document.objects.get(id=self.d2.id).title, "wow2")
            self.assertEqual(Document.objects.get(id=self.d3.id).title, "wow2")
            self.assertEqual(Document.objects.get(id=self.d4.id).title, "wow_dec")
            self.assertEqual(GroupObjectPermission.objects.count(), 1)
            self.assertEqual(UserObjectPermission.objects.count(), 1)
            self.assertEqual(Permission.objects.count(), num_permission_objects)
            messages = check_sanity()
            # everything is alright after the test
            self.assertEqual(len(messages), 0)

    def test_exporter_with_filename_format(self):
        shutil.rmtree(os.path.join(self.dirs.media_dir, "documents"))
        shutil.copytree(
            os.path.join(os.path.dirname(__file__), "samples", "documents"),
            os.path.join(self.dirs.media_dir, "documents"),
        )

        with override_settings(
            FILENAME_FORMAT="{created_year}/{correspondent}/{title}",
        ):
            self.test_exporter(use_filename_format=True)

    def test_update_export_changed_time(self):
        shutil.rmtree(os.path.join(self.dirs.media_dir, "documents"))
        shutil.copytree(
            os.path.join(os.path.dirname(__file__), "samples", "documents"),
            os.path.join(self.dirs.media_dir, "documents"),
        )

        self._do_export()
        self.assertIsFile(os.path.join(self.target, "manifest.json"))

        st_mtime_1 = os.stat(os.path.join(self.target, "manifest.json")).st_mtime

        with mock.patch(
            "documents.management.commands.document_exporter.copy_file_with_basic_stats",
        ) as m:
            self._do_export()
            m.assert_not_called()

        self.assertIsFile(os.path.join(self.target, "manifest.json"))
        st_mtime_2 = os.stat(os.path.join(self.target, "manifest.json")).st_mtime

        Path(self.d1.source_path).touch()

        with mock.patch(
            "documents.management.commands.document_exporter.copy_file_with_basic_stats",
        ) as m:
            self._do_export()
            self.assertEqual(m.call_count, 1)

        st_mtime_3 = os.stat(os.path.join(self.target, "manifest.json")).st_mtime
        self.assertIsFile(os.path.join(self.target, "manifest.json"))

        self.assertNotEqual(st_mtime_1, st_mtime_2)
        self.assertNotEqual(st_mtime_2, st_mtime_3)

        self._do_export(compare_json=True)
        st_mtime_4 = os.stat(os.path.join(self.target, "manifest.json")).st_mtime
        self.assertEqual(st_mtime_3, st_mtime_4)

    def test_update_export_changed_checksum(self):
        shutil.rmtree(os.path.join(self.dirs.media_dir, "documents"))
        shutil.copytree(
            os.path.join(os.path.dirname(__file__), "samples", "documents"),
            os.path.join(self.dirs.media_dir, "documents"),
        )

        self._do_export()

        self.assertIsFile(os.path.join(self.target, "manifest.json"))

        with mock.patch(
            "documents.management.commands.document_exporter.copy_file_with_basic_stats",
        ) as m:
            self._do_export()
            m.assert_not_called()

        self.assertIsFile(os.path.join(self.target, "manifest.json"))

        self.d2.checksum = "asdfasdgf3"
        self.d2.save()

        with mock.patch(
            "documents.management.commands.document_exporter.copy_file_with_basic_stats",
        ) as m:
            self._do_export(compare_checksums=True)
            self.assertEqual(m.call_count, 1)

        self.assertIsFile(os.path.join(self.target, "manifest.json"))

    def test_update_export_deleted_document(self):
        shutil.rmtree(os.path.join(self.dirs.media_dir, "documents"))
        shutil.copytree(
            os.path.join(os.path.dirname(__file__), "samples", "documents"),
            os.path.join(self.dirs.media_dir, "documents"),
        )

        manifest = self._do_export()

        self.assertTrue(len(manifest), 7)
        doc_from_manifest = self._get_document_from_manifest(manifest, self.d3.id)
        self.assertIsFile(
            os.path.join(self.target, doc_from_manifest[EXPORTER_FILE_NAME]),
        )
        self.d3.delete()

        manifest = self._do_export()
        self.assertRaises(
            ValueError,
            self._get_document_from_manifest,
            manifest,
            self.d3.id,
        )
        self.assertIsFile(
            os.path.join(self.target, doc_from_manifest[EXPORTER_FILE_NAME]),
        )

        manifest = self._do_export(delete=True)
        self.assertIsNotFile(
            os.path.join(self.target, doc_from_manifest[EXPORTER_FILE_NAME]),
        )

        self.assertTrue(len(manifest), 6)

    @override_settings(FILENAME_FORMAT="{title}/{correspondent}")
    def test_update_export_changed_location(self):
        shutil.rmtree(os.path.join(self.dirs.media_dir, "documents"))
        shutil.copytree(
            os.path.join(os.path.dirname(__file__), "samples", "documents"),
            os.path.join(self.dirs.media_dir, "documents"),
        )

        self._do_export(use_filename_format=True)
        self.assertIsFile(os.path.join(self.target, "wow1", "c.pdf"))

        self.assertIsFile(os.path.join(self.target, "manifest.json"))

        self.d1.title = "new_title"
        self.d1.save()
        self._do_export(use_filename_format=True, delete=True)
        self.assertIsNotFile(os.path.join(self.target, "wow1", "c.pdf"))
        self.assertIsNotDir(os.path.join(self.target, "wow1"))
        self.assertIsFile(os.path.join(self.target, "new_title", "c.pdf"))
        self.assertIsFile(os.path.join(self.target, "manifest.json"))
        self.assertIsFile(os.path.join(self.target, "wow2", "none.pdf"))
        self.assertIsFile(
            os.path.join(self.target, "wow2", "none_01.pdf"),
        )

    def test_export_missing_files(self):
        target = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, target)
        Document.objects.create(
            checksum="AAAAAAAAAAAAAAAAA",
            title="wow",
            filename="0000004.pdf",
            mime_type="application/pdf",
        )
        self.assertRaises(FileNotFoundError, call_command, "document_exporter", target)

    @override_settings(PASSPHRASE="test")
    def test_export_zipped(self):
        """
        GIVEN:
            - Request to export documents to zipfile
        WHEN:
            - Documents are exported
        THEN:
            - Zipfile is created
            - Zipfile contains exported files
        """
        shutil.rmtree(os.path.join(self.dirs.media_dir, "documents"))
        shutil.copytree(
            os.path.join(os.path.dirname(__file__), "samples", "documents"),
            os.path.join(self.dirs.media_dir, "documents"),
        )

        args = ["document_exporter", self.target, "--zip"]

        call_command(*args)

        expected_file = os.path.join(
            self.target,
            f"export-{timezone.localdate().isoformat()}.zip",
        )

        self.assertIsFile(expected_file)

        with ZipFile(expected_file) as zip:
            self.assertEqual(len(zip.namelist()), 11)
            self.assertIn("manifest.json", zip.namelist())
            self.assertIn("metadata.json", zip.namelist())

    @override_settings(PASSPHRASE="test")
    def test_export_zipped_format(self):
        """
        GIVEN:
            - Request to export documents to zipfile
            - Export is following filename formatting
        WHEN:
            - Documents are exported
        THEN:
            - Zipfile is created
            - Zipfile contains exported files
        """
        shutil.rmtree(os.path.join(self.dirs.media_dir, "documents"))
        shutil.copytree(
            os.path.join(os.path.dirname(__file__), "samples", "documents"),
            os.path.join(self.dirs.media_dir, "documents"),
        )

        args = ["document_exporter", self.target, "--zip", "--use-filename-format"]

        with override_settings(
            FILENAME_FORMAT="{created_year}/{correspondent}/{title}",
        ):
            call_command(*args)

        expected_file = os.path.join(
            self.target,
            f"export-{timezone.localdate().isoformat()}.zip",
        )

        self.assertIsFile(expected_file)

        with ZipFile(expected_file) as zip:
            # Extras are from the directories, which also appear in the listing
            self.assertEqual(len(zip.namelist()), 14)
            self.assertIn("manifest.json", zip.namelist())
            self.assertIn("metadata.json", zip.namelist())

    @override_settings(PASSPHRASE="test")
    def test_export_zipped_with_delete(self):
        """
        GIVEN:
            - Request to export documents to zipfile
            - There is one existing file in the target
            - There is one existing directory in the target
        WHEN:
            - Documents are exported
            - deletion of existing files is requested
        THEN:
            - Zipfile is created
            - Zipfile contains exported files
            - The existing file and directory in target are removed
        """
        shutil.rmtree(os.path.join(self.dirs.media_dir, "documents"))
        shutil.copytree(
            os.path.join(os.path.dirname(__file__), "samples", "documents"),
            os.path.join(self.dirs.media_dir, "documents"),
        )

        # Create stuff in target directory
        existing_file = self.target / "test.txt"
        existing_file.touch()
        existing_dir = self.target / "somedir"
        existing_dir.mkdir(parents=True)

        self.assertIsFile(existing_file)
        self.assertIsDir(existing_dir)

        args = ["document_exporter", self.target, "--zip", "--delete"]

        call_command(*args)

        expected_file = os.path.join(
            self.target,
            f"export-{timezone.localdate().isoformat()}.zip",
        )

        self.assertIsFile(expected_file)
        self.assertIsNotFile(existing_file)
        self.assertIsNotDir(existing_dir)

        with ZipFile(expected_file) as zip:
            self.assertEqual(len(zip.namelist()), 11)
            self.assertIn("manifest.json", zip.namelist())
            self.assertIn("metadata.json", zip.namelist())

    def test_export_target_not_exists(self):
        """
        GIVEN:
            - Request to export documents to directory that doesn't exist
        WHEN:
            - Export command is called
        THEN:
            - Error is raised
        """
        args = ["document_exporter", "/tmp/foo/bar"]

        with self.assertRaises(CommandError) as e:
            call_command(*args)

            self.assertEqual("That path isn't a directory", str(e))

    def test_export_target_exists_but_is_file(self):
        """
        GIVEN:
            - Request to export documents to file instead of directory
        WHEN:
            - Export command is called
        THEN:
            - Error is raised
        """

        with tempfile.NamedTemporaryFile() as tmp_file:
            args = ["document_exporter", tmp_file.name]

            with self.assertRaises(CommandError) as e:
                call_command(*args)

                self.assertEqual("That path isn't a directory", str(e))

    def test_export_target_not_writable(self):
        """
        GIVEN:
            - Request to export documents to directory that's not writeable
        WHEN:
            - Export command is called
        THEN:
            - Error is raised
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            os.chmod(tmp_dir, 0o000)

            args = ["document_exporter", tmp_dir]

            with self.assertRaises(CommandError) as e:
                call_command(*args)

                self.assertEqual("That path doesn't appear to be writable", str(e))

    def test_no_archive(self):
        """
        GIVEN:
            - Request to export documents to directory
        WHEN:
            - Option no-archive is used
        THEN:
            - Manifest.json doesn't contain information about archive files
            - Documents can be imported again
        """
        shutil.rmtree(os.path.join(self.dirs.media_dir, "documents"))
        shutil.copytree(
            os.path.join(os.path.dirname(__file__), "samples", "documents"),
            os.path.join(self.dirs.media_dir, "documents"),
        )

        manifest = self._do_export()
        has_archive = False
        for element in manifest:
            if element["model"] == "documents.document":
                has_archive = (
                    has_archive or document_exporter.EXPORTER_ARCHIVE_NAME in element
                )
        self.assertTrue(has_archive)

        has_archive = False
        manifest = self._do_export(no_archive=True)
        for element in manifest:
            if element["model"] == "documents.document":
                has_archive = (
                    has_archive or document_exporter.EXPORTER_ARCHIVE_NAME in element
                )
        self.assertFalse(has_archive)

        with paperless_environment():
            self.assertEqual(Document.objects.count(), 4)
            Document.objects.all().delete()
            self.assertEqual(Document.objects.count(), 0)
            call_command("document_importer", "--no-progress-bar", self.target)
            self.assertEqual(Document.objects.count(), 4)

    def test_no_thumbnail(self):
        """
        GIVEN:
            - Request to export documents to directory
        WHEN:
            - Option no-thumbnails is used
        THEN:
            - Manifest.json doesn't contain information about thumbnails
            - Documents can be imported again
        """
        shutil.rmtree(os.path.join(self.dirs.media_dir, "documents"))
        shutil.copytree(
            os.path.join(os.path.dirname(__file__), "samples", "documents"),
            os.path.join(self.dirs.media_dir, "documents"),
        )

        manifest = self._do_export()
        has_thumbnail = False
        for element in manifest:
            if element["model"] == "documents.document":
                has_thumbnail = (
                    has_thumbnail
                    or document_exporter.EXPORTER_THUMBNAIL_NAME in element
                )
        self.assertTrue(has_thumbnail)

        has_thumbnail = False
        manifest = self._do_export(no_thumbnail=True)
        for element in manifest:
            if element["model"] == "documents.document":
                has_thumbnail = (
                    has_thumbnail
                    or document_exporter.EXPORTER_THUMBNAIL_NAME in element
                )
        self.assertFalse(has_thumbnail)

        with paperless_environment():
            self.assertEqual(Document.objects.count(), 4)
            Document.objects.all().delete()
            self.assertEqual(Document.objects.count(), 0)
            call_command("document_importer", "--no-progress-bar", self.target)
            self.assertEqual(Document.objects.count(), 4)

    def test_split_manifest(self):
        """
        GIVEN:
            - Request to export documents to directory
        WHEN:
            - Option split_manifest is used
        THEN:
            - Main manifest.json file doesn't contain information about documents
            - Documents can be imported again
        """
        shutil.rmtree(os.path.join(self.dirs.media_dir, "documents"))
        shutil.copytree(
            os.path.join(os.path.dirname(__file__), "samples", "documents"),
            os.path.join(self.dirs.media_dir, "documents"),
        )

        manifest = self._do_export(split_manifest=True)
        has_document = False
        for element in manifest:
            has_document = has_document or element["model"] == "documents.document"
        self.assertFalse(has_document)

        with paperless_environment():
            self.assertEqual(Document.objects.count(), 4)
            self.assertEqual(CustomFieldInstance.objects.count(), 1)
            Document.objects.all().delete()
            CustomFieldInstance.objects.all().delete()
            self.assertEqual(Document.objects.count(), 0)
            call_command("document_importer", "--no-progress-bar", self.target)
            self.assertEqual(Document.objects.count(), 4)
            self.assertEqual(CustomFieldInstance.objects.count(), 1)

    def test_folder_prefix(self):
        """
        GIVEN:
            - Request to export documents to directory
        WHEN:
            - Option use_folder_prefix is used
        THEN:
            - Documents can be imported again
        """
        shutil.rmtree(os.path.join(self.dirs.media_dir, "documents"))
        shutil.copytree(
            os.path.join(os.path.dirname(__file__), "samples", "documents"),
            os.path.join(self.dirs.media_dir, "documents"),
        )

        self._do_export(use_folder_prefix=True)

        with paperless_environment():
            self.assertEqual(Document.objects.count(), 4)
            Document.objects.all().delete()
            self.assertEqual(Document.objects.count(), 0)
            call_command("document_importer", "--no-progress-bar", self.target)
            self.assertEqual(Document.objects.count(), 4)

    def test_import_db_transaction_failed(self):
        """
        GIVEN:
            - Import from manifest started
        WHEN:
            - Import of database fails
        THEN:
            - ContentType & Permission objects are not deleted, db transaction rolled back
        """

        shutil.rmtree(os.path.join(self.dirs.media_dir, "documents"))
        shutil.copytree(
            os.path.join(os.path.dirname(__file__), "samples", "documents"),
            os.path.join(self.dirs.media_dir, "documents"),
        )

        num_content_type_objects = ContentType.objects.count()
        num_permission_objects = Permission.objects.count()

        manifest = self._do_export()

        with paperless_environment():
            self.assertEqual(
                len(list(filter(lambda e: e["model"] == "auth.permission", manifest))),
                num_permission_objects,
            )
            # add 1 more to db to show objects are not re-created by import
            Permission.objects.create(
                name="test",
                codename="test_perm",
                content_type_id=1,
            )
            self.assertEqual(Permission.objects.count(), num_permission_objects + 1)

            # will cause an import error
            self.user.delete()
            self.user = User.objects.create(username="temp_admin")

            with self.assertRaises(IntegrityError):
                call_command("document_importer", "--no-progress-bar", self.target)

            self.assertEqual(ContentType.objects.count(), num_content_type_objects)
            self.assertEqual(Permission.objects.count(), num_permission_objects + 1)

    def test_exporter_with_auditlog_disabled(self):
        shutil.rmtree(os.path.join(self.dirs.media_dir, "documents"))
        shutil.copytree(
            os.path.join(os.path.dirname(__file__), "samples", "documents"),
            os.path.join(self.dirs.media_dir, "documents"),
        )

        with override_settings(
            AUDIT_LOG_ENABLED=False,
        ):
            manifest = self._do_export(use_filename_format=True)
            for obj in manifest:
                self.assertNotEqual(obj["model"], "auditlog.logentry")

    def test_export_data_only(self):
        """
        GIVEN:
            - Request to export documents with data only
        WHEN:
            - Export command is called
        THEN:
            - No document files are exported
            - Manifest and version are exported
        """

        shutil.rmtree(self.dirs.media_dir / "documents")
        shutil.copytree(
            self.SAMPLE_DIR / "documents",
            self.dirs.media_dir / "documents",
        )

        _ = self._do_export(data_only=True)

        # Manifest and version files only should be present in the exported directory
        self.assertFileCountInDir(self.target, 2)
        self.assertIsFile(self.target / "manifest.json")
        self.assertIsFile(self.target / "metadata.json")

        shutil.rmtree(self.dirs.media_dir / "documents")
        Document.objects.all().delete()

        call_command(
            "document_importer",
            "--no-progress-bar",
            "--data-only",
            self.target,
        )

        self.assertEqual(Document.objects.all().count(), 4)


class TestCryptExportImport(
    DirectoriesMixin,
    FileSystemAssertsMixin,
    TestCase,
):
    def setUp(self) -> None:
        self.target = Path(tempfile.mkdtemp())
        return super().setUp()

    def tearDown(self) -> None:
        shutil.rmtree(self.target, ignore_errors=True)
        return super().tearDown()

    def test_export_passphrase(self):
        """
        GIVEN:
            - A mail account exists
        WHEN:
            - Export command is called
            - Passphrase is provided
        THEN:
            - Output password is not plaintext
        """
        MailAccount.objects.create(
            name="Test Account",
            imap_server="test.imap.com",
            username="myusername",
            password="mypassword",
        )

        app = SocialApp.objects.create(
            provider="test",
            name="test",
            client_id="test",
        )
        account = SocialAccount.objects.create(
            user=User.objects.first(),
            provider="test",
            uid="test",
        )
        SocialToken.objects.create(
            app=app,
            account=account,
            token="test",
            token_secret="test",
        )

        call_command(
            "document_exporter",
            "--no-progress-bar",
            "--passphrase",
            "securepassword",
            self.target,
        )

        self.assertIsFile(self.target / "metadata.json")
        self.assertIsFile(self.target / "manifest.json")

        data = json.loads((self.target / "manifest.json").read_text())

        mail_accounts = list(
            filter(lambda r: r["model"] == "paperless_mail.mailaccount", data),
        )

        self.assertEqual(len(mail_accounts), 1)

        mail_account_data = mail_accounts[0]

        self.assertNotEqual(mail_account_data["fields"]["password"], "mypassword")

        MailAccount.objects.all().delete()

        call_command(
            "document_importer",
            "--no-progress-bar",
            "--passphrase",
            "securepassword",
            self.target,
        )

        account = MailAccount.objects.first()

        self.assertIsNotNone(account)
        self.assertEqual(account.password, "mypassword")

        social_token = SocialToken.objects.first()
        self.assertIsNotNone(social_token)

    def test_import_crypt_no_passphrase(self):
        """
        GIVEN:
            - A mail account exists
        WHEN:
            - Export command is called
            - Passphrase is provided
            - Import command is called
            - No passphrase is given
        THEN:
            - An error is raised for the issue
        """
        call_command(
            "document_exporter",
            "--no-progress-bar",
            "--passphrase",
            "securepassword",
            self.target,
        )

        with self.assertRaises(CommandError) as err:
            call_command(
                "document_importer",
                "--no-progress-bar",
                self.target,
            )
            self.assertEqual(
                err.msg,
                "No passphrase was given, but this export contains encrypted fields",
            )

    def test_export_warn_plaintext(self):
        """
        GIVEN:
            - A mail account exists
        WHEN:
            - Export command is called
            - No passphrase is provided
        THEN:
            - Output password is plaintext
            - Warning is output
        """
        MailAccount.objects.create(
            name="Test Account",
            imap_server="test.imap.com",
            username="myusername",
            password="mypassword",
        )

        stdout = StringIO()

        call_command(
            "document_exporter",
            "--no-progress-bar",
            str(self.target),
            stdout=stdout,
        )
        stdout.seek(0)
        self.assertIn(
            ("No passphrase was given, sensitive fields will be in plaintext"),
            stdout.read(),
        )
