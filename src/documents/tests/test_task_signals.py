import uuid
from unittest import mock

import celery
from django.test import TestCase

from documents.data_models import ConsumableDocument
from documents.data_models import DocumentMetadataOverrides
from documents.data_models import DocumentSource
from documents.models import PaperlessTask
from documents.signals.handlers import before_task_publish_handler
from documents.signals.handlers import task_failure_handler
from documents.signals.handlers import task_postrun_handler
from documents.signals.handlers import task_prerun_handler
from documents.tests.test_consumer import fake_magic_from_file
from documents.tests.utils import DirectoriesMixin


@mock.patch("documents.consumer.magic.from_file", fake_magic_from_file)
class TestTaskSignalHandler(DirectoriesMixin, TestCase):
    def util_call_before_task_publish_handler(self, headers_to_use, body_to_use):
        """
        Simple utility to call the pre-run handle and ensure it created a single task
        instance
        """
        self.assertEqual(PaperlessTask.objects.all().count(), 0)

        before_task_publish_handler(headers=headers_to_use, body=body_to_use)

        self.assertEqual(PaperlessTask.objects.all().count(), 1)

    def test_before_task_publish_handler_consume(self):
        """
        GIVEN:
            - A celery task is started via the consume folder
        WHEN:
            - Task before publish handler is called
        THEN:
            - The task is created and marked as pending
        """
        headers = {
            "id": str(uuid.uuid4()),
            "task": "documents.tasks.consume_file",
        }
        body = (
            # args
            (
                ConsumableDocument(
                    source=DocumentSource.ConsumeFolder,
                    original_file="/consume/hello-999.pdf",
                ),
                DocumentMetadataOverrides(
                    title="Hello world",
                    owner_id=1,
                ),
            ),
            # kwargs
            {},
            # celery stuff
            {"callbacks": None, "errbacks": None, "chain": None, "chord": None},
        )
        self.util_call_before_task_publish_handler(
            headers_to_use=headers,
            body_to_use=body,
        )

        task = PaperlessTask.objects.get()
        self.assertIsNotNone(task)
        self.assertEqual(headers["id"], task.task_id)
        self.assertEqual("hello-999.pdf", task.task_file_name)
        self.assertEqual(PaperlessTask.TaskName.CONSUME_FILE, task.task_name)
        self.assertEqual(1, task.owner_id)
        self.assertEqual(celery.states.PENDING, task.status)

    def test_task_prerun_handler(self):
        """
        GIVEN:
            - A celery task is started via the consume folder
        WHEN:
            - Task starts execution
        THEN:
            - The task is marked as started
        """

        headers = {
            "id": str(uuid.uuid4()),
            "task": "documents.tasks.consume_file",
        }
        body = (
            # args
            (
                ConsumableDocument(
                    source=DocumentSource.ConsumeFolder,
                    original_file="/consume/hello-99.pdf",
                ),
                None,
            ),
            # kwargs
            {},
            # celery stuff
            {"callbacks": None, "errbacks": None, "chain": None, "chord": None},
        )

        self.util_call_before_task_publish_handler(
            headers_to_use=headers,
            body_to_use=body,
        )

        task_prerun_handler(task_id=headers["id"])

        task = PaperlessTask.objects.get()

        self.assertEqual(celery.states.STARTED, task.status)

    def test_task_postrun_handler(self):
        """
        GIVEN:
            - A celery task is started via the consume folder
        WHEN:
            - Task finished execution
        THEN:
            - The task is marked as started
        """
        headers = {
            "id": str(uuid.uuid4()),
            "task": "documents.tasks.consume_file",
        }
        body = (
            # args
            (
                ConsumableDocument(
                    source=DocumentSource.ConsumeFolder,
                    original_file="/consume/hello-9.pdf",
                ),
                None,
            ),
            # kwargs
            {},
            # celery stuff
            {"callbacks": None, "errbacks": None, "chain": None, "chord": None},
        )
        self.util_call_before_task_publish_handler(
            headers_to_use=headers,
            body_to_use=body,
        )

        task_postrun_handler(
            task_id=headers["id"],
            retval="Success. New document id 1 created",
            state=celery.states.SUCCESS,
        )

        task = PaperlessTask.objects.get()

        self.assertEqual(celery.states.SUCCESS, task.status)

    def test_task_failure_handler(self):
        """
        GIVEN:
            - A celery task is started via the consume folder
        WHEN:
            - Task failed execution
        THEN:
            - The task is marked as failed
        """
        headers = {
            "id": str(uuid.uuid4()),
            "task": "documents.tasks.consume_file",
        }
        body = (
            # args
            (
                ConsumableDocument(
                    source=DocumentSource.ConsumeFolder,
                    original_file="/consume/hello-9.pdf",
                ),
                None,
            ),
            # kwargs
            {},
            # celery stuff
            {"callbacks": None, "errbacks": None, "chain": None, "chord": None},
        )
        self.util_call_before_task_publish_handler(
            headers_to_use=headers,
            body_to_use=body,
        )

        task_failure_handler(
            task_id=headers["id"],
            exception="Example failure",
        )

        task = PaperlessTask.objects.get()

        self.assertEqual(celery.states.FAILURE, task.status)
