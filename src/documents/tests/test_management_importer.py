import json
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from rich.progress import Progress

from documents.management.commands.document_importer import Command
from documents.models import Document
from documents.settings import EXPORTER_ARCHIVE_NAME
from documents.settings import EXPORTER_FILE_NAME
from documents.tests.utils import DirectoriesMixin
from documents.tests.utils import FileSystemAssertsMixin
from documents.tests.utils import SampleDirMixin


class TestCommandImport(
    DirectoriesMixin,
    FileSystemAssertsMixin,
    SampleDirMixin,
    TestCase,
):
    def test_check_manifest_exists(self):
        """
        GIVEN:
            - Source directory exists
            - No manifest.json file exists in the directory
        WHEN:
            - Import is attempted
        THEN:
            - CommandError is raised indicating the issue
        """
        with self.assertRaises(CommandError) as e:
            call_command(
                "document_importer",
                "--no-progress-bar",
                str(self.dirs.scratch_dir),
            )
            self.assertIn(
                "That directory doesn't appear to contain a manifest.json file.",
                str(e),
            )

    def test_check_manifest_malformed(self):
        """
        GIVEN:
            - Source directory exists
            - manifest.json file exists in the directory
            - manifest.json is missing the documents exported name
        WHEN:
            - Import is attempted
        THEN:
            - CommandError is raised indicating the issue
        """
        manifest_file = self.dirs.scratch_dir / "manifest.json"
        with manifest_file.open("w") as outfile:
            json.dump([{"model": "documents.document"}], outfile)

        with self.assertRaises(CommandError) as e:
            call_command(
                "document_importer",
                "--no-progress-bar",
                str(self.dirs.scratch_dir),
            )
            self.assertIn(
                "The manifest file contains a record which does not refer to an actual document file.",
                str(e),
            )

    def test_check_manifest_file_not_found(self):
        """
        GIVEN:
            - Source directory exists
            - manifest.json file exists in the directory
            - manifest.json refers to a file which doesn't exist
        WHEN:
            - Import is attempted
        THEN:
            - CommandError is raised indicating the issue
        """
        manifest_file = self.dirs.scratch_dir / "manifest.json"
        with manifest_file.open("w") as outfile:
            json.dump(
                [{"model": "documents.document", EXPORTER_FILE_NAME: "noexist.pdf"}],
                outfile,
            )

        with self.assertRaises(CommandError) as e:
            call_command(
                "document_importer",
                "--no-progress-bar",
                str(self.dirs.scratch_dir),
            )
            self.assertIn('The manifest file refers to "noexist.pdf"', str(e))

    def test_import_permission_error(self):
        """
        GIVEN:
            - Original file which cannot be read from
            - Archive file which cannot be read from
        WHEN:
            - Import is attempted
        THEN:
            - CommandError is raised indicating the issue
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create empty files
            original_path = Path(temp_dir) / "original.pdf"
            archive_path = Path(temp_dir) / "archive.pdf"
            original_path.touch()
            archive_path.touch()

            # No read permissions
            original_path.chmod(0o222)

            cmd = Command()
            cmd.source = Path(temp_dir)
            cmd.manifest = [
                {
                    "model": "documents.document",
                    EXPORTER_FILE_NAME: "original.pdf",
                    EXPORTER_ARCHIVE_NAME: "archive.pdf",
                },
            ]
            cmd.data_only = False
            with (
                self.assertRaises(CommandError) as cm,
                Progress(disable=True) as progress,
            ):
                cmd.check_manifest_validity(progress)
                self.assertInt("Failed to read from original file", str(cm.exception))

            original_path.chmod(0o444)
            archive_path.chmod(0o222)

            with (
                self.assertRaises(CommandError) as cm,
                Progress(disable=True) as progress,
            ):
                cmd.check_manifest_validity(progress)
                self.assertInt("Failed to read from archive file", str(cm.exception))

    def test_import_source_not_existing(self):
        """
        GIVEN:
            - Source given doesn't exist
        WHEN:
            - Import is attempted
        THEN:
            - CommandError is raised indicating the issue
        """
        with self.assertRaises(CommandError) as cm:
            call_command("document_importer", Path("/tmp/notapath"))
            self.assertInt("That path doesn't exist", str(cm.exception))

    def test_import_source_not_readable(self):
        """
        GIVEN:
            - Source given isn't readable
        WHEN:
            - Import is attempted
        THEN:
            - CommandError is raised indicating the issue
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir)
            path.chmod(0o222)
            with self.assertRaises(CommandError) as cm:
                call_command("document_importer", path)
                self.assertInt(
                    "That path doesn't appear to be readable",
                    str(cm.exception),
                )

    def test_import_source_does_not_exist(self):
        """
        GIVEN:
            - Source directory does not exist
        WHEN:
            - Request to import documents from a directory
        THEN:
            - CommandError is raised indicating the folder doesn't exist
        """
        path = Path("/tmp/should-not-exist")

        self.assertIsNotFile(path)

        with self.assertRaises(CommandError) as e:
            call_command("document_importer", "--no-progress-bar", str(path))

            self.assertIn("That path doesn't exist", str(e))

    def test_import_files_exist(self):
        """
        GIVEN:
            - Source directory does exist
            - A file exists in the originals directory
        WHEN:
            - Request to import documents from a directory
        THEN:
            - CommandError is raised indicating the file exists
        """
        (self.dirs.originals_dir / "temp").mkdir()

        (self.dirs.originals_dir / "temp" / "file.pdf").touch()

        stdout = StringIO()

        with self.assertRaises(CommandError):
            call_command(
                "document_importer",
                "--no-progress-bar",
                str(self.dirs.scratch_dir),
                stdout=stdout,
            )
        stdout.seek(0)
        self.assertIn(
            "Found file temp/file.pdf, this might indicate a non-empty installation",
            str(stdout.read()),
        )

    def test_import_with_user_exists(self):
        """
        GIVEN:
            - Source directory does exist
            - At least 1 User exists in the database
        WHEN:
            - Request to import documents from a directory
        THEN:
            - A warning is output to stdout
        """
        stdout = StringIO()

        User.objects.create()

        # Not creating a manifest, etc, so it errors
        with self.assertRaises(CommandError):
            call_command(
                "document_importer",
                "--no-progress-bar",
                str(self.dirs.scratch_dir),
                stdout=stdout,
            )
        stdout.seek(0)
        self.assertIn(
            "Found existing user(s), this might indicate a non-empty installation",
            stdout.read(),
        )

    def test_import_with_documents_exists(self):
        """
        GIVEN:
            - Source directory does exist
            - At least 1 Document exists in the database
        WHEN:
            - Request to import documents from a directory
        THEN:
            - A warning is output to stdout
        """
        stdout = StringIO()

        Document.objects.create(
            content="Content",
            checksum="42995833e01aea9b3edee44bbfdd7ce1",
            archive_checksum="62acb0bcbfbcaa62ca6ad3668e4e404b",
            title="wow1",
            filename="0000001.pdf",
            mime_type="application/pdf",
            archive_filename="0000001.pdf",
        )

        # Not creating a manifest, etc, so it errors
        with self.assertRaises(CommandError):
            call_command(
                "document_importer",
                "--no-progress-bar",
                str(self.dirs.scratch_dir),
                stdout=stdout,
            )
        stdout.seek(0)
        self.assertIn(
            "Found existing documents(s), this might indicate a non-empty installation",
            str(stdout.read()),
        )

    def test_import_no_metadata_or_version_file(self):
        """
        GIVEN:
            - A source directory with a manifest file only
        WHEN:
            - An import is attempted
        THEN:
            - Warning about the missing files is output
        """
        stdout = StringIO()

        (self.dirs.scratch_dir / "manifest.json").touch()

        # We're not building a manifest, so it fails, but this test doesn't care
        with self.assertRaises(json.decoder.JSONDecodeError):
            call_command(
                "document_importer",
                "--no-progress-bar",
                str(self.dirs.scratch_dir),
                stdout=stdout,
            )
        stdout.seek(0)
        stdout_str = str(stdout.read())

        self.assertIn("No version.json or metadata.json file located", stdout_str)

    def test_import_version_file(self):
        """
        GIVEN:
            - A source directory with a manifest file and version file
        WHEN:
            - An import is attempted
        THEN:
            - Warning about the the version mismatch is output
        """
        stdout = StringIO()

        (self.dirs.scratch_dir / "manifest.json").touch()
        (self.dirs.scratch_dir / "version.json").write_text(
            json.dumps({"version": "2.8.1"}),
        )

        # We're not building a manifest, so it fails, but this test doesn't care
        with self.assertRaises(json.decoder.JSONDecodeError):
            call_command(
                "document_importer",
                "--no-progress-bar",
                str(self.dirs.scratch_dir),
                stdout=stdout,
            )
        stdout.seek(0)
        stdout_str = str(stdout.read())

        self.assertIn("Version mismatch:", stdout_str)
        self.assertIn("importing 2.8.1", stdout_str)
