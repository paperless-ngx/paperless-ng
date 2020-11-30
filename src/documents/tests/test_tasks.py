from datetime import datetime

from django.test import TestCase

from documents import tasks
from documents.models import Document
from documents.tests.utils import DirectoriesMixin


class TestTasks(DirectoriesMixin, TestCase):

    def test_index_reindex(self):
        Document.objects.create(title="test", content="my document", checksum="wow", added=datetime.now(), created=datetime.now(), modified=datetime.now())

        tasks.index_reindex()

    def test_index_optimize(self):
        Document.objects.create(title="test", content="my document", checksum="wow", added=datetime.now(), created=datetime.now(), modified=datetime.now())

        tasks.index_optimize()

    def test_train_classifier(self):
        tasks.train_classifier()
