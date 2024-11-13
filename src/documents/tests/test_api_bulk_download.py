import datetime
import io
import json
import os
import shutil
import zipfile

from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from documents.models import Correspondent
from documents.models import Document
from documents.models import DocumentType
from documents.tests.utils import DirectoriesMixin


class TestBulkDownload(DirectoriesMixin, APITestCase):
    ENDPOINT = "/api/documents/bulk_download/"

    def setUp(self):
        super().setUp()

        self.user = User.objects.create_superuser(username="temp_admin")
        self.client.force_authenticate(user=self.user)

        self.doc1 = Document.objects.create(title="unrelated", checksum="A")
        self.doc2 = Document.objects.create(
            title="document A",
            filename="docA.pdf",
            mime_type="application/pdf",
            checksum="B",
            created=timezone.make_aware(datetime.datetime(2021, 1, 1)),
        )
        self.doc2b = Document.objects.create(
            title="document A",
            filename="docA2.pdf",
            mime_type="application/pdf",
            checksum="D",
            created=timezone.make_aware(datetime.datetime(2021, 1, 1)),
        )
        self.doc3 = Document.objects.create(
            title="document B",
            filename="docB.jpg",
            mime_type="image/jpeg",
            checksum="C",
            created=timezone.make_aware(datetime.datetime(2020, 3, 21)),
            archive_filename="docB.pdf",
            archive_checksum="D",
        )

        shutil.copy(
            os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"),
            self.doc2.source_path,
        )
        shutil.copy(
            os.path.join(os.path.dirname(__file__), "samples", "simple.png"),
            self.doc2b.source_path,
        )
        shutil.copy(
            os.path.join(os.path.dirname(__file__), "samples", "simple.jpg"),
            self.doc3.source_path,
        )
        shutil.copy(
            os.path.join(os.path.dirname(__file__), "samples", "test_with_bom.pdf"),
            self.doc3.archive_path,
        )

    def test_download_originals(self):
        response = self.client.post(
            self.ENDPOINT,
            json.dumps(
                {"documents": [self.doc2.id, self.doc3.id], "content": "originals"},
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/zip")

        with zipfile.ZipFile(io.BytesIO(response.getvalue())) as zipf:
            self.assertEqual(len(zipf.filelist), 2)
            self.assertIn("2021-01-01 document A.pdf", zipf.namelist())
            self.assertIn("2020-03-21 document B.jpg", zipf.namelist())

            with self.doc2.source_file as f:
                self.assertEqual(f.read(), zipf.read("2021-01-01 document A.pdf"))

            with self.doc3.source_file as f:
                self.assertEqual(f.read(), zipf.read("2020-03-21 document B.jpg"))

    def test_download_default(self):
        response = self.client.post(
            self.ENDPOINT,
            json.dumps({"documents": [self.doc2.id, self.doc3.id]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/zip")

        with zipfile.ZipFile(io.BytesIO(response.getvalue())) as zipf:
            self.assertEqual(len(zipf.filelist), 2)
            self.assertIn("2021-01-01 document A.pdf", zipf.namelist())
            self.assertIn("2020-03-21 document B.pdf", zipf.namelist())

            with self.doc2.source_file as f:
                self.assertEqual(f.read(), zipf.read("2021-01-01 document A.pdf"))

            with self.doc3.archive_file as f:
                self.assertEqual(f.read(), zipf.read("2020-03-21 document B.pdf"))

    def test_download_both(self):
        response = self.client.post(
            self.ENDPOINT,
            json.dumps({"documents": [self.doc2.id, self.doc3.id], "content": "both"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/zip")

        with zipfile.ZipFile(io.BytesIO(response.getvalue())) as zipf:
            self.assertEqual(len(zipf.filelist), 3)
            self.assertIn("originals/2021-01-01 document A.pdf", zipf.namelist())
            self.assertIn("archive/2020-03-21 document B.pdf", zipf.namelist())
            self.assertIn("originals/2020-03-21 document B.jpg", zipf.namelist())

            with self.doc2.source_file as f:
                self.assertEqual(
                    f.read(),
                    zipf.read("originals/2021-01-01 document A.pdf"),
                )

            with self.doc3.archive_file as f:
                self.assertEqual(
                    f.read(),
                    zipf.read("archive/2020-03-21 document B.pdf"),
                )

            with self.doc3.source_file as f:
                self.assertEqual(
                    f.read(),
                    zipf.read("originals/2020-03-21 document B.jpg"),
                )

    def test_filename_clashes(self):
        response = self.client.post(
            self.ENDPOINT,
            json.dumps({"documents": [self.doc2.id, self.doc2b.id]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/zip")

        with zipfile.ZipFile(io.BytesIO(response.getvalue())) as zipf:
            self.assertEqual(len(zipf.filelist), 2)

            self.assertIn("2021-01-01 document A.pdf", zipf.namelist())
            self.assertIn("2021-01-01 document A_01.pdf", zipf.namelist())

            with self.doc2.source_file as f:
                self.assertEqual(f.read(), zipf.read("2021-01-01 document A.pdf"))

            with self.doc2b.source_file as f:
                self.assertEqual(f.read(), zipf.read("2021-01-01 document A_01.pdf"))

    def test_compression(self):
        self.client.post(
            self.ENDPOINT,
            json.dumps(
                {"documents": [self.doc2.id, self.doc2b.id], "compression": "lzma"},
            ),
            content_type="application/json",
        )

    @override_settings(FILENAME_FORMAT="{correspondent}/{title}")
    def test_formatted_download_originals(self):
        """
        GIVEN:
            - Defined file naming format
        WHEN:
            - Bulk download request for original documents
            - Bulk download request requests to follow format
        THEN:
            - Files in resulting zipfile are formatted
        """

        c = Correspondent.objects.create(name="test")
        c2 = Correspondent.objects.create(name="a space name")

        self.doc2.correspondent = c
        self.doc2.title = "This is Doc 2"
        self.doc2.save()

        self.doc3.correspondent = c2
        self.doc3.title = "Title 2 - Doc 3"
        self.doc3.save()

        response = self.client.post(
            self.ENDPOINT,
            json.dumps(
                {
                    "documents": [self.doc2.id, self.doc3.id],
                    "content": "originals",
                    "follow_formatting": True,
                },
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/zip")

        with zipfile.ZipFile(io.BytesIO(response.getvalue())) as zipf:
            self.assertEqual(len(zipf.filelist), 2)
            self.assertIn("a space name/Title 2 - Doc 3.jpg", zipf.namelist())
            self.assertIn("test/This is Doc 2.pdf", zipf.namelist())

            with self.doc2.source_file as f:
                self.assertEqual(f.read(), zipf.read("test/This is Doc 2.pdf"))

            with self.doc3.source_file as f:
                self.assertEqual(
                    f.read(),
                    zipf.read("a space name/Title 2 - Doc 3.jpg"),
                )

    @override_settings(FILENAME_FORMAT="somewhere/{title}")
    def test_formatted_download_archive(self):
        """
        GIVEN:
            - Defined file naming format
        WHEN:
            - Bulk download request for archive documents
            - Bulk download request requests to follow format
        THEN:
            - Files in resulting zipfile are formatted
        """

        self.doc2.title = "This is Doc 2"
        self.doc2.save()

        self.doc3.title = "Title 2 - Doc 3"
        self.doc3.save()

        response = self.client.post(
            self.ENDPOINT,
            json.dumps(
                {
                    "documents": [self.doc2.id, self.doc3.id],
                    "follow_formatting": True,
                },
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/zip")

        with zipfile.ZipFile(io.BytesIO(response.getvalue())) as zipf:
            self.assertEqual(len(zipf.filelist), 2)
            self.assertIn("somewhere/This is Doc 2.pdf", zipf.namelist())
            self.assertIn("somewhere/Title 2 - Doc 3.pdf", zipf.namelist())

            with self.doc2.source_file as f:
                self.assertEqual(f.read(), zipf.read("somewhere/This is Doc 2.pdf"))

            with self.doc3.archive_file as f:
                self.assertEqual(f.read(), zipf.read("somewhere/Title 2 - Doc 3.pdf"))

    @override_settings(FILENAME_FORMAT="{document_type}/{title}")
    def test_formatted_download_both(self):
        """
        GIVEN:
            - Defined file naming format
        WHEN:
            - Bulk download request for original documents and archive documents
            - Bulk download request requests to follow format
        THEN:
            - Files defined in resulting zipfile are formatted
        """

        dc1 = DocumentType.objects.create(name="bill")
        dc2 = DocumentType.objects.create(name="statement")

        self.doc2.document_type = dc1
        self.doc2.title = "This is Doc 2"
        self.doc2.save()

        self.doc3.document_type = dc2
        self.doc3.title = "Title 2 - Doc 3"
        self.doc3.save()

        response = self.client.post(
            self.ENDPOINT,
            json.dumps(
                {
                    "documents": [self.doc2.id, self.doc3.id],
                    "content": "both",
                    "follow_formatting": True,
                },
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/zip")

        with zipfile.ZipFile(io.BytesIO(response.getvalue())) as zipf:
            self.assertEqual(len(zipf.filelist), 3)
            self.assertIn("originals/bill/This is Doc 2.pdf", zipf.namelist())
            self.assertIn("archive/statement/Title 2 - Doc 3.pdf", zipf.namelist())
            self.assertIn("originals/statement/Title 2 - Doc 3.jpg", zipf.namelist())

            with self.doc2.source_file as f:
                self.assertEqual(
                    f.read(),
                    zipf.read("originals/bill/This is Doc 2.pdf"),
                )

            with self.doc3.archive_file as f:
                self.assertEqual(
                    f.read(),
                    zipf.read("archive/statement/Title 2 - Doc 3.pdf"),
                )

            with self.doc3.source_file as f:
                self.assertEqual(
                    f.read(),
                    zipf.read("originals/statement/Title 2 - Doc 3.jpg"),
                )

    def test_download_insufficient_permissions(self):
        user = User.objects.create_user(username="temp_user")
        self.client.force_authenticate(user=user)

        self.doc2.owner = self.user
        self.doc2.save()

        response = self.client.post(
            self.ENDPOINT,
            json.dumps({"documents": [self.doc2.id, self.doc3.id]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.content, b"Insufficient permissions")
