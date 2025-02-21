import uuid

import celery
from django.contrib.auth.models import Permission
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from documents.models import PaperlessTask
from documents.tests.utils import DirectoriesMixin


class TestTasks(DirectoriesMixin, APITestCase):
    ENDPOINT = "/api/tasks/"

    def setUp(self):
        super().setUp()

        self.user = User.objects.create_superuser(username="temp_admin")
        self.client.force_authenticate(user=self.user)

    def test_get_tasks(self):
        """
        GIVEN:
            - Attempted celery tasks
        WHEN:
            - API call is made to get tasks
        THEN:
            - Attempting and pending tasks are serialized and provided
        """

        task1 = PaperlessTask.objects.create(
            task_id=str(uuid.uuid4()),
            task_file_name="task_one.pdf",
        )

        task2 = PaperlessTask.objects.create(
            task_id=str(uuid.uuid4()),
            task_file_name="task_two.pdf",
        )

        response = self.client.get(self.ENDPOINT)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        returned_task1 = response.data[1]
        returned_task2 = response.data[0]

        self.assertEqual(returned_task1["task_id"], task1.task_id)
        self.assertEqual(returned_task1["status"], celery.states.PENDING)
        self.assertEqual(returned_task1["task_file_name"], task1.task_file_name)

        self.assertEqual(returned_task2["task_id"], task2.task_id)
        self.assertEqual(returned_task2["status"], celery.states.PENDING)
        self.assertEqual(returned_task2["task_file_name"], task2.task_file_name)

    def test_get_single_task_status(self):
        """
        GIVEN
            - Query parameter for a valid task ID
        WHEN:
            - API call is made to get task status
        THEN:
            - Single task data is returned
        """

        id1 = str(uuid.uuid4())
        task1 = PaperlessTask.objects.create(
            task_id=id1,
            task_file_name="task_one.pdf",
        )

        _ = PaperlessTask.objects.create(
            task_id=str(uuid.uuid4()),
            task_file_name="task_two.pdf",
        )

        response = self.client.get(self.ENDPOINT + f"?task_id={id1}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        returned_task1 = response.data[0]

        self.assertEqual(returned_task1["task_id"], task1.task_id)

    def test_get_single_task_status_not_valid(self):
        """
        GIVEN
            - Query parameter for a non-existent task ID
        WHEN:
            - API call is made to get task status
        THEN:
            - No task data is returned
        """
        PaperlessTask.objects.create(
            task_id=str(uuid.uuid4()),
            task_file_name="task_one.pdf",
        )

        _ = PaperlessTask.objects.create(
            task_id=str(uuid.uuid4()),
            task_file_name="task_two.pdf",
        )

        response = self.client.get(self.ENDPOINT + "?task_id=bad-task-id")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_acknowledge_tasks(self):
        """
        GIVEN:
            - Attempted celery tasks
        WHEN:
            - API call is made to get mark task as acknowledged
        THEN:
            - Task is marked as acknowledged
        """
        task = PaperlessTask.objects.create(
            task_id=str(uuid.uuid4()),
            task_file_name="task_one.pdf",
        )

        response = self.client.get(self.ENDPOINT)
        self.assertEqual(len(response.data), 1)

        response = self.client.post(
            self.ENDPOINT + "acknowledge/",
            {"tasks": [task.id]},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(self.ENDPOINT + "?acknowledged=false")
        self.assertEqual(len(response.data), 0)

    def test_tasks_owner_aware(self):
        """
        GIVEN:
            - Existing PaperlessTasks with owner and with no owner
        WHEN:
            - API call is made to get tasks
        THEN:
            - Only tasks with no owner or request user are returned
        """

        regular_user = User.objects.create_user(username="test")
        regular_user.user_permissions.add(*Permission.objects.all())
        self.client.logout()
        self.client.force_authenticate(user=regular_user)

        task1 = PaperlessTask.objects.create(
            task_id=str(uuid.uuid4()),
            task_file_name="task_one.pdf",
            owner=self.user,
        )

        task2 = PaperlessTask.objects.create(
            task_id=str(uuid.uuid4()),
            task_file_name="task_two.pdf",
        )

        task3 = PaperlessTask.objects.create(
            task_id=str(uuid.uuid4()),
            task_file_name="task_three.pdf",
            owner=regular_user,
        )

        response = self.client.get(self.ENDPOINT)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]["task_id"], task3.task_id)
        self.assertEqual(response.data[1]["task_id"], task2.task_id)

        acknowledge_response = self.client.post(
            self.ENDPOINT + "acknowledge/",
            {"tasks": [task1.id, task2.id, task3.id]},
        )
        self.assertEqual(acknowledge_response.status_code, status.HTTP_200_OK)
        self.assertEqual(acknowledge_response.data, {"result": 2})

    def test_task_result_no_error(self):
        """
        GIVEN:
            - A celery task completed without error
        WHEN:
            - API call is made to get tasks
        THEN:
            - The returned data includes the task result
        """
        PaperlessTask.objects.create(
            task_id=str(uuid.uuid4()),
            task_file_name="task_one.pdf",
            status=celery.states.SUCCESS,
            result="Success. New document id 1 created",
        )

        response = self.client.get(self.ENDPOINT)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        returned_data = response.data[0]

        self.assertEqual(returned_data["result"], "Success. New document id 1 created")
        self.assertEqual(returned_data["related_document"], "1")

    def test_task_result_with_error(self):
        """
        GIVEN:
            - A celery task completed with an exception
        WHEN:
            - API call is made to get tasks
        THEN:
            - The returned result is the exception info
        """
        PaperlessTask.objects.create(
            task_id=str(uuid.uuid4()),
            task_file_name="task_one.pdf",
            status=celery.states.FAILURE,
            result="test.pdf: Not consuming test.pdf: It is a duplicate.",
        )

        response = self.client.get(self.ENDPOINT)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        returned_data = response.data[0]

        self.assertEqual(
            returned_data["result"],
            "test.pdf: Not consuming test.pdf: It is a duplicate.",
        )

    def test_task_name_webui(self):
        """
        GIVEN:
            - Attempted celery task
            - Task was created through the webui
        WHEN:
            - API call is made to get tasks
        THEN:
            - Returned data include the filename
        """
        PaperlessTask.objects.create(
            task_id=str(uuid.uuid4()),
            task_file_name="test.pdf",
            task_name=PaperlessTask.TaskName.CONSUME_FILE,
            status=celery.states.SUCCESS,
        )

        response = self.client.get(self.ENDPOINT)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        returned_data = response.data[0]

        self.assertEqual(returned_data["task_file_name"], "test.pdf")

    def test_task_name_consume_folder(self):
        """
        GIVEN:
            - Attempted celery task
            - Task was created through the consume folder
        WHEN:
            - API call is made to get tasks
        THEN:
            - Returned data include the filename
        """
        PaperlessTask.objects.create(
            task_id=str(uuid.uuid4()),
            task_file_name="anothertest.pdf",
            task_name=PaperlessTask.TaskName.CONSUME_FILE,
            status=celery.states.SUCCESS,
        )

        response = self.client.get(self.ENDPOINT)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        returned_data = response.data[0]

        self.assertEqual(returned_data["task_file_name"], "anothertest.pdf")

    def test_task_result_failed_duplicate_includes_related_doc(self):
        """
        GIVEN:
            - A celery task failed with a duplicate error
        WHEN:
            - API call is made to get tasks
        THEN:
            - The returned data includes a related document link
        """
        PaperlessTask.objects.create(
            task_id=str(uuid.uuid4()),
            task_file_name="task_one.pdf",
            status=celery.states.FAILURE,
            result="Not consuming task_one.pdf: It is a duplicate of task_one_existing.pdf (#1234).",
        )

        response = self.client.get(self.ENDPOINT)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        returned_data = response.data[0]

        self.assertEqual(returned_data["related_document"], "1234")
