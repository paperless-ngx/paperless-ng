from auditlog.models import LogEntry
from django.core.management.base import BaseCommand
from django.db import transaction
from rich.progress import track

from documents.management.commands.mixins import ProgressBarMixin


class Command(BaseCommand, ProgressBarMixin):
    """
    Prune the audit logs of objects that no longer exist.
    """

    help = "Prunes the audit logs of objects that no longer exist."

    def add_arguments(self, parser):
        self.add_argument_progress_bar_mixin(parser)

    def handle(self, **options):
        self.handle_progress_bar_mixin(**options)
        with transaction.atomic():
            for log_entry in track(
                LogEntry.objects.all(),
                disable=self.no_progress_bar,
            ):
                model_class = log_entry.content_type.model_class()
                # use global_objects for SoftDeleteModel
                objects = (
                    model_class.global_objects
                    if hasattr(model_class, "global_objects")
                    else model_class.objects
                )
                if (
                    log_entry.object_id
                    and not objects.filter(pk=log_entry.object_id).exists()
                ):
                    log_entry.delete()
                    self.stdout.write(
                        self.style.NOTICE(
                            f"Deleted audit log entry for {model_class.__name__} #{log_entry.object_id}",
                        ),
                    )
