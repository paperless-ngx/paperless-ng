import json
import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.serializers.base import DeserializationError
from django.db import IntegrityError
from django.db import transaction
from django.db.models.signals import m2m_changed
from django.db.models.signals import post_save
from filelock import FileLock
from rich.progress import Progress

from documents.file_handling import create_source_path_directory
from documents.management.commands.mixins import CryptMixin
from documents.models import Correspondent
from documents.models import CustomField
from documents.models import CustomFieldInstance
from documents.models import Document
from documents.models import DocumentType
from documents.models import Note
from documents.models import Tag
from documents.parsers import run_convert
from documents.settings import EXPORTER_ARCHIVE_NAME
from documents.settings import EXPORTER_CRYPTO_SETTINGS_NAME
from documents.settings import EXPORTER_FILE_NAME
from documents.settings import EXPORTER_THUMBNAIL_NAME
from documents.signals.handlers import check_paths_and_prune_custom_fields
from documents.signals.handlers import update_filename_and_move_files
from documents.utils import copy_file_with_basic_stats
from paperless import version

if settings.AUDIT_LOG_ENABLED:
    from auditlog.registry import auditlog


@contextmanager
def disable_signal(sig, receiver, sender) -> Generator:
    try:
        sig.disconnect(receiver=receiver, sender=sender)
        yield
    finally:
        sig.connect(receiver=receiver, sender=sender)


class Command(CryptMixin, BaseCommand):
    help = (
        "Using a manifest.json file, load the data from there, and import the "
        "documents it refers to."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("source")

        parser.add_argument(
            "--no-progress-bar",
            default=False,
            action="store_true",
            help="If set, the progress bar will not be shown",
        )

        parser.add_argument(
            "--data-only",
            default=False,
            action="store_true",
            help="If set, only the database will be exported, not files",
        )

        parser.add_argument(
            "--passphrase",
            help="If provided, is used to sensitive fields in the export",
        )

    def pre_check(self) -> None:
        """
        Runs some initial checks against the state of the install and source, including:
        - Does the target exist?
        - Can we access the target?
        - Does the target have a manifest file?
        - Are there existing files in the document folders?
        - Are there existing users or documents in the database?
        """

        def pre_check_maybe_not_empty() -> None:
            # Skip this check if operating only on the database
            # We can expect data to exist in that case
            if not self.data_only:
                for document_dir in [settings.ORIGINALS_DIR, settings.ARCHIVE_DIR]:
                    if document_dir.exists() and document_dir.is_dir():
                        for entry in document_dir.glob("**/*"):
                            if entry.is_dir():
                                continue
                            self.stdout.write(
                                self.style.WARNING(
                                    f"Found file {entry.relative_to(document_dir)}, this might indicate a non-empty installation",
                                ),
                            )
                            break
            # But existing users or other data still matters in a data only
            if (
                User.objects.exclude(username__in=["consumer", "AnonymousUser"]).count()
                != 0
            ):
                self.stdout.write(
                    self.style.WARNING(
                        "Found existing user(s), this might indicate a non-empty installation",
                    ),
                )
            if Document.objects.count() != 0:
                self.stdout.write(
                    self.style.WARNING(
                        "Found existing documents(s), this might indicate a non-empty installation",
                    ),
                )

        def pre_check_manifest_exists() -> None:
            if not (self.source / "manifest.json").exists():
                raise CommandError(
                    "That directory doesn't appear to contain a manifest.json file.",
                )

        if not self.source.exists():
            raise CommandError("That path doesn't exist")

        if not os.access(self.source, os.R_OK):
            raise CommandError("That path doesn't appear to be readable")

        pre_check_maybe_not_empty()
        pre_check_manifest_exists()

    def load_manifest_files(self, progress: Progress) -> None:
        """
        Loads manifest data from the various JSON files for parsing and loading the database
        """
        main_manifest_path: Path = self.source / "manifest.json"

        with main_manifest_path.open() as infile:
            self.manifest = json.load(infile)
        self.manifest_paths.append(main_manifest_path)

        split_manifest_task = progress.add_task("Parsing split manifests")

        for file in Path(self.source).glob("**/*-manifest.json"):
            progress.update(split_manifest_task, visible=True)
            with file.open() as infile:
                self.manifest += json.load(infile)
            self.manifest_paths.append(file)
            progress.advance(split_manifest_task)
        progress.update(split_manifest_task, total=1, completed=1)

    def load_metadata(self) -> None:
        """
        Loads either just the version information or the version information and extra data

        Must account for the old style of export as well, with just version.json
        """
        version_path: Path = self.source / "version.json"
        metadata_path: Path = self.source / "metadata.json"
        if not version_path.exists() and not metadata_path.exists():
            self.stdout.write(
                self.style.NOTICE("No version.json or metadata.json file located"),
            )
            return

        if metadata_path.exists():
            with metadata_path.open() as infile:
                data = json.load(infile)
                self.version = data["version"]
                if not self.passphrase and EXPORTER_CRYPTO_SETTINGS_NAME in data:
                    raise CommandError(
                        "No passphrase was given, but this export contains encrypted fields",
                    )
                elif EXPORTER_CRYPTO_SETTINGS_NAME in data:
                    self.load_crypt_params(data)
        elif version_path.exists():
            with version_path.open() as infile:
                self.version = json.load(infile)["version"]

        if self.version and self.version != version.__full_version_str__:
            self.stdout.write(
                self.style.WARNING(
                    "Version mismatch: "
                    f"Currently {version.__full_version_str__},"
                    f" importing {self.version}."
                    " Continuing, but import may fail.",
                ),
            )

    def load_data_to_database(self, progress: Progress) -> None:
        """
        As the name implies, loads data from the JSON file(s) into the database
        """
        try:
            with transaction.atomic():
                # delete these since pk can change, re-created from import
                ContentType.objects.all().delete()
                Permission.objects.all().delete()
                for manifest_path in self.manifest_paths:
                    call_command("loaddata", "-v", "0", manifest_path)
        except (FieldDoesNotExist, DeserializationError, IntegrityError) as e:
            self.stdout.write(self.style.ERROR("Database import failed"))
            if (
                self.version is not None
                and self.version != version.__full_version_str__
            ):  # pragma: no cover
                self.stdout.write(
                    self.style.ERROR(
                        "Version mismatch: "
                        f"Currently {version.__full_version_str__},"
                        f" importing {self.version}",
                    ),
                )
                raise e
            else:
                self.stdout.write(
                    self.style.ERROR("No version information present"),
                )
                raise e

    def handle(self, *args, **options) -> None:
        logging.getLogger().handlers[0].level = logging.ERROR

        self.source = Path(options["source"]).resolve()
        self.data_only: bool = options["data_only"]
        self.no_progress_bar: bool = options["no_progress_bar"]
        self.passphrase: str | None = options.get("passphrase")
        self.version: str | None = None
        self.salt: str | None = None
        self.manifest_paths = []
        self.manifest = []

        with Progress(disable=self.no_progress_bar) as progress:
            self.pre_check()

            self.load_metadata()

            self.load_manifest_files(progress)

            self.check_manifest_validity(progress)

            self.decrypt_secret_fields()

            # see /src/documents/signals/handlers.py
            with (
                disable_signal(
                    post_save,
                    receiver=update_filename_and_move_files,
                    sender=Document,
                ),
                disable_signal(
                    m2m_changed,
                    receiver=update_filename_and_move_files,
                    sender=Document.tags.through,
                ),
                disable_signal(
                    post_save,
                    receiver=update_filename_and_move_files,
                    sender=CustomFieldInstance,
                ),
                disable_signal(
                    post_save,
                    receiver=check_paths_and_prune_custom_fields,
                    sender=CustomField,
                ),
            ):
                if settings.AUDIT_LOG_ENABLED:
                    auditlog.unregister(Document)
                    auditlog.unregister(Correspondent)
                    auditlog.unregister(Tag)
                    auditlog.unregister(DocumentType)
                    auditlog.unregister(Note)
                    auditlog.unregister(CustomField)
                    auditlog.unregister(CustomFieldInstance)

                # Fill up the database with whatever is in the manifest
                self.load_data_to_database(progress)

                if not self.data_only:
                    self._import_files_from_manifest(progress)
                else:
                    self.stdout.write(self.style.NOTICE("Data only import completed"))

        self.stdout.write("Updating search index...")
        call_command(
            "document_index",
            "reindex",
            no_progress_bar=self.no_progress_bar,
        )

    def check_manifest_validity(self, progress: Progress) -> None:
        """
        Attempts to verify the manifest is valid.  Namely checking the files
        referred to exist and the files can be read from
        """

        def check_document_validity(document_record: dict) -> None:
            if EXPORTER_FILE_NAME not in document_record:
                raise CommandError(
                    "The manifest file contains a record which does not "
                    "refer to an actual document file.",
                )

            doc_file = document_record[EXPORTER_FILE_NAME]
            doc_path: Path = self.source / doc_file
            if not doc_path.exists():
                raise CommandError(
                    f'The manifest file refers to "{doc_file}" which does not '
                    "appear to be in the source directory.",
                )
            try:
                with doc_path.open(mode="rb"):
                    pass
            except Exception as e:
                raise CommandError(
                    f"Failed to read from original file {doc_path}",
                ) from e

            if EXPORTER_ARCHIVE_NAME in document_record:
                archive_file = document_record[EXPORTER_ARCHIVE_NAME]
                doc_archive_path: Path = self.source / archive_file
                if not doc_archive_path.exists():
                    raise CommandError(
                        f"The manifest file refers to {archive_file} which "
                        f"does not appear to be in the source directory.",
                    )
                try:
                    with doc_archive_path.open(mode="rb"):
                        pass
                except Exception as e:
                    raise CommandError(
                        f"Failed to read from archive file {doc_archive_path}",
                    ) from e

        manifest_valid_task = progress.add_task(
            "Checking validity",
            total=None,
            visible=not self.data_only,
        )

        # self.stdout.write("Checking the manifest")
        for record in self.manifest:
            # Only check if the document files exist if this is not data only
            # We don't care about documents for a data only import
            if not self.data_only and record["model"] == "documents.document":
                check_document_validity(record)
                progress.advance(manifest_valid_task)
        progress.update(manifest_valid_task, total=1, completed=1)

    def _import_files_from_manifest(self, progress: Progress) -> None:
        settings.ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)
        settings.THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
        settings.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

        # self.stdout.write("Copy files into paperless...")

        manifest_documents = list(
            filter(lambda r: r["model"] == "documents.document", self.manifest),
        )
        copy_file_task = progress.add_task(
            "Copying files",
            total=len(manifest_documents),
        )
        with FileLock(settings.MEDIA_LOCK):
            for record in manifest_documents:
                document = Document.objects.get(pk=record["pk"])

                doc_file = record[EXPORTER_FILE_NAME]
                document_path = self.source / doc_file

                if EXPORTER_THUMBNAIL_NAME in record:
                    thumb_file = record[EXPORTER_THUMBNAIL_NAME]
                    thumbnail_path = (self.source / thumb_file).resolve()
                else:
                    thumbnail_path = None

                if EXPORTER_ARCHIVE_NAME in record:
                    archive_file = record[EXPORTER_ARCHIVE_NAME]
                    archive_path = self.source / archive_file
                else:
                    archive_path = None

                document.storage_type = Document.STORAGE_TYPE_UNENCRYPTED

                if Path(document.source_path).is_file():
                    raise FileExistsError(document.source_path)

                create_source_path_directory(document.source_path)

                copy_file_with_basic_stats(document_path, document.source_path)

                if thumbnail_path:
                    if thumbnail_path.suffix in {".png", ".PNG"}:
                        run_convert(
                            density=300,
                            scale="500x5000>",
                            alpha="remove",
                            strip=True,
                            trim=False,
                            auto_orient=True,
                            input_file=f"{thumbnail_path}[0]",
                            output_file=str(document.thumbnail_path),
                        )
                    else:
                        copy_file_with_basic_stats(
                            thumbnail_path,
                            document.thumbnail_path,
                        )

                if archive_path:
                    create_source_path_directory(document.archive_path)
                    # TODO: this assumes that the export is valid and
                    #  archive_filename is present on all documents with
                    #  archived files
                    copy_file_with_basic_stats(archive_path, document.archive_path)

                document.save()
                progress.advance(copy_file_task)

    def decrypt_secret_fields(self) -> None:
        """
        The converse decryption of some fields out of the export before importing to database
        """
        if self.passphrase:
            # Salt has been loaded from metadata.json at this point, so it cannot be None
            self.setup_crypto(passphrase=self.passphrase, salt=self.salt)

            had_at_least_one_record = False

            for crypt_config in self.CRYPT_FIELDS:
                importer_model: str = crypt_config["model_name"]
                crypt_fields: str = crypt_config["fields"]
                for record in filter(
                    lambda x: x["model"] == importer_model,
                    self.manifest,
                ):
                    had_at_least_one_record = True
                    for field in crypt_fields:
                        if record["fields"][field]:
                            record["fields"][field] = self.decrypt_string(
                                value=record["fields"][field],
                            )

            if had_at_least_one_record:
                # It's annoying, but the DB is loaded from the JSON directly
                # Maybe could change that in the future?
                (self.source / "manifest.json").write_text(
                    json.dumps(self.manifest, indent=2, ensure_ascii=False),
                )
