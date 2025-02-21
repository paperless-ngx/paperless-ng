from django.core.management.base import BaseCommand

from documents.tasks import train_classifier


class Command(BaseCommand):
    help = (
        "Trains the classifier on your data and saves the resulting models to a "
        "file. The document consumer will then automatically use this new model."
    )

    def handle(self, *args, **options):
        train_classifier(scheduled=False)
