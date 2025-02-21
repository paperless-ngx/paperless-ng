import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from allauth.mfa.models import Authenticator
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.models import SocialToken
from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core import serializers
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone
from filelock import FileLock
from guardian.models import GroupObjectPermission
from guardian.models import UserObjectPermission
from rich.progress import BarColumn
from rich.progress import MofNCompleteColumn
from rich.progress import Progress
from rich.progress import TaskProgressColumn
from rich.progress import TextColumn

if TYPE_CHECKING:
    from django.db.models import QuerySet

if settings.AUDIT_LOG_ENABLED:
    from auditlog.models import LogEntry

from documents.file_handling import delete_empty_directories
from documents.file_handling import generate_filename
from documents.management.commands.mixins import CryptMixin
from documents.models import Correspondent
from documents.models import CustomField
from documents.models import CustomFieldInstance
from documents.models import Document
from documents.models import DocumentType
from documents.models import Note
from documents.models import SavedView
from documents.models import SavedViewFilterRule
from documents.models import StoragePath
from documents.models import Tag
from documents.models import UiSettings
from documents.models import Workflow
from documents.models import WorkflowAction
from documents.models import WorkflowActionEmail
from documents.models import WorkflowActionWebhook
from documents.models import WorkflowTrigger
from documents.settings import EXPORTER_ARCHIVE_NAME
from documents.settings import EXPORTER_FILE_NAME
from documents.settings import EXPORTER_THUMBNAIL_NAME
from documents.utils import copy_file_with_basic_stats
from paperless import version
from paperless.db import GnuPG
from paperless.models import ApplicationConfiguration
from paperless_mail.models import MailAccount
from paperless_mail.models import MailRule


class Command(CryptMixin, BaseCommand):
    help = (
        "Decrypt and rename all files in our collection into a given target "
        "directory.  And include a manifest file containing document data for "
        "easy import."
    )

    def add_arguments(self, parser):
        parser.add_argument("target")

        parser.add_argument(
            "-c",
            "--compare-checksums",
            default=False,
            action="store_true",
            help=(
                "Compare file checksums when determining whether to export "
                "a file or not. If not specified, file size and time "
                "modified is used instead."
            ),
        )

        parser.add_argument(
            "-cj",
            "--compare-json",
            default=False,
            action="store_true",
            help=(
                "Compare json file checksums when determining whether to "
                "export a json file or not (manifest or metadata). "
                "If not specified, the file is always exported."
            ),
        )

        parser.add_argument(
            "-d",
            "--delete",
            default=False,
            action="store_true",
            help=(
                "After exporting, delete files in the export directory that "
                "do not belong to the current export, such as files from "
                "deleted documents."
            ),
        )

        parser.add_argument(
            "-f",
            "--use-filename-format",
            default=False,
            action="store_true",
            help=(
                "Use PAPERLESS_FILENAME_FORMAT for storing files in the "
                "export directory, if configured."
            ),
        )

        parser.add_argument(
            "-na",
            "--no-archive",
            default=False,
            action="store_true",
            help="Avoid exporting archive files",
        )

        parser.add_argument(
            "-nt",
            "--no-thumbnail",
            default=False,
            action="store_true",
            help="Avoid exporting thumbnail files",
        )

        parser.add_argument(
            "-p",
            "--use-folder-prefix",
            default=False,
            action="store_true",
            help=(
                "Export files in dedicated folders according to their nature: "
                "archive, originals or thumbnails"
            ),
        )

        parser.add_argument(
            "-sm",
            "--split-manifest",
            default=False,
            action="store_true",
            help="Export document information in individual manifest json files.",
        )

        parser.add_argument(
            "-z",
            "--zip",
            default=False,
            action="store_true",
            help="Export the documents to a zip file in the given directory",
        )

        parser.add_argument(
            "-zn",
            "--zip-name",
            default=f"export-{timezone.localdate().isoformat()}",
            help="Sets the export zip file name",
        )

        parser.add_argument(
            "--data-only",
            default=False,
            action="store_true",
            help="If set, only the database will be imported, not files",
        )

        parser.add_argument(
            "--no-progress-bar",
            default=False,
            action="store_true",
            help="If set, the progress bar will not be shown",
        )

        parser.add_argument(
            "--passphrase",
            help="If provided, is used to encrypt sensitive data in the export",
        )

    def handle(self, *args, **options):
        self.target = Path(options["target"]).resolve()
        self.split_manifest: bool = options["split_manifest"]
        self.compare_checksums: bool = options["compare_checksums"]
        self.compare_json: bool = options["compare_json"]
        self.use_filename_format: bool = options["use_filename_format"]
        self.use_folder_prefix: bool = options["use_folder_prefix"]
        self.delete: bool = options["delete"]
        self.no_archive: bool = options["no_archive"]
        self.no_thumbnail: bool = options["no_thumbnail"]
        self.zip_export: bool = options["zip"]
        self.data_only: bool = options["data_only"]
        self.no_progress_bar: bool = options["no_progress_bar"]
        self.passphrase: str | None = options.get("passphrase")

        self.files_in_export_dir: set[Path] = set()
        self.exported_files: set[str] = set()

        # If zipping, save the original target for later and
        # get a temporary directory for the target instead
        temp_dir = None
        self.original_target = self.target
        if self.zip_export:
            settings.SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
            temp_dir = tempfile.TemporaryDirectory(
                dir=settings.SCRATCH_DIR,
                prefix="paperless-export",
            )
            self.target = Path(temp_dir.name).resolve()

        if not self.target.exists():
            raise CommandError("That path doesn't exist")

        if not self.target.is_dir():
            raise CommandError("That path isn't a directory")

        if not os.access(self.target, os.W_OK):
            raise CommandError("That path doesn't appear to be writable")

        try:
            # Prevent any ongoing changes in the documents
            with (
                FileLock(settings.MEDIA_LOCK),
                Progress(
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    MofNCompleteColumn(),
                    disable=self.no_progress_bar,
                ) as progress,
            ):
                self.dump(progress)

                # We've written everything to the temporary directory in this case,
                # now make an archive in the original target, with all files stored
                if self.zip_export and temp_dir is not None:
                    shutil.make_archive(
                        os.path.join(
                            self.original_target,
                            options["zip_name"],
                        ),
                        format="zip",
                        root_dir=temp_dir.name,
                    )

        finally:
            # Always cleanup the temporary directory, if one was created
            if self.zip_export and temp_dir is not None:
                temp_dir.cleanup()

    def dump(self, progress: Progress):
        # 1. Take a snapshot of what files exist in the current export folder
        for x in self.target.glob("**/*"):
            if x.is_file():
                self.files_in_export_dir.add(x.resolve())

        # 2. Create manifest, containing all correspondents, types, tags, storage paths
        # note, documents and ui_settings
        manifest_key_to_object_query: dict[str, QuerySet] = {
            "correspondents": Correspondent.objects.all(),
            "tags": Tag.objects.all(),
            "document_types": DocumentType.objects.all(),
            "storage_paths": StoragePath.objects.all(),
            "mail_accounts": MailAccount.objects.all(),
            "mail_rules": MailRule.objects.all(),
            "saved_views": SavedView.objects.all(),
            "saved_view_filter_rules": SavedViewFilterRule.objects.all(),
            "groups": Group.objects.all(),
            "users": User.objects.exclude(
                username__in=["consumer", "AnonymousUser"],
            ).all(),
            "ui_settings": UiSettings.objects.all(),
            "content_types": ContentType.objects.all(),
            "permissions": Permission.objects.all(),
            "user_object_permissions": UserObjectPermission.objects.all(),
            "group_object_permissions": GroupObjectPermission.objects.all(),
            "workflow_triggers": WorkflowTrigger.objects.all(),
            "workflow_actions": WorkflowAction.objects.all(),
            "workflow_email_actions": WorkflowActionEmail.objects.all(),
            "workflow_webhook_actions": WorkflowActionWebhook.objects.all(),
            "workflows": Workflow.objects.all(),
            "custom_fields": CustomField.objects.all(),
            "custom_field_instances": CustomFieldInstance.objects.all(),
            "app_configs": ApplicationConfiguration.objects.all(),
            "notes": Note.objects.all(),
            "documents": Document.objects.order_by("id").all(),
            "social_accounts": SocialAccount.objects.all(),
            "social_apps": SocialApp.objects.all(),
            "social_tokens": SocialToken.objects.all(),
            "authenticators": Authenticator.objects.all(),
        }

        if settings.AUDIT_LOG_ENABLED:
            manifest_key_to_object_query["log_entries"] = LogEntry.objects.all()

        with transaction.atomic():
            manifest_dict = {}

            serialize_task = progress.add_task(
                "Serializing database",
                total=len(manifest_key_to_object_query),
            )

            # Build an overall manifest
            for key, object_query in manifest_key_to_object_query.items():
                manifest_dict[key] = json.loads(
                    serializers.serialize("json", object_query),
                )
                progress.advance(serialize_task)

            self.encrypt_secret_fields(manifest_dict)

            # These are treated specially and included in the per-document manifest
            # if that setting is enabled.  Otherwise, they are just exported to the bulk
            # manifest
            document_map: dict[int, Document] = {
                d.pk: d for d in manifest_key_to_object_query["documents"]
            }
            document_manifest = manifest_dict["documents"]

        copy_task = progress.add_task("Copying files", total=len(document_manifest))

        # 3. Export files from each document
        for index, document_dict in enumerate(document_manifest):
            # 3.1. store files unencrypted
            document_dict["fields"]["storage_type"] = Document.STORAGE_TYPE_UNENCRYPTED

            document = document_map[document_dict["pk"]]

            # 3.2. generate a unique filename
            base_name = self.generate_base_name(document)

            # 3.3. write filenames into manifest
            original_target, thumbnail_target, archive_target = (
                self.generate_document_targets(document, base_name, document_dict)
            )

            # 3.4. write files to target folder
            if not self.data_only:
                self.copy_document_files(
                    document,
                    original_target,
                    thumbnail_target,
                    archive_target,
                )

            if self.split_manifest:
                manifest_name = Path(base_name + "-manifest.json")
                if self.use_folder_prefix:
                    manifest_name = Path("json") / manifest_name
                manifest_name = (self.target / manifest_name).resolve()
                manifest_name.parent.mkdir(parents=True, exist_ok=True)
                content = [document_manifest[index]]
                content += list(
                    filter(
                        lambda d: d["fields"]["document"] == document_dict["pk"],
                        manifest_dict["notes"],
                    ),
                )
                content += list(
                    filter(
                        lambda d: d["fields"]["document"] == document_dict["pk"],
                        manifest_dict["custom_field_instances"],
                    ),
                )

                self.check_and_write_json(
                    content,
                    manifest_name,
                )
            progress.advance(copy_task)

        # These were exported already
        if self.split_manifest:
            del manifest_dict["documents"]
            del manifest_dict["notes"]
            del manifest_dict["custom_field_instances"]

        # 4.1 write primary manifest to target folder
        manifest = []
        for key, item in manifest_dict.items():
            manifest.extend(item)
        manifest_path = (self.target / "manifest.json").resolve()
        self.check_and_write_json(
            manifest,
            manifest_path,
        )

        # 4.2 write version information to target folder
        extra_metadata_path = (self.target / "metadata.json").resolve()
        metadata: dict[str, str | int | dict[str, str | int]] = {
            "version": version.__full_version_str__,
        }

        # 4.2.1 If needed, write the crypto values into the metadata
        # Django stores most of these in the field itself, we store them once here
        if self.passphrase:
            metadata.update(self.get_crypt_params())

        self.check_and_write_json(
            metadata,
            extra_metadata_path,
        )

        if self.delete:
            # 5. Remove files which we did not explicitly export in this run
            if not self.zip_export:
                for f in self.files_in_export_dir:
                    f.unlink()

                    delete_empty_directories(
                        f.parent,
                        self.target,
                    )
            else:
                # 5. Remove anything in the original location (before moving the zip)
                for item in self.original_target.glob("*"):
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()

    def generate_base_name(self, document: Document) -> str:
        """
        Generates a unique name for the document, one which hasn't already been exported (or will be)
        """
        filename_counter = 0
        while True:
            if self.use_filename_format:
                base_name = generate_filename(
                    document,
                    counter=filename_counter,
                    append_gpg=False,
                )
            else:
                base_name = document.get_public_filename(counter=filename_counter)

            if base_name not in self.exported_files:
                self.exported_files.add(base_name)
                break
            else:
                filename_counter += 1
        return base_name

    def generate_document_targets(
        self,
        document: Document,
        base_name: str,
        document_dict: dict,
    ) -> tuple[Path, Path | None, Path | None]:
        """
        Generates the targets for a given document, including the original file, archive file and thumbnail (depending on settings).
        """
        original_name = base_name
        if self.use_folder_prefix:
            original_name = os.path.join("originals", original_name)
        original_target = (self.target / Path(original_name)).resolve()
        document_dict[EXPORTER_FILE_NAME] = original_name

        if not self.no_thumbnail:
            thumbnail_name = base_name + "-thumbnail.webp"
            if self.use_folder_prefix:
                thumbnail_name = os.path.join("thumbnails", thumbnail_name)
            thumbnail_target = (self.target / Path(thumbnail_name)).resolve()
            document_dict[EXPORTER_THUMBNAIL_NAME] = thumbnail_name
        else:
            thumbnail_target = None

        if not self.no_archive and document.has_archive_version:
            archive_name = base_name + "-archive.pdf"
            if self.use_folder_prefix:
                archive_name = os.path.join("archive", archive_name)
            archive_target = (self.target / Path(archive_name)).resolve()
            document_dict[EXPORTER_ARCHIVE_NAME] = archive_name
        else:
            archive_target = None

        return original_target, thumbnail_target, archive_target

    def copy_document_files(
        self,
        document: Document,
        original_target: Path,
        thumbnail_target: Path | None,
        archive_target: Path | None,
    ) -> None:
        """
        Copies files from the document storage location to the specified target location.

        If the document is encrypted, the files are decrypted before copying them to the target location.
        """
        if document.storage_type == Document.STORAGE_TYPE_GPG:
            t = int(time.mktime(document.created.timetuple()))

            original_target.parent.mkdir(parents=True, exist_ok=True)
            with document.source_file as out_file:
                original_target.write_bytes(GnuPG.decrypted(out_file))
                os.utime(original_target, times=(t, t))

            if thumbnail_target:
                thumbnail_target.parent.mkdir(parents=True, exist_ok=True)
                with document.thumbnail_file as out_file:
                    thumbnail_target.write_bytes(GnuPG.decrypted(out_file))
                    os.utime(thumbnail_target, times=(t, t))

            if archive_target:
                archive_target.parent.mkdir(parents=True, exist_ok=True)
                if TYPE_CHECKING:
                    assert isinstance(document.archive_path, Path)
                with document.archive_path as out_file:
                    archive_target.write_bytes(GnuPG.decrypted(out_file))
                    os.utime(archive_target, times=(t, t))
        else:
            self.check_and_copy(
                document.source_path,
                document.checksum,
                original_target,
            )

            if thumbnail_target:
                self.check_and_copy(document.thumbnail_path, None, thumbnail_target)

            if archive_target:
                if TYPE_CHECKING:
                    assert isinstance(document.archive_path, Path)
                self.check_and_copy(
                    document.archive_path,
                    document.archive_checksum,
                    archive_target,
                )

    def check_and_write_json(
        self,
        content: list[dict] | dict,
        target: Path,
    ):
        """
        Writes the source content to the target json file.
        If --compare-json arg was used, don't write to target file if
        the file exists and checksum is identical to content checksum.
        This preserves the file timestamps when no changes are made.
        """

        target = target.resolve()
        perform_write = True
        if target in self.files_in_export_dir:
            self.files_in_export_dir.remove(target)
            if self.compare_json:
                target_checksum = hashlib.md5(target.read_bytes()).hexdigest()
                src_str = json.dumps(content, indent=2, ensure_ascii=False)
                src_checksum = hashlib.md5(src_str.encode("utf-8")).hexdigest()
                if src_checksum == target_checksum:
                    perform_write = False

        if perform_write:
            target.write_text(
                json.dumps(content, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    def check_and_copy(
        self,
        source: Path,
        source_checksum: str | None,
        target: Path,
    ):
        """
        Copies the source to the target, if target doesn't exist or the target doesn't seem to match
        the source attributes
        """

        target = target.resolve()
        if target in self.files_in_export_dir:
            self.files_in_export_dir.remove(target)

        perform_copy = False

        if target.exists():
            source_stat = os.stat(source)
            target_stat = target.stat()
            if self.compare_checksums and source_checksum:
                target_checksum = hashlib.md5(target.read_bytes()).hexdigest()
                perform_copy = target_checksum != source_checksum
            elif (
                source_stat.st_mtime != target_stat.st_mtime
                or source_stat.st_size != target_stat.st_size
            ):
                perform_copy = True
        else:
            # Copy if it does not exist
            perform_copy = True

        if perform_copy:
            target.parent.mkdir(parents=True, exist_ok=True)
            copy_file_with_basic_stats(source, target)

    def encrypt_secret_fields(self, manifest: dict) -> None:
        """
        Encrypts certain fields in the export.  Currently limited to the mail account password
        """

        if self.passphrase:
            self.setup_crypto(passphrase=self.passphrase)

            for crypt_config in self.CRYPT_FIELDS:
                exporter_key = crypt_config["exporter_key"]
                crypt_fields = crypt_config["fields"]
                for manifest_record in manifest[exporter_key]:
                    for field in crypt_fields:
                        if manifest_record["fields"][field]:
                            manifest_record["fields"][field] = self.encrypt_string(
                                value=manifest_record["fields"][field],
                            )

        elif MailAccount.objects.count() > 0 or SocialToken.objects.count() > 0:
            self.stdout.write(
                self.style.NOTICE(
                    "No passphrase was given, sensitive fields will be in plaintext",
                ),
            )
