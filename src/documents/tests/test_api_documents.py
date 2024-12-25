import datetime
import os
import shutil
import tempfile
import uuid
import zoneinfo
from binascii import hexlify
from datetime import date
from datetime import timedelta
from pathlib import Path
from unittest import mock

import celery
from dateutil import parser
from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.db import DataError
from django.test import override_settings
from django.utils import timezone
from guardian.shortcuts import assign_perm
from rest_framework import status
from rest_framework.test import APITestCase

from documents.caching import CACHE_50_MINUTES
from documents.caching import CLASSIFIER_HASH_KEY
from documents.caching import CLASSIFIER_MODIFIED_KEY
from documents.caching import CLASSIFIER_VERSION_KEY
from documents.models import Correspondent
from documents.models import CustomField
from documents.models import CustomFieldInstance
from documents.models import Document
from documents.models import DocumentType
from documents.models import MatchingModel
from documents.models import Note
from documents.models import SavedView
from documents.models import ShareLink
from documents.models import StoragePath
from documents.models import Tag
from documents.tests.utils import DirectoriesMixin
from documents.tests.utils import DocumentConsumeDelayMixin


class TestDocumentApi(DirectoriesMixin, DocumentConsumeDelayMixin, APITestCase):
    def setUp(self):
        super().setUp()

        self.user = User.objects.create_superuser(username="temp_admin")
        self.client.force_authenticate(user=self.user)
        cache.clear()

    def testDocuments(self):
        response = self.client.get("/api/documents/").data

        self.assertEqual(response["count"], 0)

        c = Correspondent.objects.create(name="c", pk=41)
        dt = DocumentType.objects.create(name="dt", pk=63)
        tag = Tag.objects.create(name="t", pk=85)

        doc = Document.objects.create(
            title="WOW",
            content="the content",
            correspondent=c,
            document_type=dt,
            checksum="123",
            mime_type="application/pdf",
        )

        doc.tags.add(tag)

        response = self.client.get("/api/documents/", format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

        returned_doc = response.data["results"][0]
        self.assertEqual(returned_doc["id"], doc.id)
        self.assertEqual(returned_doc["title"], doc.title)
        self.assertEqual(returned_doc["correspondent"], c.id)
        self.assertEqual(returned_doc["document_type"], dt.id)
        self.assertListEqual(returned_doc["tags"], [tag.id])

        c2 = Correspondent.objects.create(name="c2")

        returned_doc["correspondent"] = c2.pk
        returned_doc["title"] = "the new title"

        response = self.client.put(
            f"/api/documents/{doc.pk}/",
            returned_doc,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        doc_after_save = Document.objects.get(id=doc.id)

        self.assertEqual(doc_after_save.correspondent, c2)
        self.assertEqual(doc_after_save.title, "the new title")

        self.client.delete(f"/api/documents/{doc_after_save.pk}/")

        self.assertEqual(len(Document.objects.all()), 0)

    def test_document_fields(self):
        c = Correspondent.objects.create(name="c", pk=41)
        dt = DocumentType.objects.create(name="dt", pk=63)
        Tag.objects.create(name="t", pk=85)
        storage_path = StoragePath.objects.create(name="sp", pk=77, path="p")
        Document.objects.create(
            title="WOW",
            content="the content",
            correspondent=c,
            document_type=dt,
            checksum="123",
            mime_type="application/pdf",
            storage_path=storage_path,
        )

        response = self.client.get("/api/documents/", format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results_full = response.data["results"]
        self.assertIn("content", results_full[0])
        self.assertIn("id", results_full[0])

        response = self.client.get("/api/documents/?fields=id", format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertFalse("content" in results[0])
        self.assertIn("id", results[0])
        self.assertEqual(len(results[0]), 1)

        response = self.client.get("/api/documents/?fields=content", format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertIn("content", results[0])
        self.assertFalse("id" in results[0])
        self.assertEqual(len(results[0]), 1)

        response = self.client.get("/api/documents/?fields=id,content", format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertIn("content", results[0])
        self.assertIn("id", results[0])
        self.assertEqual(len(results[0]), 2)

        response = self.client.get(
            "/api/documents/?fields=id,conteasdnt",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertFalse("content" in results[0])
        self.assertIn("id", results[0])
        self.assertEqual(len(results[0]), 1)

        response = self.client.get("/api/documents/?fields=", format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results_full[0]), len(results[0]))

        response = self.client.get("/api/documents/?fields=dgfhs", format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results[0]), 0)

    def test_document_actions(self):
        _, filename = tempfile.mkstemp(dir=self.dirs.originals_dir)

        content = b"This is a test"
        content_thumbnail = b"thumbnail content"

        with open(filename, "wb") as f:
            f.write(content)

        doc = Document.objects.create(
            title="none",
            filename=os.path.basename(filename),
            mime_type="application/pdf",
        )

        with open(
            os.path.join(self.dirs.thumbnail_dir, f"{doc.pk:07d}.webp"),
            "wb",
        ) as f:
            f.write(content_thumbnail)

        response = self.client.get(f"/api/documents/{doc.pk}/download/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, content)

        response = self.client.get(f"/api/documents/{doc.pk}/preview/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, content)

        response = self.client.get(f"/api/documents/{doc.pk}/thumb/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, content_thumbnail)

    def test_document_actions_with_perms(self):
        """
        GIVEN:
            - Document with owner and without granted permissions
            - User is then granted permissions
        WHEN:
            - User tries to load preview, thumbnail
        THEN:
            - Initially, HTTP 403 Forbidden
            - With permissions, HTTP 200 OK
        """
        _, filename = tempfile.mkstemp(dir=self.dirs.originals_dir)

        content = b"This is a test"
        content_thumbnail = b"thumbnail content"

        with open(filename, "wb") as f:
            f.write(content)

        user1 = User.objects.create_user(username="test1")
        user2 = User.objects.create_user(username="test2")
        user1.user_permissions.add(*Permission.objects.filter(codename="view_document"))
        user2.user_permissions.add(*Permission.objects.filter(codename="view_document"))

        self.client.force_authenticate(user2)

        doc = Document.objects.create(
            title="none",
            filename=os.path.basename(filename),
            mime_type="application/pdf",
            owner=user1,
        )

        with open(
            os.path.join(self.dirs.thumbnail_dir, f"{doc.pk:07d}.webp"),
            "wb",
        ) as f:
            f.write(content_thumbnail)

        response = self.client.get(f"/api/documents/{doc.pk}/download/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.get(f"/api/documents/{doc.pk}/preview/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.get(f"/api/documents/{doc.pk}/thumb/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        assign_perm("view_document", user2, doc)

        response = self.client.get(f"/api/documents/{doc.pk}/download/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(f"/api/documents/{doc.pk}/preview/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(f"/api/documents/{doc.pk}/thumb/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(FILENAME_FORMAT="")
    def test_download_with_archive(self):
        content = b"This is a test"
        content_archive = b"This is the same test but archived"

        doc = Document.objects.create(
            title="none",
            filename="my_document.pdf",
            archive_filename="archived.pdf",
            mime_type="application/pdf",
        )

        with open(doc.source_path, "wb") as f:
            f.write(content)

        with open(doc.archive_path, "wb") as f:
            f.write(content_archive)

        response = self.client.get(f"/api/documents/{doc.pk}/download/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, content_archive)

        response = self.client.get(
            f"/api/documents/{doc.pk}/download/?original=true",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, content)

        response = self.client.get(f"/api/documents/{doc.pk}/preview/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, content_archive)

        response = self.client.get(
            f"/api/documents/{doc.pk}/preview/?original=true",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, content)

    def test_document_actions_not_existing_file(self):
        doc = Document.objects.create(
            title="none",
            filename=os.path.basename("asd"),
            mime_type="application/pdf",
        )

        response = self.client.get(f"/api/documents/{doc.pk}/download/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.get(f"/api/documents/{doc.pk}/preview/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.get(f"/api/documents/{doc.pk}/thumb/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_document_history_action(self):
        """
        GIVEN:
            - Document
        WHEN:
            - Document is updated
        THEN:
            - Audit log contains changes
        """
        doc = Document.objects.create(
            title="First title",
            checksum="123",
            mime_type="application/pdf",
        )
        self.client.force_login(user=self.user)
        self.client.patch(
            f"/api/documents/{doc.pk}/",
            {"title": "New title"},
            format="json",
        )

        response = self.client.get(f"/api/documents/{doc.pk}/history/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]["actor"]["id"], self.user.id)
        self.assertEqual(response.data[0]["action"], "update")
        self.assertEqual(
            response.data[0]["changes"],
            {"title": ["First title", "New title"]},
        )

    def test_document_history_action_w_custom_fields(self):
        """
        GIVEN:
            - Document with custom fields
        WHEN:
            - Document is updated
        THEN:
            - Audit log contains custom field changes
        """
        doc = Document.objects.create(
            title="First title",
            checksum="123",
            mime_type="application/pdf",
        )
        custom_field = CustomField.objects.create(
            name="custom field str",
            data_type=CustomField.FieldDataType.STRING,
        )
        self.client.force_login(user=self.user)

        # Initial response should include only document's creation
        response = self.client.get(f"/api/documents/{doc.pk}/history/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        self.assertIsNone(response.data[0]["actor"])
        self.assertEqual(response.data[0]["action"], "create")

        self.client.patch(
            f"/api/documents/{doc.pk}/",
            data={
                "custom_fields": [
                    {
                        "field": custom_field.pk,
                        "value": "custom value",
                    },
                ],
            },
            format="json",
        )

        # Second response should include custom field addition
        response = self.client.get(f"/api/documents/{doc.pk}/history/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]["actor"]["id"], self.user.id)
        self.assertEqual(response.data[0]["action"], "create")
        self.assertEqual(
            response.data[0]["changes"],
            {
                "custom_fields": {
                    "type": "custom_field",
                    "field": "custom field str",
                    "value": "custom value",
                },
            },
        )
        self.assertIsNone(response.data[1]["actor"])
        self.assertEqual(response.data[1]["action"], "create")

    @override_settings(AUDIT_LOG_ENABLED=False)
    def test_document_history_action_disabled(self):
        """
        GIVEN:
            - Audit log is disabled
        WHEN:
            - Document is updated
            - Audit log is requested
        THEN:
            - Audit log returns HTTP 400 Bad Request
        """
        doc = Document.objects.create(
            title="First title",
            checksum="123",
            mime_type="application/pdf",
        )
        self.client.force_login(user=self.user)
        self.client.patch(
            f"/api/documents/{doc.pk}/",
            {"title": "New title"},
            format="json",
        )

        response = self.client.get(f"/api/documents/{doc.pk}/history/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_document_history_insufficient_perms(self):
        """
        GIVEN:
            - Audit log is enabled
        WHEN:
            - History is requested without auditlog permissions
            - Or is requested as superuser on document with another owner
        THEN:
            - History endpoint returns HTTP 403 Forbidden
            - History is returned
        """
        # No auditlog permissions
        user = User.objects.create_user(username="test")
        user.user_permissions.add(*Permission.objects.filter(codename="view_document"))
        self.client.force_authenticate(user=user)
        doc = Document.objects.create(
            title="First title",
            checksum="123",
            mime_type="application/pdf",
            owner=user,
        )

        response = self.client.get(f"/api/documents/{doc.pk}/history/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # superuser
        user.is_superuser = True
        user.save()
        user2 = User.objects.create_user(username="test2")
        doc2 = Document.objects.create(
            title="Second title",
            checksum="456",
            mime_type="application/pdf",
            owner=user2,
        )
        response = self.client.get(f"/api/documents/{doc2.pk}/history/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_document_filters(self):
        doc1 = Document.objects.create(
            title="none1",
            checksum="A",
            mime_type="application/pdf",
        )
        doc2 = Document.objects.create(
            title="none2",
            checksum="B",
            mime_type="application/pdf",
        )
        doc3 = Document.objects.create(
            title="none3",
            checksum="C",
            mime_type="application/pdf",
        )

        tag_inbox = Tag.objects.create(name="t1", is_inbox_tag=True)
        tag_2 = Tag.objects.create(name="t2")
        tag_3 = Tag.objects.create(name="t3")

        cf1 = CustomField.objects.create(
            name="stringfield",
            data_type=CustomField.FieldDataType.STRING,
        )
        cf2 = CustomField.objects.create(
            name="numberfield",
            data_type=CustomField.FieldDataType.INT,
        )

        doc1.tags.add(tag_inbox)
        doc2.tags.add(tag_2)
        doc3.tags.add(tag_2)
        doc3.tags.add(tag_3)

        cf1_d1 = CustomFieldInstance.objects.create(
            document=doc1,
            field=cf1,
            value_text="foobard1",
        )
        CustomFieldInstance.objects.create(
            document=doc1,
            field=cf2,
            value_int=999,
        )
        cf1_d3 = CustomFieldInstance.objects.create(
            document=doc3,
            field=cf1,
            value_text="foobard3",
        )

        response = self.client.get("/api/documents/?is_in_inbox=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], doc1.id)

        response = self.client.get("/api/documents/?is_in_inbox=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 2)
        self.assertCountEqual([results[0]["id"], results[1]["id"]], [doc2.id, doc3.id])

        response = self.client.get(
            f"/api/documents/?tags__id__in={tag_inbox.id},{tag_3.id}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 2)
        self.assertCountEqual([results[0]["id"], results[1]["id"]], [doc1.id, doc3.id])

        response = self.client.get(
            f"/api/documents/?tags__id__in={tag_2.id},{tag_3.id}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 2)
        self.assertCountEqual([results[0]["id"], results[1]["id"]], [doc2.id, doc3.id])

        response = self.client.get(
            f"/api/documents/?tags__id__all={tag_2.id},{tag_3.id}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], doc3.id)

        response = self.client.get(
            f"/api/documents/?tags__id__all={tag_inbox.id},{tag_3.id}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 0)

        response = self.client.get(
            f"/api/documents/?tags__id__all={tag_inbox.id}a{tag_3.id}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 3)

        response = self.client.get(f"/api/documents/?tags__id__none={tag_3.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 2)
        self.assertCountEqual([results[0]["id"], results[1]["id"]], [doc1.id, doc2.id])

        response = self.client.get(
            f"/api/documents/?tags__id__none={tag_3.id},{tag_2.id}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], doc1.id)

        response = self.client.get(
            f"/api/documents/?tags__id__none={tag_2.id},{tag_inbox.id}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 0)

        response = self.client.get(
            f"/api/documents/?id__in={doc1.id},{doc2.id}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 2)

        response = self.client.get(
            f"/api/documents/?id__range={doc1.id},{doc3.id}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 3)

        response = self.client.get(
            f"/api/documents/?id={doc2.id}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)

        # custom field name
        response = self.client.get(
            f"/api/documents/?custom_fields__icontains={cf1.name}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 2)

        # custom field value
        response = self.client.get(
            f"/api/documents/?custom_fields__icontains={cf1_d1.value}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], doc1.id)

        response = self.client.get(
            f"/api/documents/?custom_fields__icontains={cf1_d3.value}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], doc3.id)

    def test_custom_field_select_filter(self):
        """
        GIVEN:
            - Documents with select custom field values
        WHEN:
            - API request with custom field filtering is made
        THEN:
            - Only docs with selected custom field values are returned
        """
        doc1 = Document.objects.create(checksum="1", content="test 1")
        Document.objects.create(checksum="2", content="test 2")
        custom_field_select = CustomField.objects.create(
            name="Test Custom Field Select",
            data_type=CustomField.FieldDataType.SELECT,
            extra_data={
                "select_options": [
                    {"label": "Option 1", "id": "abc123"},
                    {"label": "Choice 2", "id": "def456"},
                ],
            },
        )
        CustomFieldInstance.objects.create(
            document=doc1,
            field=custom_field_select,
            value_select="def456",
        )

        r = self.client.get("/api/documents/?custom_fields__icontains=choice")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 1)

        r = self.client.get("/api/documents/?custom_fields__icontains=option")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 0)

    def test_document_checksum_filter(self):
        Document.objects.create(
            title="none1",
            checksum="A",
            mime_type="application/pdf",
        )
        doc2 = Document.objects.create(
            title="none2",
            checksum="B",
            mime_type="application/pdf",
        )
        Document.objects.create(
            title="none3",
            checksum="C",
            mime_type="application/pdf",
        )

        response = self.client.get("/api/documents/?checksum__iexact=B")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], doc2.id)

        response = self.client.get("/api/documents/?checksum__iexact=X")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 0)

    def test_document_original_filename_filter(self):
        doc1 = Document.objects.create(
            title="none1",
            checksum="A",
            mime_type="application/pdf",
            original_filename="docA.pdf",
        )
        doc2 = Document.objects.create(
            title="none2",
            checksum="B",
            mime_type="application/pdf",
            original_filename="docB.pdf",
        )
        doc3 = Document.objects.create(
            title="none3",
            checksum="C",
            mime_type="application/pdf",
            original_filename="docC.pdf",
        )

        response = self.client.get("/api/documents/?original_filename__iexact=DOCa.pdf")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], doc1.id)

        response = self.client.get("/api/documents/?original_filename__iexact=docx.pdf")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 0)

        response = self.client.get("/api/documents/?original_filename__istartswith=dOc")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 3)
        self.assertCountEqual(
            [results[0]["id"], results[1]["id"], results[2]["id"]],
            [doc1.id, doc2.id, doc3.id],
        )

    def test_documents_title_content_filter(self):
        doc1 = Document.objects.create(
            title="title A",
            content="content A",
            checksum="A",
            mime_type="application/pdf",
        )
        doc2 = Document.objects.create(
            title="title B",
            content="content A",
            checksum="B",
            mime_type="application/pdf",
        )
        doc3 = Document.objects.create(
            title="title A",
            content="content B",
            checksum="C",
            mime_type="application/pdf",
        )
        doc4 = Document.objects.create(
            title="title B",
            content="content B",
            checksum="D",
            mime_type="application/pdf",
        )

        response = self.client.get("/api/documents/?title_content=A")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 3)
        self.assertCountEqual(
            [results[0]["id"], results[1]["id"], results[2]["id"]],
            [doc1.id, doc2.id, doc3.id],
        )

        response = self.client.get("/api/documents/?title_content=B")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 3)
        self.assertCountEqual(
            [results[0]["id"], results[1]["id"], results[2]["id"]],
            [doc2.id, doc3.id, doc4.id],
        )

        response = self.client.get("/api/documents/?title_content=X")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 0)

    def test_document_permissions_filters(self):
        """
        GIVEN:
            - Documents with owners, with and without granted permissions
        WHEN:
            - User filters by owner
        THEN:
            - Owner filters work correctly but still respect permissions
        """
        u1 = User.objects.create_user("user1")
        u2 = User.objects.create_user("user2")
        u1.user_permissions.add(*Permission.objects.filter(codename="view_document"))
        u2.user_permissions.add(*Permission.objects.filter(codename="view_document"))

        u1_doc1 = Document.objects.create(
            title="none1",
            checksum="A",
            mime_type="application/pdf",
            owner=u1,
        )
        Document.objects.create(
            title="none2",
            checksum="B",
            mime_type="application/pdf",
            owner=u2,
        )
        u0_doc1 = Document.objects.create(
            title="none3",
            checksum="C",
            mime_type="application/pdf",
        )
        u1_doc2 = Document.objects.create(
            title="none4",
            checksum="D",
            mime_type="application/pdf",
            owner=u1,
        )
        u2_doc2 = Document.objects.create(
            title="none5",
            checksum="E",
            mime_type="application/pdf",
            owner=u2,
        )

        self.client.force_authenticate(user=u1)
        assign_perm("view_document", u1, u2_doc2)

        # Will not show any u1 docs or u2_doc1 which isn't shared
        response = self.client.get(f"/api/documents/?owner__id__none={u1.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 2)
        self.assertCountEqual(
            [results[0]["id"], results[1]["id"]],
            [u0_doc1.id, u2_doc2.id],
        )

        # Will not show any u1 docs, u0_doc1 which has no owner or u2_doc1 which isn't shared
        response = self.client.get(
            f"/api/documents/?owner__id__none={u1.id}&owner__isnull=false",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertCountEqual([results[0]["id"]], [u2_doc2.id])

        # Will not show any u1 docs, u2_doc2 which is shared but has owner
        response = self.client.get(
            f"/api/documents/?owner__id__none={u1.id}&owner__isnull=true",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertCountEqual([results[0]["id"]], [u0_doc1.id])

        # Will not show any u1 docs or u2_doc1 which is not shared
        response = self.client.get(f"/api/documents/?owner__id={u2.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertCountEqual([results[0]["id"]], [u2_doc2.id])

        # Will not show u2_doc1 which is not shared
        response = self.client.get(f"/api/documents/?owner__id__in={u1.id},{u2.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 3)
        self.assertCountEqual(
            [results[0]["id"], results[1]["id"], results[2]["id"]],
            [u1_doc1.id, u1_doc2.id, u2_doc2.id],
        )

        assign_perm("view_document", u2, u1_doc1)

        # Will show only documents shared by user
        response = self.client.get(f"/api/documents/?shared_by__id={u1.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertCountEqual(
            [results[0]["id"]],
            [u1_doc1.id],
        )

    def test_pagination_all(self):
        """
        GIVEN:
            - A set of 50 documents
        WHEN:
            - API request for document filtering
        THEN:
            - Results are paginated (25 items) and response["all"] returns all ids (50 items)
        """
        t = Tag.objects.create(name="tag")
        docs = []
        for i in range(50):
            d = Document.objects.create(checksum=i, content=f"test{i}")
            d.tags.add(t)
            docs.append(d)

        response = self.client.get(
            f"/api/documents/?tags__id__in={t.id}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 25)
        self.assertEqual(len(response.data["all"]), 50)
        self.assertCountEqual(response.data["all"], [d.id for d in docs])

    def test_statistics(self):
        doc1 = Document.objects.create(
            title="none1",
            checksum="A",
            mime_type="application/pdf",
            content="abc",
        )
        Document.objects.create(
            title="none2",
            checksum="B",
            mime_type="application/pdf",
            content="123",
        )
        Document.objects.create(
            title="none3",
            checksum="C",
            mime_type="text/plain",
            content="hello",
        )

        tag_inbox = Tag.objects.create(name="t1", is_inbox_tag=True)
        Tag.objects.create(name="t2")
        Tag.objects.create(name="t3")
        Correspondent.objects.create(name="c1")
        Correspondent.objects.create(name="c2")
        DocumentType.objects.create(name="dt1")
        StoragePath.objects.create(name="sp1")
        StoragePath.objects.create(name="sp2")

        doc1.tags.add(tag_inbox)

        response = self.client.get("/api/statistics/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["documents_total"], 3)
        self.assertEqual(response.data["documents_inbox"], 1)
        self.assertEqual(response.data["inbox_tags"], [tag_inbox.pk])
        self.assertEqual(
            response.data["document_file_type_counts"][0]["mime_type_count"],
            2,
        )
        self.assertEqual(
            response.data["document_file_type_counts"][1]["mime_type_count"],
            1,
        )
        self.assertEqual(response.data["character_count"], 11)
        self.assertEqual(response.data["tag_count"], 3)
        self.assertEqual(response.data["correspondent_count"], 2)
        self.assertEqual(response.data["document_type_count"], 1)
        self.assertEqual(response.data["storage_path_count"], 2)

    def test_statistics_no_inbox_tag(self):
        Document.objects.create(title="none1", checksum="A")

        response = self.client.get("/api/statistics/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["documents_inbox"], None)
        self.assertEqual(response.data["inbox_tags"], None)

    def test_statistics_multiple_users(self):
        """
        GIVEN:
            - Inbox tags with different owners and documents that are accessible to different users
        WHEN:
            - Statistics are requested
        THEN:
            - Statistics only include inbox counts for tags accessible by the user
        """
        u1 = User.objects.create_user("user1")
        u2 = User.objects.create_user("user2")
        inbox_tag_u1 = Tag.objects.create(name="inbox_u1", is_inbox_tag=True, owner=u1)
        Tag.objects.create(name="inbox_u2", is_inbox_tag=True, owner=u2)
        doc_u1 = Document.objects.create(
            title="none1",
            checksum="A",
            mime_type="application/pdf",
            owner=u1,
        )
        doc2_u1 = Document.objects.create(
            title="none2",
            checksum="B",
            mime_type="application/pdf",
        )
        doc_u1.tags.add(inbox_tag_u1)
        doc2_u1.save()
        doc2_u1.tags.add(inbox_tag_u1)
        doc2_u1.save()

        self.client.force_authenticate(user=u1)
        response = self.client.get("/api/statistics/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["documents_inbox"], 2)

        self.client.force_authenticate(user=u2)
        response = self.client.get("/api/statistics/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["documents_inbox"], 0)

    def test_upload(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.consume_file_mock.assert_called_once()

        input_doc, overrides = self.get_last_consume_delay_call_args()

        self.assertEqual(input_doc.original_file.name, "simple.pdf")
        self.assertIn(Path(settings.SCRATCH_DIR), input_doc.original_file.parents)
        self.assertIsNone(overrides.title)
        self.assertIsNone(overrides.correspondent_id)
        self.assertIsNone(overrides.document_type_id)
        self.assertIsNone(overrides.tag_ids)

    def test_create_wrong_endpoint(self):
        response = self.client.post(
            "/api/documents/",
            {},
        )

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_upload_empty_metadata(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {
                    "document": f,
                    "title": "",
                    "correspondent": "",
                    "document_type": "",
                    "storage_path": "",
                },
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.consume_file_mock.assert_called_once()

        input_doc, overrides = self.get_last_consume_delay_call_args()

        self.assertEqual(input_doc.original_file.name, "simple.pdf")
        self.assertIn(Path(settings.SCRATCH_DIR), input_doc.original_file.parents)
        self.assertIsNone(overrides.title)
        self.assertIsNone(overrides.correspondent_id)
        self.assertIsNone(overrides.document_type_id)
        self.assertIsNone(overrides.storage_path_id)
        self.assertIsNone(overrides.tag_ids)

    def test_upload_invalid_form(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"documenst": f},
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.consume_file_mock.assert_not_called()

    def test_upload_invalid_file(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.zip"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f},
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.consume_file_mock.assert_not_called()

    def test_upload_with_title(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f, "title": "my custom title"},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.consume_file_mock.assert_called_once()

        _, overrides = self.get_last_consume_delay_call_args()

        self.assertEqual(overrides.title, "my custom title")
        self.assertIsNone(overrides.correspondent_id)
        self.assertIsNone(overrides.document_type_id)
        self.assertIsNone(overrides.tag_ids)

    def test_upload_with_correspondent(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        c = Correspondent.objects.create(name="test-corres")
        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f, "correspondent": c.id},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.consume_file_mock.assert_called_once()

        _, overrides = self.get_last_consume_delay_call_args()

        self.assertEqual(overrides.correspondent_id, c.id)
        self.assertIsNone(overrides.title)
        self.assertIsNone(overrides.document_type_id)
        self.assertIsNone(overrides.tag_ids)

    def test_upload_with_invalid_correspondent(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f, "correspondent": 3456},
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.consume_file_mock.assert_not_called()

    def test_upload_with_document_type(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        dt = DocumentType.objects.create(name="invoice")
        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f, "document_type": dt.id},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.consume_file_mock.assert_called_once()

        _, overrides = self.get_last_consume_delay_call_args()

        self.assertEqual(overrides.document_type_id, dt.id)
        self.assertIsNone(overrides.correspondent_id)
        self.assertIsNone(overrides.title)
        self.assertIsNone(overrides.tag_ids)

    def test_upload_with_invalid_document_type(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f, "document_type": 34578},
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.consume_file_mock.assert_not_called()

    def test_upload_with_storage_path(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        sp = StoragePath.objects.create(name="invoices")
        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f, "storage_path": sp.id},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.consume_file_mock.assert_called_once()

        _, overrides = self.get_last_consume_delay_call_args()

        self.assertEqual(overrides.storage_path_id, sp.id)
        self.assertIsNone(overrides.correspondent_id)
        self.assertIsNone(overrides.title)
        self.assertIsNone(overrides.tag_ids)

    def test_upload_with_invalid_storage_path(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f, "storage_path": 34578},
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.consume_file_mock.assert_not_called()

    def test_upload_with_tags(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        t1 = Tag.objects.create(name="tag1")
        t2 = Tag.objects.create(name="tag2")
        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f, "tags": [t2.id, t1.id]},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.consume_file_mock.assert_called_once()

        _, overrides = self.get_last_consume_delay_call_args()

        self.assertCountEqual(overrides.tag_ids, [t1.id, t2.id])
        self.assertIsNone(overrides.document_type_id)
        self.assertIsNone(overrides.correspondent_id)
        self.assertIsNone(overrides.title)

    def test_upload_with_invalid_tags(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        t1 = Tag.objects.create(name="tag1")
        t2 = Tag.objects.create(name="tag2")
        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f, "tags": [t2.id, t1.id, 734563]},
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.consume_file_mock.assert_not_called()

    def test_upload_with_created(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        created = datetime.datetime(
            2022,
            5,
            12,
            0,
            0,
            0,
            0,
            tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles"),
        )
        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f, "created": created},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.consume_file_mock.assert_called_once()

        _, overrides = self.get_last_consume_delay_call_args()

        self.assertEqual(overrides.created, created)

    def test_upload_with_asn(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f, "archive_serial_number": 500},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.consume_file_mock.assert_called_once()

        input_doc, overrides = self.get_last_consume_delay_call_args()

        self.assertEqual(input_doc.original_file.name, "simple.pdf")
        self.assertEqual(overrides.filename, "simple.pdf")
        self.assertIsNone(overrides.correspondent_id)
        self.assertIsNone(overrides.document_type_id)
        self.assertIsNone(overrides.tag_ids)
        self.assertEqual(500, overrides.asn)

    def test_upload_with_custom_fields(self):
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        custom_field = CustomField.objects.create(
            name="stringfield",
            data_type=CustomField.FieldDataType.STRING,
        )

        with open(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {
                    "document": f,
                    "custom_fields": [custom_field.id],
                },
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.consume_file_mock.assert_called_once()

        input_doc, overrides = self.get_last_consume_delay_call_args()

        self.assertEqual(input_doc.original_file.name, "simple.pdf")
        self.assertEqual(overrides.filename, "simple.pdf")
        self.assertEqual(overrides.custom_field_ids, [custom_field.id])

    def test_upload_invalid_pdf(self):
        """
        GIVEN: Invalid PDF named "*.pdf" that mime_type is in settings.CONSUMER_PDF_RECOVERABLE_MIME_TYPES
        WHEN: Upload the file
        THEN: The file is not rejected
        """
        self.consume_file_mock.return_value = celery.result.AsyncResult(
            id=str(uuid.uuid4()),
        )

        with open(
            os.path.join(os.path.dirname(__file__), "samples", "invalid_pdf.pdf"),
            "rb",
        ) as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_metadata(self):
        doc = Document.objects.create(
            title="test",
            filename="file.pdf",
            mime_type="image/png",
            archive_checksum="A",
            archive_filename="archive.pdf",
        )

        source_file = os.path.join(
            os.path.dirname(__file__),
            "samples",
            "documents",
            "thumbnails",
            "0000001.webp",
        )
        archive_file = os.path.join(os.path.dirname(__file__), "samples", "simple.pdf")

        shutil.copy(source_file, doc.source_path)
        shutil.copy(archive_file, doc.archive_path)

        response = self.client.get(f"/api/documents/{doc.pk}/metadata/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        meta = response.data

        self.assertEqual(meta["original_mime_type"], "image/png")
        self.assertTrue(meta["has_archive_version"])
        self.assertEqual(len(meta["original_metadata"]), 0)
        self.assertGreater(len(meta["archive_metadata"]), 0)
        self.assertEqual(meta["media_filename"], "file.pdf")
        self.assertEqual(meta["archive_media_filename"], "archive.pdf")
        self.assertEqual(meta["original_size"], os.stat(source_file).st_size)
        self.assertEqual(meta["archive_size"], os.stat(archive_file).st_size)

        response = self.client.get(f"/api/documents/{doc.pk}/metadata/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_metadata_invalid_doc(self):
        response = self.client.get("/api/documents/34576/metadata/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_metadata_no_archive(self):
        doc = Document.objects.create(
            title="test",
            filename="file.pdf",
            mime_type="application/pdf",
        )

        shutil.copy(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            doc.source_path,
        )

        response = self.client.get(f"/api/documents/{doc.pk}/metadata/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        meta = response.data

        self.assertEqual(meta["original_mime_type"], "application/pdf")
        self.assertFalse(meta["has_archive_version"])
        self.assertGreater(len(meta["original_metadata"]), 0)
        self.assertIsNone(meta["archive_metadata"])
        self.assertIsNone(meta["archive_media_filename"])

    def test_get_metadata_missing_files(self):
        doc = Document.objects.create(
            title="test",
            filename="file.pdf",
            mime_type="application/pdf",
            archive_filename="file.pdf",
            archive_checksum="B",
            checksum="A",
        )

        response = self.client.get(f"/api/documents/{doc.pk}/metadata/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        meta = response.data

        self.assertTrue(meta["has_archive_version"])
        self.assertIsNone(meta["original_metadata"])
        self.assertIsNone(meta["original_size"])
        self.assertIsNone(meta["archive_metadata"])
        self.assertIsNone(meta["archive_size"])

    def test_get_empty_suggestions(self):
        doc = Document.objects.create(title="test", mime_type="application/pdf")

        response = self.client.get(f"/api/documents/{doc.pk}/suggestions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "correspondents": [],
                "tags": [],
                "document_types": [],
                "storage_paths": [],
                "dates": [],
            },
        )

    def test_get_suggestions_invalid_doc(self):
        response = self.client.get("/api/documents/34676/suggestions/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @mock.patch("documents.views.match_storage_paths")
    @mock.patch("documents.views.match_document_types")
    @mock.patch("documents.views.match_tags")
    @mock.patch("documents.views.match_correspondents")
    @override_settings(NUMBER_OF_SUGGESTED_DATES=10)
    def test_get_suggestions(
        self,
        match_correspondents,
        match_tags,
        match_document_types,
        match_storage_paths,
    ):
        doc = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is an invoice from 12.04.2022!",
        )

        match_correspondents.return_value = [Correspondent(id=88), Correspondent(id=2)]
        match_tags.return_value = [Tag(id=56), Tag(id=123)]
        match_document_types.return_value = [DocumentType(id=23)]
        match_storage_paths.return_value = [StoragePath(id=99), StoragePath(id=77)]

        response = self.client.get(f"/api/documents/{doc.pk}/suggestions/")
        self.assertEqual(
            response.data,
            {
                "correspondents": [88, 2],
                "tags": [56, 123],
                "document_types": [23],
                "storage_paths": [99, 77],
                "dates": ["2022-04-12"],
            },
        )

    @mock.patch("documents.views.load_classifier")
    @mock.patch("documents.views.match_storage_paths")
    @mock.patch("documents.views.match_document_types")
    @mock.patch("documents.views.match_tags")
    @mock.patch("documents.views.match_correspondents")
    @override_settings(NUMBER_OF_SUGGESTED_DATES=10)
    def test_get_suggestions_cached(
        self,
        match_correspondents,
        match_tags,
        match_document_types,
        match_storage_paths,
        mocked_load,
    ):
        """
        GIVEN:
           - Request for suggestions for a document
        WHEN:
          - Classifier has not been modified
        THEN:
          - Subsequent requests are returned alright
          - ETag and last modified headers are set
        """

        # setup the cache how the classifier does it
        from documents.classifier import DocumentClassifier

        settings.MODEL_FILE.touch()

        classifier_checksum_bytes = b"thisisachecksum"
        classifier_checksum_hex = hexlify(classifier_checksum_bytes).decode()

        # Two loads, so two side effects
        mocked_load.side_effect = [
            mock.Mock(
                last_auto_type_hash=classifier_checksum_bytes,
                FORMAT_VERSION=DocumentClassifier.FORMAT_VERSION,
            ),
            mock.Mock(
                last_auto_type_hash=classifier_checksum_bytes,
                FORMAT_VERSION=DocumentClassifier.FORMAT_VERSION,
            ),
        ]

        last_modified = timezone.now()
        cache.set(CLASSIFIER_MODIFIED_KEY, last_modified, CACHE_50_MINUTES)
        cache.set(CLASSIFIER_HASH_KEY, classifier_checksum_hex, CACHE_50_MINUTES)
        cache.set(
            CLASSIFIER_VERSION_KEY,
            DocumentClassifier.FORMAT_VERSION,
            CACHE_50_MINUTES,
        )

        # Mock the matching
        match_correspondents.return_value = [Correspondent(id=88), Correspondent(id=2)]
        match_tags.return_value = [Tag(id=56), Tag(id=123)]
        match_document_types.return_value = [DocumentType(id=23)]
        match_storage_paths.return_value = [StoragePath(id=99), StoragePath(id=77)]

        doc = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is an invoice from 12.04.2022!",
        )

        response = self.client.get(f"/api/documents/{doc.pk}/suggestions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "correspondents": [88, 2],
                "tags": [56, 123],
                "document_types": [23],
                "storage_paths": [99, 77],
                "dates": ["2022-04-12"],
            },
        )
        self.assertIn("Last-Modified", response.headers)
        self.assertEqual(
            response.headers["Last-Modified"],
            last_modified.strftime("%a, %d %b %Y %H:%M:%S %Z").replace("UTC", "GMT"),
        )
        self.assertIn("ETag", response.headers)
        self.assertEqual(
            response.headers["ETag"],
            f'"{classifier_checksum_hex}:{settings.NUMBER_OF_SUGGESTED_DATES}"',
        )

        response = self.client.get(f"/api/documents/{doc.pk}/suggestions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @mock.patch("documents.parsers.parse_date_generator")
    @override_settings(NUMBER_OF_SUGGESTED_DATES=0)
    def test_get_suggestions_dates_disabled(
        self,
        parse_date_generator,
    ):
        """
        GIVEN:
            - NUMBER_OF_SUGGESTED_DATES = 0 (disables feature)
        WHEN:
            - API request for document suggestions
        THEN:
            - Dont check for suggested dates at all
        """
        doc = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is an invoice from 12.04.2022!",
        )

        self.client.get(f"/api/documents/{doc.pk}/suggestions/")
        self.assertFalse(parse_date_generator.called)

    def test_saved_views(self):
        u1 = User.objects.create_superuser("user1")
        u2 = User.objects.create_superuser("user2")

        v1 = SavedView.objects.create(
            owner=u1,
            name="test1",
            sort_field="",
            show_on_dashboard=False,
            show_in_sidebar=False,
        )
        SavedView.objects.create(
            owner=u2,
            name="test2",
            sort_field="",
            show_on_dashboard=False,
            show_in_sidebar=False,
        )
        SavedView.objects.create(
            owner=u2,
            name="test3",
            sort_field="",
            show_on_dashboard=False,
            show_in_sidebar=False,
        )

        response = self.client.get("/api/saved_views/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        self.assertEqual(
            self.client.get(f"/api/saved_views/{v1.id}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )

        self.client.force_authenticate(user=u1)

        response = self.client.get("/api/saved_views/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

        self.assertEqual(
            self.client.get(f"/api/saved_views/{v1.id}/").status_code,
            status.HTTP_200_OK,
        )

        self.client.force_authenticate(user=u2)

        response = self.client.get("/api/saved_views/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)

        self.assertEqual(
            self.client.get(f"/api/saved_views/{v1.id}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_saved_view_create_update_patch(self):
        User.objects.create_user("user1")

        view = {
            "name": "test",
            "show_on_dashboard": True,
            "show_in_sidebar": True,
            "sort_field": "created2",
            "filter_rules": [{"rule_type": 4, "value": "test"}],
        }

        response = self.client.post("/api/saved_views/", view, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        v1 = SavedView.objects.get(name="test")
        self.assertEqual(v1.sort_field, "created2")
        self.assertEqual(v1.filter_rules.count(), 1)
        self.assertEqual(v1.owner, self.user)

        response = self.client.patch(
            f"/api/saved_views/{v1.id}/",
            {"show_in_sidebar": False},
            format="json",
        )

        v1 = SavedView.objects.get(id=v1.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(v1.show_in_sidebar)
        self.assertEqual(v1.filter_rules.count(), 1)

        view["filter_rules"] = [{"rule_type": 12, "value": "secret"}]

        response = self.client.put(f"/api/saved_views/{v1.id}/", view, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        v1 = SavedView.objects.get(id=v1.id)
        self.assertEqual(v1.filter_rules.count(), 1)
        self.assertEqual(v1.filter_rules.first().value, "secret")

        view["filter_rules"] = []

        response = self.client.put(f"/api/saved_views/{v1.id}/", view, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        v1 = SavedView.objects.get(id=v1.id)
        self.assertEqual(v1.filter_rules.count(), 0)

    def test_saved_view_display_options(self):
        """
        GIVEN:
            - Saved view
        WHEN:
            - Updating display options
        THEN:
            - Display options are updated
            - Display fields are validated
        """
        User.objects.create_user("user1")

        view = {
            "name": "test",
            "show_on_dashboard": True,
            "show_in_sidebar": True,
            "sort_field": "created2",
            "filter_rules": [{"rule_type": 4, "value": "test"}],
            "page_size": 20,
            "display_mode": SavedView.DisplayMode.SMALL_CARDS,
            "display_fields": [
                SavedView.DisplayFields.TITLE,
                SavedView.DisplayFields.CREATED,
            ],
        }

        response = self.client.post("/api/saved_views/", view, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        v1 = SavedView.objects.get(name="test")
        self.assertEqual(v1.page_size, 20)
        self.assertEqual(
            v1.display_mode,
            SavedView.DisplayMode.SMALL_CARDS,
        )
        self.assertEqual(
            v1.display_fields,
            [
                SavedView.DisplayFields.TITLE,
                SavedView.DisplayFields.CREATED,
            ],
        )

        response = self.client.patch(
            f"/api/saved_views/{v1.id}/",
            {
                "display_fields": [
                    SavedView.DisplayFields.TAGS,
                    SavedView.DisplayFields.TITLE,
                    SavedView.DisplayFields.CREATED,
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        v1.refresh_from_db()
        self.assertEqual(
            v1.display_fields,
            [
                SavedView.DisplayFields.TAGS,
                SavedView.DisplayFields.TITLE,
                SavedView.DisplayFields.CREATED,
            ],
        )

        # Invalid display field
        response = self.client.patch(
            f"/api/saved_views/{v1.id}/",
            {
                "display_fields": [
                    "foobar",
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_saved_view_display_customfields(self):
        """
        GIVEN:
            - Saved view
        WHEN:
            - Updating display options with custom fields
        THEN:
            - Display filds for custom fields are updated
            - Display fields for custom fields are validated
        """
        view = {
            "name": "test",
            "show_on_dashboard": True,
            "show_in_sidebar": True,
            "sort_field": "created2",
            "filter_rules": [{"rule_type": 4, "value": "test"}],
            "page_size": 20,
            "display_mode": SavedView.DisplayMode.SMALL_CARDS,
            "display_fields": [
                SavedView.DisplayFields.TITLE,
                SavedView.DisplayFields.CREATED,
            ],
        }

        response = self.client.post("/api/saved_views/", view, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        v1 = SavedView.objects.get(name="test")

        custom_field = CustomField.objects.create(
            name="stringfield",
            data_type=CustomField.FieldDataType.STRING,
        )

        response = self.client.patch(
            f"/api/saved_views/{v1.id}/",
            {
                "display_fields": [
                    SavedView.DisplayFields.TITLE,
                    SavedView.DisplayFields.CREATED,
                    SavedView.DisplayFields.CUSTOM_FIELD % custom_field.id,
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        v1.refresh_from_db()
        self.assertEqual(
            v1.display_fields,
            [
                str(SavedView.DisplayFields.TITLE),
                str(SavedView.DisplayFields.CREATED),
                SavedView.DisplayFields.CUSTOM_FIELD % custom_field.id,
            ],
        )

        # Custom field not found
        response = self.client.patch(
            f"/api/saved_views/{v1.id}/",
            {
                "display_fields": [
                    SavedView.DisplayFields.TITLE,
                    SavedView.DisplayFields.CREATED,
                    SavedView.DisplayFields.CUSTOM_FIELD % 99,
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_logs(self):
        log_data = "test\ntest2\n"
        with open(os.path.join(settings.LOGGING_DIR, "mail.log"), "w") as f:
            f.write(log_data)
        with open(os.path.join(settings.LOGGING_DIR, "paperless.log"), "w") as f:
            f.write(log_data)
        response = self.client.get("/api/logs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.data, ["mail", "paperless"])

    def test_get_logs_only_when_exist(self):
        log_data = "test\ntest2\n"
        with open(os.path.join(settings.LOGGING_DIR, "paperless.log"), "w") as f:
            f.write(log_data)
        response = self.client.get("/api/logs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.data, ["paperless"])

    def test_get_invalid_log(self):
        response = self.client.get("/api/logs/bogus_log/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(LOGGING_DIR="bogus_dir")
    def test_get_nonexistent_log(self):
        response = self.client.get("/api/logs/paperless/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_log(self):
        log_data = "test\ntest2\n"
        with open(os.path.join(settings.LOGGING_DIR, "paperless.log"), "w") as f:
            f.write(log_data)
        response = self.client.get("/api/logs/paperless/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertListEqual(response.data, ["test", "test2"])

    def test_invalid_regex_other_algorithm(self):
        for endpoint in ["correspondents", "tags", "document_types"]:
            response = self.client.post(
                f"/api/{endpoint}/",
                {
                    "name": "test",
                    "matching_algorithm": MatchingModel.MATCH_ANY,
                    "match": "[",
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, endpoint)

    def test_invalid_regex(self):
        for endpoint in ["correspondents", "tags", "document_types"]:
            response = self.client.post(
                f"/api/{endpoint}/",
                {
                    "name": "test",
                    "matching_algorithm": MatchingModel.MATCH_REGEX,
                    "match": "[",
                },
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                endpoint,
            )

    def test_valid_regex(self):
        for endpoint in ["correspondents", "tags", "document_types"]:
            response = self.client.post(
                f"/api/{endpoint}/",
                {
                    "name": "test",
                    "matching_algorithm": MatchingModel.MATCH_REGEX,
                    "match": "[0-9]",
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, endpoint)

    def test_regex_no_algorithm(self):
        for endpoint in ["correspondents", "tags", "document_types"]:
            response = self.client.post(
                f"/api/{endpoint}/",
                {"name": "test", "match": "[0-9]"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, endpoint)

    def test_tag_color_default(self):
        response = self.client.post("/api/tags/", {"name": "tag"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Tag.objects.get(id=response.data["id"]).color, "#a6cee3")
        self.assertEqual(
            self.client.get(f"/api/tags/{response.data['id']}/", format="json").data[
                "colour"
            ],
            1,
        )

    def test_tag_color(self):
        response = self.client.post(
            "/api/tags/",
            {"name": "tag", "colour": 3},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Tag.objects.get(id=response.data["id"]).color, "#b2df8a")
        self.assertEqual(
            self.client.get(f"/api/tags/{response.data['id']}/", format="json").data[
                "colour"
            ],
            3,
        )

    def test_tag_color_invalid(self):
        response = self.client.post(
            "/api/tags/",
            {"name": "tag", "colour": 34},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_tag_color_custom(self):
        tag = Tag.objects.create(name="test", color="#abcdef")
        self.assertEqual(
            self.client.get(f"/api/tags/{tag.id}/", format="json").data["colour"],
            1,
        )

    def test_get_existing_notes(self):
        """
        GIVEN:
            - A document with a single note
        WHEN:
            - API request for document notes is made
        THEN:
            - The associated note is returned
        """
        doc = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is a document which will have notes!",
        )
        note = Note.objects.create(
            note="This is a note.",
            document=doc,
            user=self.user,
        )

        response = self.client.get(
            f"/api/documents/{doc.pk}/notes/",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        resp_data = response.json()

        self.assertEqual(len(resp_data), 1)

        resp_data = resp_data[0]
        del resp_data["created"]

        self.assertDictEqual(
            resp_data,
            {
                "id": note.id,
                "note": note.note,
                "user": {
                    "id": note.user.id,
                    "username": note.user.username,
                    "first_name": note.user.first_name,
                    "last_name": note.user.last_name,
                },
            },
        )

    def test_create_note(self):
        """
        GIVEN:
            - Existing document
        WHEN:
            - API request is made to add a note
        THEN:
            - note is created and associated with document, modified time is updated
        """
        doc = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is a document which will have notes added",
            created=timezone.now() - timedelta(days=1),
        )
        # set to yesterday
        doc.modified = timezone.now() - timedelta(days=1)
        self.assertEqual(doc.modified.day, (timezone.now() - timedelta(days=1)).day)

        resp = self.client.post(
            f"/api/documents/{doc.pk}/notes/",
            data={"note": "this is a posted note"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        response = self.client.get(
            f"/api/documents/{doc.pk}/notes/",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        resp_data = response.json()

        self.assertEqual(len(resp_data), 1)

        resp_data = resp_data[0]

        self.assertEqual(resp_data["note"], "this is a posted note")

        doc = Document.objects.get(pk=doc.pk)
        # modified was updated to today
        self.assertEqual(doc.modified.day, timezone.now().day)

    def test_notes_permissions_aware(self):
        """
        GIVEN:
            - Existing document owned by user2 but with granted view perms for user1
        WHEN:
            - API request is made by user1 to add a note or delete
        THEN:
            - Notes are neither created nor deleted
        """
        user1 = User.objects.create_user(username="test1")
        user1.user_permissions.add(*Permission.objects.all())
        user1.save()

        user2 = User.objects.create_user(username="test2")
        user2.save()

        doc = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is a document which will have notes added",
        )
        doc.owner = user2
        doc.save()

        self.client.force_authenticate(user1)

        resp = self.client.get(
            f"/api/documents/{doc.pk}/notes/",
            format="json",
        )
        self.assertEqual(resp.content, b"Insufficient permissions to view notes")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        assign_perm("view_document", user1, doc)

        resp = self.client.post(
            f"/api/documents/{doc.pk}/notes/",
            data={"note": "this is a posted note"},
        )
        self.assertEqual(resp.content, b"Insufficient permissions to create notes")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        note = Note.objects.create(
            note="This is a note.",
            document=doc,
            user=user2,
        )

        response = self.client.delete(
            f"/api/documents/{doc.pk}/notes/?id={note.pk}",
            format="json",
        )

        self.assertEqual(response.content, b"Insufficient permissions to delete notes")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_note(self):
        """
        GIVEN:
            - Existing document, existing note
        WHEN:
            - API request is made to delete a note
        THEN:
            - note is deleted, document modified is updated
        """
        doc = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is a document which will have notes!",
            created=timezone.now() - timedelta(days=1),
        )
        # set to yesterday
        doc.modified = timezone.now() - timedelta(days=1)
        self.assertEqual(doc.modified.day, (timezone.now() - timedelta(days=1)).day)
        note = Note.objects.create(
            note="This is a note.",
            document=doc,
            user=self.user,
        )

        response = self.client.delete(
            f"/api/documents/{doc.pk}/notes/?id={note.pk}",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(Note.objects.all()), 0)
        doc = Document.objects.get(pk=doc.pk)
        # modified was updated to today
        self.assertEqual(doc.modified.day, timezone.now().day)

    def test_get_notes_no_doc(self):
        """
        GIVEN:
            - A request to get notes from a non-existent document
        WHEN:
            - API request for document notes is made
        THEN:
            - HTTP status.HTTP_404_NOT_FOUND is returned
        """
        response = self.client.get(
            "/api/documents/500/notes/",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_tag_unique_name_and_owner(self):
        """
        GIVEN:
            - Multiple users
            - Tags owned by particular users
        WHEN:
            - API request for creating items which are unique by name and owner
        THEN:
            - Unique items are created
            - Non-unique items are not allowed
        """
        user1 = User.objects.create_user(username="test1")
        user1.user_permissions.add(*Permission.objects.filter(codename="add_tag"))
        user1.save()

        user2 = User.objects.create_user(username="test2")
        user2.user_permissions.add(*Permission.objects.filter(codename="add_tag"))
        user2.save()

        # User 1 creates tag 1 owned by user 1 by default
        # No issue
        self.client.force_authenticate(user1)
        response = self.client.post("/api/tags/", {"name": "tag 1"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # User 2 creates tag 1 owned by user 2 by default
        # No issue
        self.client.force_authenticate(user2)
        response = self.client.post("/api/tags/", {"name": "tag 1"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # User 2 creates tag 2 owned by user 1
        # No issue
        self.client.force_authenticate(user2)
        response = self.client.post(
            "/api/tags/",
            {"name": "tag 2", "owner": user1.pk},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # User 1 creates tag 2 owned by user 1 by default
        # Not allowed, would create tag2/user1 which already exists
        self.client.force_authenticate(user1)
        response = self.client.post(
            "/api/tags/",
            {"name": "tag 2"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # User 1 creates tag 2 owned by user 1
        # Not allowed, would create tag2/user1 which already exists
        response = self.client.post(
            "/api/tags/",
            {"name": "tag 2", "owner": user1.pk},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_tag_unique_name_and_owner_enforced_on_update(self):
        """
        GIVEN:
            - Multiple users
            - Tags owned by particular users
        WHEN:
            - API request for to update tag in such as way as makes it non-unqiue
        THEN:
            - Unique items are created
            - Non-unique items are not allowed on update
        """
        user1 = User.objects.create_user(username="test1")
        user1.user_permissions.add(*Permission.objects.filter(codename="change_tag"))
        user1.save()

        user2 = User.objects.create_user(username="test2")
        user2.user_permissions.add(*Permission.objects.filter(codename="change_tag"))
        user2.save()

        # Create name tag 1 owned by user 1
        # Create name tag 1 owned by user 2
        Tag.objects.create(name="tag 1", owner=user1)
        tag2 = Tag.objects.create(name="tag 1", owner=user2)

        # User 2 attempts to change the owner of tag to user 1
        # Not allowed, would change to tag1/user1 which already exists
        self.client.force_authenticate(user2)
        response = self.client.patch(
            f"/api/tags/{tag2.id}/",
            {"owner": user1.pk},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_share_links(self):
        """
        GIVEN:
            - Existing document
        WHEN:
            - API request is made to generate a share_link
            - API request is made to view share_links on incorrect doc pk
            - Invalid method request is made to view share_links doc
        THEN:
            - Link is created with a slug and associated with document
            - 404
            - Error
        """
        doc = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is a document which will have notes added",
        )
        # never expires
        resp = self.client.post(
            "/api/share_links/",
            data={
                "document": doc.pk,
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        resp = self.client.post(
            "/api/share_links/",
            data={
                "expiration": (timezone.now() + timedelta(days=7)).isoformat(),
                "document": doc.pk,
                "file_version": "original",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        response = self.client.get(
            f"/api/documents/{doc.pk}/share_links/",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        resp_data = response.json()

        self.assertEqual(len(resp_data), 2)

        self.assertGreater(len(resp_data[1]["slug"]), 0)
        self.assertIsNone(resp_data[1]["expiration"])
        self.assertEqual(
            (parser.isoparse(resp_data[0]["expiration"]) - timezone.now()).days,
            6,
        )

        sl1 = ShareLink.objects.get(slug=resp_data[1]["slug"])
        self.assertEqual(str(sl1), f"Share Link for {doc.title}")

        response = self.client.post(
            f"/api/documents/{doc.pk}/share_links/",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client.get(
            "/api/documents/99/share_links/",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_share_links_permissions_aware(self):
        """
        GIVEN:
            - Existing document owned by user2 but with granted view perms for user1
        WHEN:
            - API request is made by user1 to view share links
        THEN:
            - Links only shown if user has permissions
        """
        user1 = User.objects.create_user(username="test1")
        user1.user_permissions.add(*Permission.objects.all())
        user1.save()

        user2 = User.objects.create_user(username="test2")
        user2.save()

        doc = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is a document which will have share links added",
        )
        doc.owner = user2
        doc.save()

        self.client.force_authenticate(user1)

        resp = self.client.get(
            f"/api/documents/{doc.pk}/share_links/",
            format="json",
        )
        self.assertEqual(resp.content, b"Insufficient permissions to add share link")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        assign_perm("change_document", user1, doc)

        resp = self.client.get(
            f"/api/documents/{doc.pk}/share_links/",
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_next_asn(self):
        """
        GIVEN:
            - Existing documents with ASNs, highest owned by user2
        WHEN:
            - API request is made by user1 to get next ASN
        THEN:
            - ASN +1 from user2's doc is returned for user1
        """
        user1 = User.objects.create_user(username="test1")
        user1.user_permissions.add(*Permission.objects.all())
        user1.save()

        user2 = User.objects.create_user(username="test2")
        user2.save()

        doc1 = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is a document 1",
            checksum="1",
            archive_serial_number=998,
        )
        doc1.owner = user1
        doc1.save()

        doc2 = Document.objects.create(
            title="test2",
            mime_type="application/pdf",
            content="this is a document 2 with higher ASN",
            checksum="2",
            archive_serial_number=999,
        )
        doc2.owner = user2
        doc2.save()

        self.client.force_authenticate(user1)

        resp = self.client.get(
            "/api/documents/next_asn/",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.content, b"1000")

    def test_next_asn_no_documents_with_asn(self):
        """
        GIVEN:
            - Existing document, but with no ASN assugned
        WHEN:
            - API request to get next ASN
        THEN:
            - ASN 1 is returned
        """
        user1 = User.objects.create_user(username="test1")
        user1.user_permissions.add(*Permission.objects.all())
        user1.save()

        doc1 = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is a document 1",
            checksum="1",
        )
        doc1.save()

        self.client.force_authenticate(user1)

        resp = self.client.get(
            "/api/documents/next_asn/",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.content, b"1")

    def test_asn_not_unique_with_trashed_doc(self):
        """
        GIVEN:
            - Existing document with ASN that is trashed
        WHEN:
            - API request to update document with same ASN
        THEN:
            - Explicit error is returned
        """
        user1 = User.objects.create_superuser(username="test1")

        self.client.force_authenticate(user1)

        doc1 = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is a document 1",
            checksum="1",
            archive_serial_number=1,
        )
        doc1.delete()

        doc2 = Document.objects.create(
            title="test2",
            mime_type="application/pdf",
            content="this is a document 2",
            checksum="2",
        )
        result = self.client.patch(
            f"/api/documents/{doc2.pk}/",
            {
                "archive_serial_number": 1,
            },
        )
        self.assertEqual(result.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            result.json(),
            {
                "archive_serial_number": [
                    "Document with this Archive Serial Number already exists in the trash.",
                ],
            },
        )

    def test_remove_inbox_tags(self):
        """
        GIVEN:
            - Existing document with or without inbox tags
        WHEN:
            - API request to update document, with or without `remove_inbox_tags` flag
        THEN:
            - Inbox tags are removed as long as they are not being added
        """
        tag1 = Tag.objects.create(name="tag1", color="#abcdef")
        inbox_tag1 = Tag.objects.create(
            name="inbox1",
            color="#abcdef",
            is_inbox_tag=True,
        )
        inbox_tag2 = Tag.objects.create(
            name="inbox2",
            color="#abcdef",
            is_inbox_tag=True,
        )

        doc1 = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is a document 1",
            checksum="1",
        )
        doc1.tags.add(tag1)
        doc1.tags.add(inbox_tag1)
        doc1.tags.add(inbox_tag2)
        doc1.save()

        # Remove inbox tags defaults to false
        resp = self.client.patch(
            f"/api/documents/{doc1.pk}/",
            {
                "title": "New title",
            },
        )
        doc1.refresh_from_db()
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(doc1.tags.count(), 3)

        # Remove inbox tags set to true
        resp = self.client.patch(
            f"/api/documents/{doc1.pk}/",
            {
                "remove_inbox_tags": True,
            },
        )
        doc1.refresh_from_db()
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(doc1.tags.count(), 1)

        # Remove inbox tags set to true but adding a new inbox tag
        resp = self.client.patch(
            f"/api/documents/{doc1.pk}/",
            {
                "remove_inbox_tags": True,
                "tags": [inbox_tag1.pk, tag1.pk],
            },
        )
        doc1.refresh_from_db()
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(doc1.tags.count(), 2)

    @override_settings(
        EMAIL_ENABLED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_email_document(self):
        """
        GIVEN:
            - Existing document
        WHEN:
            - API request is made to email document action
        THEN:
            - Email is sent, with document (original or archive) attached
        """
        doc = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is a document 1",
            checksum="1",
            filename="test.pdf",
            archive_checksum="A",
            archive_filename="archive.pdf",
        )
        doc2 = Document.objects.create(
            title="test2",
            mime_type="application/pdf",
            content="this is a document 2",
            checksum="2",
            filename="test2.pdf",
        )

        archive_file = os.path.join(os.path.dirname(__file__), "samples", "simple.pdf")
        source_file = os.path.join(os.path.dirname(__file__), "samples", "simple.pdf")

        shutil.copy(archive_file, doc.archive_path)
        shutil.copy(source_file, doc2.source_path)

        self.client.post(
            f"/api/documents/{doc.pk}/email/",
            {
                "addresses": "hello@paperless-ngx.com",
                "subject": "test",
                "message": "hello",
            },
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].attachments[0][0], "archive.pdf")

        self.client.post(
            f"/api/documents/{doc2.pk}/email/",
            {
                "addresses": "hello@paperless-ngx.com",
                "subject": "test",
                "message": "hello",
                "use_archive_version": False,
            },
        )

        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].attachments[0][0], "test2.pdf")

    @mock.patch("django.core.mail.message.EmailMessage.send", side_effect=Exception)
    def test_email_document_errors(self, mocked_send):
        """
        GIVEN:
            - Existing document
        WHEN:
            - API request is made to email document action with insufficient permissions
            - API request is made to email document action with invalid document id
            - API request is made to email document action with missing data
            - API request is made to email document action with invalid email address
            - API request is made to email document action and error occurs during email send
        THEN:
            - Error response is returned
        """
        user1 = User.objects.create_user(username="test1")
        user1.user_permissions.add(*Permission.objects.all())
        user1.save()

        doc = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is a document 1",
            checksum="1",
            filename="test.pdf",
            archive_checksum="A",
            archive_filename="archive.pdf",
        )

        doc2 = Document.objects.create(
            title="test2",
            mime_type="application/pdf",
            content="this is a document 2",
            checksum="2",
            owner=self.user,
        )

        self.client.force_authenticate(user1)

        resp = self.client.post(
            f"/api/documents/{doc2.pk}/email/",
            {
                "addresses": "hello@paperless-ngx.com",
                "subject": "test",
                "message": "hello",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        resp = self.client.post(
            "/api/documents/999/email/",
            {
                "addresses": "hello@paperless-ngx.com",
                "subject": "test",
                "message": "hello",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

        resp = self.client.post(
            f"/api/documents/{doc.pk}/email/",
            {
                "addresses": "hello@paperless-ngx.com",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        resp = self.client.post(
            f"/api/documents/{doc.pk}/email/",
            {
                "addresses": "hello@paperless-ngx.com,hello",
                "subject": "test",
                "message": "hello",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        resp = self.client.post(
            f"/api/documents/{doc.pk}/email/",
            {
                "addresses": "hello@paperless-ngx.com",
                "subject": "test",
                "message": "hello",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    @mock.patch("django_softdelete.models.SoftDeleteModel.delete")
    def test_warn_on_delete_with_old_uuid_field(self, mocked_delete):
        """
        GIVEN:
            - Existing document in a (mocked) MariaDB database with an old UUID field
        WHEN:
            - API request to delete document is made which raises "Data too long for column" error
        THEN:
            - Warning is logged alerting the user of the issue (and link to the fix)
        """

        doc = Document.objects.create(
            title="test",
            mime_type="application/pdf",
            content="this is a document 1",
            checksum="1",
        )

        mocked_delete.side_effect = DataError(
            "Data too long for column 'transaction_id' at row 1",
        )

        with self.assertLogs(level="WARNING") as cm:
            self.client.delete(f"/api/documents/{doc.pk}/")
            self.assertIn(
                "Detected a possible incompatible database column",
                cm.output[0],
            )


class TestDocumentApiV2(DirectoriesMixin, APITestCase):
    def setUp(self):
        super().setUp()

        self.user = User.objects.create_superuser(username="temp_admin")

        self.client.force_authenticate(user=self.user)
        self.client.defaults["HTTP_ACCEPT"] = "application/json; version=2"

    def test_tag_validate_color(self):
        self.assertEqual(
            self.client.post(
                "/api/tags/",
                {"name": "test", "color": "#12fFaA"},
                format="json",
            ).status_code,
            status.HTTP_201_CREATED,
        )

        self.assertEqual(
            self.client.post(
                "/api/tags/",
                {"name": "test1", "color": "abcdef"},
                format="json",
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                "/api/tags/",
                {"name": "test2", "color": "#abcdfg"},
                format="json",
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                "/api/tags/",
                {"name": "test3", "color": "#asd"},
                format="json",
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                "/api/tags/",
                {"name": "test4", "color": "#12121212"},
                format="json",
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_tag_text_color(self):
        t = Tag.objects.create(name="tag1", color="#000000")
        self.assertEqual(
            self.client.get(f"/api/tags/{t.id}/", format="json").data["text_color"],
            "#ffffff",
        )

        t.color = "#ffffff"
        t.save()
        self.assertEqual(
            self.client.get(f"/api/tags/{t.id}/", format="json").data["text_color"],
            "#000000",
        )

        t.color = "asdf"
        t.save()
        self.assertEqual(
            self.client.get(f"/api/tags/{t.id}/", format="json").data["text_color"],
            "#000000",
        )

        t.color = "123"
        t.save()
        self.assertEqual(
            self.client.get(f"/api/tags/{t.id}/", format="json").data["text_color"],
            "#000000",
        )


class TestDocumentApiCustomFieldsSorting(DirectoriesMixin, APITestCase):
    def setUp(self):
        super().setUp()

        self.user = User.objects.create_superuser(username="temp_admin")
        self.client.force_authenticate(user=self.user)

        self.doc1 = Document.objects.create(
            title="none1",
            checksum="A",
            mime_type="application/pdf",
        )
        self.doc2 = Document.objects.create(
            title="none2",
            checksum="B",
            mime_type="application/pdf",
        )
        self.doc3 = Document.objects.create(
            title="none3",
            checksum="C",
            mime_type="application/pdf",
        )

        cache.clear()

    def test_document_custom_fields_sorting(self):
        """
        GIVEN:
            - Documents with custom fields
        WHEN:
            - API request for document filtering with custom field sorting
        THEN:
            - Documents are sorted by custom field values
        """
        values = {
            CustomField.FieldDataType.STRING: {
                "values": ["foo", "bar", "baz"],
                "field_name": CustomFieldInstance.TYPE_TO_DATA_STORE_NAME_MAP[
                    CustomField.FieldDataType.STRING
                ],
            },
            CustomField.FieldDataType.INT: {
                "values": [3, 1, 2],
                "field_name": CustomFieldInstance.TYPE_TO_DATA_STORE_NAME_MAP[
                    CustomField.FieldDataType.INT
                ],
            },
            CustomField.FieldDataType.FLOAT: {
                "values": [3.3, 1.1, 2.2],
                "field_name": CustomFieldInstance.TYPE_TO_DATA_STORE_NAME_MAP[
                    CustomField.FieldDataType.FLOAT
                ],
            },
            CustomField.FieldDataType.BOOL: {
                "values": [True, False, False],
                "field_name": CustomFieldInstance.TYPE_TO_DATA_STORE_NAME_MAP[
                    CustomField.FieldDataType.BOOL
                ],
            },
            CustomField.FieldDataType.DATE: {
                "values": [date(2021, 1, 3), date(2021, 1, 1), date(2021, 1, 2)],
                "field_name": CustomFieldInstance.TYPE_TO_DATA_STORE_NAME_MAP[
                    CustomField.FieldDataType.DATE
                ],
            },
            CustomField.FieldDataType.URL: {
                "values": [
                    "http://example.org",
                    "http://example.com",
                    "http://example.net",
                ],
                "field_name": CustomFieldInstance.TYPE_TO_DATA_STORE_NAME_MAP[
                    CustomField.FieldDataType.URL
                ],
            },
            CustomField.FieldDataType.MONETARY: {
                "values": ["USD789.00", "USD123.00", "USD456.00"],
                "field_name": CustomFieldInstance.TYPE_TO_DATA_STORE_NAME_MAP[
                    CustomField.FieldDataType.MONETARY
                ],
            },
            CustomField.FieldDataType.DOCUMENTLINK: {
                "values": [self.doc3.pk, self.doc1.pk, self.doc2.pk],
                "field_name": CustomFieldInstance.TYPE_TO_DATA_STORE_NAME_MAP[
                    CustomField.FieldDataType.DOCUMENTLINK
                ],
            },
            CustomField.FieldDataType.SELECT: {
                "values": ["ghi-789", "abc-123", "def-456"],
                "field_name": CustomFieldInstance.TYPE_TO_DATA_STORE_NAME_MAP[
                    CustomField.FieldDataType.SELECT
                ],
                "extra_data": {
                    "select_options": [
                        {"label": "Option 1", "id": "abc-123"},
                        {"label": "Option 2", "id": "def-456"},
                        {"label": "Option 3", "id": "ghi-789"},
                    ],
                },
            },
        }

        for data_type, data in values.items():
            CustomField.objects.all().delete()
            CustomFieldInstance.objects.all().delete()
            custom_field = CustomField.objects.create(
                name=f"custom field {data_type}",
                data_type=data_type,
                extra_data=data.get("extra_data", {}),
            )
            for i, value in enumerate(data["values"]):
                CustomFieldInstance.objects.create(
                    document=[self.doc1, self.doc2, self.doc3][i],
                    field=custom_field,
                    **{data["field_name"]: value},
                )
            response = self.client.get(
                f"/api/documents/?ordering=custom_field_{custom_field.pk}",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            results = response.data["results"]
            self.assertEqual(len(results), 3)
            self.assertEqual(
                [results[0]["id"], results[1]["id"], results[2]["id"]],
                [self.doc2.id, self.doc3.id, self.doc1.id],
            )

            response = self.client.get(
                f"/api/documents/?ordering=-custom_field_{custom_field.pk}",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            results = response.data["results"]
            self.assertEqual(len(results), 3)
            if data_type == CustomField.FieldDataType.BOOL:
                # just check the first one for bools, as the rest are the same
                self.assertEqual(
                    [results[0]["id"]],
                    [self.doc1.id],
                )
            else:
                self.assertEqual(
                    [results[0]["id"], results[1]["id"], results[2]["id"]],
                    [self.doc1.id, self.doc3.id, self.doc2.id],
                )

    def test_document_custom_fields_sorting_invalid(self):
        """
        GIVEN:
            - Documents with custom fields
        WHEN:
            - API request for document filtering with invalid custom field sorting
        THEN:
            - 400 is returned
        """

        response = self.client.get(
            "/api/documents/?ordering=custom_field_999",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_document_custom_fields_sorting_invalid_data_type(self):
        """
        GIVEN:
            - Documents with custom fields
        WHEN:
            - API request for document filtering with a custom field sorting with a new (unhandled) data type
        THEN:
            - Error is raised
        """

        custom_field = CustomField.objects.create(
            name="custom field",
            data_type="foo",
        )

        with self.assertRaises(ValueError):
            self.client.get(
                f"/api/documents/?ordering=custom_field_{custom_field.pk}",
            )
