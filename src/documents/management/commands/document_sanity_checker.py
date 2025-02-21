from django.core.management.base import BaseCommand

from documents.management.commands.mixins import ProgressBarMixin
from documents.sanity_checker import check_sanity


class Command(ProgressBarMixin, BaseCommand):
    help = "This command checks your document archive for issues."

    def add_arguments(self, parser):
        self.add_argument_progress_bar_mixin(parser)

    def handle(self, *args, **options):
        self.handle_progress_bar_mixin(**options)
        messages = check_sanity(progress=self.use_progress_bar, scheduled=False)

        messages.log_messages()
