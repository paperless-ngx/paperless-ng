from django.core.management.base import BaseCommand
from django.db import connection
from django.db import models

from documents.models import Document


class Command(BaseCommand):
    # This code is taken almost entirely from https://github.com/wagtail/wagtail/pull/11912 with all credit to the original author.
    help = "Converts UUID columns from char type to the native UUID type used in MariaDB 10.7+ and Django 5.0+."

    def convert_field(self, model, field_name, *, null=False):
        if model._meta.get_field(field_name).model != model:  # pragma: no cover
            # Field is inherited from a parent model
            return

        if not model._meta.managed:  # pragma: no cover
            # The migration framework skips unmanaged models, so we should too
            return

        old_field = models.CharField(null=null, max_length=36)
        old_field.set_attributes_from_name(field_name)

        new_field = models.UUIDField(null=null)
        new_field.set_attributes_from_name(field_name)

        with connection.schema_editor() as schema_editor:
            schema_editor.alter_field(model, old_field, new_field)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully converted {model._meta.label} {field_name} field to UUID type.",
                ),
            )

    def handle(self, **options):
        self.convert_field(Document, "transaction_id", null=True)
