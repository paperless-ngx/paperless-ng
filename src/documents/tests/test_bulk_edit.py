import shutil
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.test import TestCase
from guardian.shortcuts import assign_perm
from guardian.shortcuts import get_groups_with_perms
from guardian.shortcuts import get_users_with_perms

from documents import bulk_edit
from documents.models import Correspondent
from documents.models import CustomField
from documents.models import CustomFieldInstance
from documents.models import Document
from documents.models import DocumentType
from documents.models import StoragePath
from documents.models import Tag
from documents.tests.utils import DirectoriesMixin


class TestBulkEdit(DirectoriesMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.owner = User.objects.create(username="test_owner")
        self.user1 = User.objects.create(username="user1")
        self.user2 = User.objects.create(username="user2")
        self.group1 = Group.objects.create(name="group1")
        self.group2 = Group.objects.create(name="group2")

        patcher = mock.patch("documents.bulk_edit.bulk_update_documents.delay")
        self.async_task = patcher.start()
        self.addCleanup(patcher.stop)
        self.c1 = Correspondent.objects.create(name="c1")
        self.c2 = Correspondent.objects.create(name="c2")
        self.dt1 = DocumentType.objects.create(name="dt1")
        self.dt2 = DocumentType.objects.create(name="dt2")
        self.t1 = Tag.objects.create(name="t1")
        self.t2 = Tag.objects.create(name="t2")
        self.doc1 = Document.objects.create(checksum="A", title="A")
        self.doc2 = Document.objects.create(
            checksum="B",
            title="B",
            correspondent=self.c1,
            document_type=self.dt1,
        )
        self.doc3 = Document.objects.create(
            checksum="C",
            title="C",
            correspondent=self.c2,
            document_type=self.dt2,
        )
        self.doc4 = Document.objects.create(checksum="D", title="D")
        self.doc5 = Document.objects.create(checksum="E", title="E")
        self.doc2.tags.add(self.t1)
        self.doc3.tags.add(self.t2)
        self.doc4.tags.add(self.t1, self.t2)
        self.sp1 = StoragePath.objects.create(name="sp1", path="Something/{checksum}")

    def test_set_correspondent(self):
        self.assertEqual(Document.objects.filter(correspondent=self.c2).count(), 1)
        bulk_edit.set_correspondent(
            [self.doc1.id, self.doc2.id, self.doc3.id],
            self.c2.id,
        )
        self.assertEqual(Document.objects.filter(correspondent=self.c2).count(), 3)
        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        self.assertCountEqual(kwargs["document_ids"], [self.doc1.id, self.doc2.id])

    def test_unset_correspondent(self):
        self.assertEqual(Document.objects.filter(correspondent=self.c2).count(), 1)
        bulk_edit.set_correspondent([self.doc1.id, self.doc2.id, self.doc3.id], None)
        self.assertEqual(Document.objects.filter(correspondent=self.c2).count(), 0)
        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        self.assertCountEqual(kwargs["document_ids"], [self.doc2.id, self.doc3.id])

    def test_set_document_type(self):
        self.assertEqual(Document.objects.filter(document_type=self.dt2).count(), 1)
        bulk_edit.set_document_type(
            [self.doc1.id, self.doc2.id, self.doc3.id],
            self.dt2.id,
        )
        self.assertEqual(Document.objects.filter(document_type=self.dt2).count(), 3)
        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        self.assertCountEqual(kwargs["document_ids"], [self.doc1.id, self.doc2.id])

    def test_unset_document_type(self):
        self.assertEqual(Document.objects.filter(document_type=self.dt2).count(), 1)
        bulk_edit.set_document_type([self.doc1.id, self.doc2.id, self.doc3.id], None)
        self.assertEqual(Document.objects.filter(document_type=self.dt2).count(), 0)
        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        self.assertCountEqual(kwargs["document_ids"], [self.doc2.id, self.doc3.id])

    def test_set_document_storage_path(self):
        """
        GIVEN:
            - 5 documents without defined storage path
        WHEN:
            - Bulk edit called to add storage path to 1 document
        THEN:
            - Single document storage path update
        """
        self.assertEqual(Document.objects.filter(storage_path=None).count(), 5)

        bulk_edit.set_storage_path(
            [self.doc1.id],
            self.sp1.id,
        )

        self.assertEqual(Document.objects.filter(storage_path=None).count(), 4)

        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args

        self.assertCountEqual(kwargs["document_ids"], [self.doc1.id])

    def test_unset_document_storage_path(self):
        """
        GIVEN:
            - 4 documents without defined storage path
            - 1 document with a defined storage
        WHEN:
            - Bulk edit called to remove storage path from 1 document
        THEN:
            - Single document storage path removed
        """
        self.assertEqual(Document.objects.filter(storage_path=None).count(), 5)

        bulk_edit.set_storage_path(
            [self.doc1.id],
            self.sp1.id,
        )

        self.assertEqual(Document.objects.filter(storage_path=None).count(), 4)

        bulk_edit.set_storage_path(
            [self.doc1.id],
            None,
        )

        self.assertEqual(Document.objects.filter(storage_path=None).count(), 5)

        self.async_task.assert_called()
        args, kwargs = self.async_task.call_args

        self.assertCountEqual(kwargs["document_ids"], [self.doc1.id])

    def test_add_tag(self):
        self.assertEqual(Document.objects.filter(tags__id=self.t1.id).count(), 2)
        bulk_edit.add_tag(
            [self.doc1.id, self.doc2.id, self.doc3.id, self.doc4.id],
            self.t1.id,
        )
        self.assertEqual(Document.objects.filter(tags__id=self.t1.id).count(), 4)
        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        self.assertCountEqual(kwargs["document_ids"], [self.doc1.id, self.doc3.id])

    def test_remove_tag(self):
        self.assertEqual(Document.objects.filter(tags__id=self.t1.id).count(), 2)
        bulk_edit.remove_tag([self.doc1.id, self.doc3.id, self.doc4.id], self.t1.id)
        self.assertEqual(Document.objects.filter(tags__id=self.t1.id).count(), 1)
        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        self.assertCountEqual(kwargs["document_ids"], [self.doc4.id])

    def test_modify_tags(self):
        tag_unrelated = Tag.objects.create(name="unrelated")
        self.doc2.tags.add(tag_unrelated)
        self.doc3.tags.add(tag_unrelated)
        bulk_edit.modify_tags(
            [self.doc2.id, self.doc3.id],
            add_tags=[self.t2.id],
            remove_tags=[self.t1.id],
        )

        self.assertCountEqual(list(self.doc2.tags.all()), [self.t2, tag_unrelated])
        self.assertCountEqual(list(self.doc3.tags.all()), [self.t2, tag_unrelated])

        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        # TODO: doc3 should not be affected, but the query for that is rather complicated
        self.assertCountEqual(kwargs["document_ids"], [self.doc2.id, self.doc3.id])

    def test_modify_custom_fields(self):
        """
        GIVEN:
            - 2 documents with custom fields
            - 3 custom fields
        WHEN:
            - Custom fields are modified using old format (list of ids)
        THEN:
            - Custom fields are modified for the documents
        """
        cf = CustomField.objects.create(
            name="cf1",
            data_type=CustomField.FieldDataType.STRING,
        )
        cf2 = CustomField.objects.create(
            name="cf2",
            data_type=CustomField.FieldDataType.INT,
        )
        cf3 = CustomField.objects.create(
            name="cf3",
            data_type=CustomField.FieldDataType.STRING,
        )
        CustomFieldInstance.objects.create(
            document=self.doc1,
            field=cf,
        )
        CustomFieldInstance.objects.create(
            document=self.doc2,
            field=cf,
        )
        CustomFieldInstance.objects.create(
            document=self.doc2,
            field=cf3,
        )
        bulk_edit.modify_custom_fields(
            [self.doc1.id, self.doc2.id],
            add_custom_fields=[cf2.id],
            remove_custom_fields=[cf.id],
        )

        self.doc1.refresh_from_db()
        self.doc2.refresh_from_db()

        self.assertEqual(
            self.doc1.custom_fields.count(),
            1,
        )
        self.assertEqual(
            self.doc2.custom_fields.count(),
            2,
        )

        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        self.assertCountEqual(kwargs["document_ids"], [self.doc1.id, self.doc2.id])

    def test_modify_custom_fields_with_values(self):
        """
        GIVEN:
            - 2 documents with custom fields
            - 3 custom fields
        WHEN:
            - Custom fields are modified using new format (dict)
        THEN:
            - Custom fields are modified for the documents
        """
        cf = CustomField.objects.create(
            name="cf",
            data_type=CustomField.FieldDataType.STRING,
        )
        cf1 = CustomField.objects.create(
            name="cf1",
            data_type=CustomField.FieldDataType.STRING,
        )
        cf2 = CustomField.objects.create(
            name="cf2",
            data_type=CustomField.FieldDataType.MONETARY,
        )
        cf3 = CustomField.objects.create(
            name="cf3",
            data_type=CustomField.FieldDataType.STRING,
        )
        CustomFieldInstance.objects.create(
            document=self.doc2,
            field=cf,
        )
        CustomFieldInstance.objects.create(
            document=self.doc2,
            field=cf1,
        )
        CustomFieldInstance.objects.create(
            document=self.doc2,
            field=cf3,
        )
        bulk_edit.modify_custom_fields(
            [self.doc1.id, self.doc2.id],
            add_custom_fields={cf2.id: None, cf3.id: "value"},
            remove_custom_fields=[cf.id],
        )

        self.doc1.refresh_from_db()
        self.doc2.refresh_from_db()

        self.assertEqual(
            self.doc1.custom_fields.count(),
            2,
        )
        self.assertEqual(
            self.doc1.custom_fields.get(field=cf2).value,
            None,
        )
        self.assertEqual(
            self.doc1.custom_fields.get(field=cf3).value,
            "value",
        )
        self.assertEqual(
            self.doc2.custom_fields.count(),
            3,
        )
        self.assertEqual(
            self.doc2.custom_fields.get(field=cf3).value,
            "value",
        )

        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        self.assertCountEqual(kwargs["document_ids"], [self.doc1.id, self.doc2.id])

    def test_delete(self):
        self.assertEqual(Document.objects.count(), 5)
        bulk_edit.delete([self.doc1.id, self.doc2.id])
        self.assertEqual(Document.objects.count(), 3)
        self.assertCountEqual(
            [doc.id for doc in Document.objects.all()],
            [self.doc3.id, self.doc4.id, self.doc5.id],
        )

    @mock.patch("documents.tasks.bulk_update_documents.delay")
    def test_set_permissions(self, m):
        doc_ids = [self.doc1.id, self.doc2.id, self.doc3.id]

        assign_perm("view_document", self.group1, self.doc1)

        permissions = {
            "view": {
                "users": [self.user1.id, self.user2.id],
                "groups": [self.group2.id],
            },
            "change": {
                "users": [self.user1.id],
                "groups": [self.group2.id],
            },
        }

        bulk_edit.set_permissions(
            doc_ids,
            set_permissions=permissions,
            owner=self.owner,
            merge=False,
        )
        m.assert_called_once()

        self.assertEqual(Document.objects.filter(owner=self.owner).count(), 3)
        self.assertEqual(Document.objects.filter(id__in=doc_ids).count(), 3)

        users_with_perms = get_users_with_perms(
            self.doc1,
        )
        self.assertEqual(users_with_perms.count(), 2)

        # group1 should be replaced by group2
        groups_with_perms = get_groups_with_perms(
            self.doc1,
        )
        self.assertEqual(groups_with_perms.count(), 1)

    @mock.patch("documents.tasks.bulk_update_documents.delay")
    def test_set_permissions_merge(self, m):
        doc_ids = [self.doc1.id, self.doc2.id, self.doc3.id]

        self.doc1.owner = self.user1
        self.doc1.save()

        assign_perm("view_document", self.user1, self.doc1)
        assign_perm("view_document", self.group1, self.doc1)

        permissions = {
            "view": {
                "users": [self.user2.id],
                "groups": [self.group2.id],
            },
            "change": {
                "users": [self.user2.id],
                "groups": [self.group2.id],
            },
        }
        bulk_edit.set_permissions(
            doc_ids,
            set_permissions=permissions,
            owner=self.owner,
            merge=True,
        )
        m.assert_called_once()

        # when merge is true owner doesn't get replaced if its not empty
        self.assertEqual(Document.objects.filter(owner=self.owner).count(), 2)
        self.assertEqual(Document.objects.filter(id__in=doc_ids).count(), 3)

        # merge of user1 which was pre-existing and user2
        users_with_perms = get_users_with_perms(
            self.doc1,
        )
        self.assertEqual(users_with_perms.count(), 2)

        # group1 should be merged by group2
        groups_with_perms = get_groups_with_perms(
            self.doc1,
        )
        self.assertEqual(groups_with_perms.count(), 2)

    @mock.patch("documents.models.Document.delete")
    def test_delete_documents_old_uuid_field(self, m):
        m.side_effect = Exception("Data too long for column 'transaction_id' at row 1")
        doc_ids = [self.doc1.id, self.doc2.id, self.doc3.id]
        bulk_edit.delete(doc_ids)
        with self.assertLogs(level="WARNING") as cm:
            bulk_edit.delete(doc_ids)
            self.assertIn("possible incompatible database column", cm.output[0])


class TestPDFActions(DirectoriesMixin, TestCase):
    def setUp(self):
        super().setUp()
        sample1 = self.dirs.scratch_dir / "sample.pdf"
        shutil.copy(
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000001.pdf",
            sample1,
        )
        sample1_archive = self.dirs.archive_dir / "sample_archive.pdf"
        shutil.copy(
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000001.pdf",
            sample1_archive,
        )
        sample2 = self.dirs.scratch_dir / "sample2.pdf"
        shutil.copy(
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000002.pdf",
            sample2,
        )
        sample2_archive = self.dirs.archive_dir / "sample2_archive.pdf"
        shutil.copy(
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000002.pdf",
            sample2_archive,
        )
        sample3 = self.dirs.scratch_dir / "sample3.pdf"
        shutil.copy(
            Path(__file__).parent
            / "samples"
            / "documents"
            / "originals"
            / "0000003.pdf",
            sample3,
        )
        self.doc1 = Document.objects.create(
            checksum="A",
            title="A",
            filename=sample1,
            mime_type="application/pdf",
        )
        self.doc1.archive_filename = sample1_archive
        self.doc1.save()
        self.doc2 = Document.objects.create(
            checksum="B",
            title="B",
            filename=sample2,
            mime_type="application/pdf",
            page_count=8,
        )
        self.doc2.archive_filename = sample2_archive
        self.doc2.save()
        self.doc3 = Document.objects.create(
            checksum="C",
            title="C",
            filename=sample3,
            mime_type="application/pdf",
        )
        img_doc = self.dirs.scratch_dir / "sample_image.jpg"
        shutil.copy(
            Path(__file__).parent / "samples" / "simple.jpg",
            img_doc,
        )
        self.img_doc = Document.objects.create(
            checksum="D",
            title="D",
            filename=img_doc,
            mime_type="image/jpeg",
        )

    @mock.patch("documents.tasks.consume_file.s")
    def test_merge(self, mock_consume_file):
        """
        GIVEN:
            - Existing documents
        WHEN:
            - Merge action is called with 3 documents
        THEN:
            - Consume file should be called
        """
        doc_ids = [self.doc1.id, self.doc2.id, self.doc3.id]
        metadata_document_id = self.doc1.id
        user = User.objects.create(username="test_user")

        result = bulk_edit.merge(
            doc_ids,
            metadata_document_id=None,
            delete_originals=False,
            user=user,
        )

        expected_filename = (
            f"{'_'.join([str(doc_id) for doc_id in doc_ids])[:100]}_merged.pdf"
        )

        mock_consume_file.assert_called()
        consume_file_args, _ = mock_consume_file.call_args
        self.assertEqual(
            Path(consume_file_args[0].original_file).name,
            expected_filename,
        )
        self.assertEqual(consume_file_args[1].title, None)

        # With metadata_document_id overrides
        result = bulk_edit.merge(doc_ids, metadata_document_id=metadata_document_id)
        consume_file_args, _ = mock_consume_file.call_args
        self.assertEqual(consume_file_args[1].title, "A (merged)")

        self.assertEqual(result, "OK")

    @mock.patch("documents.bulk_edit.delete.si")
    @mock.patch("documents.tasks.consume_file.s")
    @mock.patch("documents.bulk_edit.chain")
    def test_merge_and_delete_originals(
        self,
        mock_chain,
        mock_consume_file,
        mock_delete_documents,
    ):
        """
        GIVEN:
            - Existing documents
        WHEN:
            - Merge action with deleting documents is called with 3 documents
        THEN:
            - Consume file task should be called
            - Document deletion task should be called
        """
        doc_ids = [self.doc1.id, self.doc2.id, self.doc3.id]

        result = bulk_edit.merge(doc_ids, delete_originals=True)
        self.assertEqual(result, "OK")

        expected_filename = (
            f"{'_'.join([str(doc_id) for doc_id in doc_ids])[:100]}_merged.pdf"
        )

        mock_consume_file.assert_called()
        mock_delete_documents.assert_called()
        mock_chain.assert_called_once()

        consume_file_args, _ = mock_consume_file.call_args
        self.assertEqual(
            Path(consume_file_args[0].original_file).name,
            expected_filename,
        )
        self.assertEqual(consume_file_args[1].title, None)

        delete_documents_args, _ = mock_delete_documents.call_args
        self.assertEqual(
            delete_documents_args[0],
            doc_ids,
        )

    @mock.patch("documents.tasks.consume_file.delay")
    @mock.patch("pikepdf.open")
    def test_merge_with_errors(self, mock_open_pdf, mock_consume_file):
        """
        GIVEN:
            - Existing documents
        WHEN:
            - Merge action is called with 2 documents
            - Error occurs when opening both files
        THEN:
            - Consume file should not be called
        """
        mock_open_pdf.side_effect = Exception("Error opening PDF")
        doc_ids = [self.doc2.id, self.doc3.id]

        with self.assertLogs("paperless.bulk_edit", level="ERROR") as cm:
            bulk_edit.merge(doc_ids)
            error_str = cm.output[0]
            expected_str = (
                "Error merging document 2, it will not be included in the merge"
            )
            self.assertIn(expected_str, error_str)

        mock_consume_file.assert_not_called()

    @mock.patch("documents.tasks.consume_file.s")
    def test_split(self, mock_consume_file):
        """
        GIVEN:
            - Existing documents
        WHEN:
            - Split action is called with 1 document and 2 pages
        THEN:
            - Consume file should be called twice
        """
        doc_ids = [self.doc2.id]
        pages = [[1, 2], [3]]
        user = User.objects.create(username="test_user")
        result = bulk_edit.split(doc_ids, pages, delete_originals=False, user=user)
        self.assertEqual(mock_consume_file.call_count, 2)
        consume_file_args, _ = mock_consume_file.call_args
        self.assertEqual(consume_file_args[1].title, "B (split 2)")

        self.assertEqual(result, "OK")

    @mock.patch("documents.bulk_edit.delete.si")
    @mock.patch("documents.tasks.consume_file.s")
    @mock.patch("documents.bulk_edit.chord")
    def test_split_and_delete_originals(
        self,
        mock_chord,
        mock_consume_file,
        mock_delete_documents,
    ):
        """
        GIVEN:
            - Existing documents
        WHEN:
            - Split action with deleting documents is called with 1 document and 2 page groups
            - delete_originals is set to True
        THEN:
            - Consume file should be called twice
            - Document deletion task should be called
        """
        doc_ids = [self.doc2.id]
        pages = [[1, 2], [3]]

        result = bulk_edit.split(doc_ids, pages, delete_originals=True)
        self.assertEqual(result, "OK")

        self.assertEqual(mock_consume_file.call_count, 2)
        consume_file_args, _ = mock_consume_file.call_args
        self.assertEqual(consume_file_args[1].title, "B (split 2)")

        mock_delete_documents.assert_called()
        mock_chord.assert_called_once()

        delete_documents_args, _ = mock_delete_documents.call_args
        self.assertEqual(
            delete_documents_args[0],
            doc_ids,
        )

    @mock.patch("documents.tasks.consume_file.delay")
    @mock.patch("pikepdf.Pdf.save")
    def test_split_with_errors(self, mock_save_pdf, mock_consume_file):
        """
        GIVEN:
            - Existing documents
        WHEN:
            - Split action is called with 1 document and 2 page groups
            - Error occurs when saving the files
        THEN:
            - Consume file should not be called
        """
        mock_save_pdf.side_effect = Exception("Error saving PDF")
        doc_ids = [self.doc2.id]
        pages = [[1, 2], [3]]

        with self.assertLogs("paperless.bulk_edit", level="ERROR") as cm:
            bulk_edit.split(doc_ids, pages)
            error_str = cm.output[0]
            expected_str = "Error splitting document 2"
            self.assertIn(expected_str, error_str)

        mock_consume_file.assert_not_called()

    @mock.patch("documents.tasks.bulk_update_documents.si")
    @mock.patch("documents.tasks.update_document_content_maybe_archive_file.s")
    @mock.patch("celery.chord.delay")
    def test_rotate(self, mock_chord, mock_update_document, mock_update_documents):
        """
        GIVEN:
            - Existing documents
        WHEN:
            - Rotate action is called with 2 documents
        THEN:
            - Rotate action should be called twice
        """
        doc_ids = [self.doc1.id, self.doc2.id]
        result = bulk_edit.rotate(doc_ids, 90)
        self.assertEqual(mock_update_document.call_count, 2)
        mock_update_documents.assert_called_once()
        mock_chord.assert_called_once()
        self.assertEqual(result, "OK")

    @mock.patch("documents.tasks.bulk_update_documents.si")
    @mock.patch("documents.tasks.update_document_content_maybe_archive_file.s")
    @mock.patch("pikepdf.Pdf.save")
    def test_rotate_with_error(
        self,
        mock_pdf_save,
        mock_update_archive_file,
        mock_update_documents,
    ):
        """
        GIVEN:
            - Existing documents
        WHEN:
            - Rotate action is called with 2 documents
            - PikePDF raises an error
        THEN:
            - Rotate action should be called 0 times
        """
        mock_pdf_save.side_effect = Exception("Error saving PDF")
        doc_ids = [self.doc2.id, self.doc3.id]

        with self.assertLogs("paperless.bulk_edit", level="ERROR") as cm:
            bulk_edit.rotate(doc_ids, 90)
            error_str = cm.output[0]
            expected_str = "Error rotating document"
            self.assertIn(expected_str, error_str)
            mock_update_archive_file.assert_not_called()

    @mock.patch("documents.tasks.bulk_update_documents.si")
    @mock.patch("documents.tasks.update_document_content_maybe_archive_file.s")
    @mock.patch("celery.chord.delay")
    def test_rotate_non_pdf(
        self,
        mock_chord,
        mock_update_document,
        mock_update_documents,
    ):
        """
        GIVEN:
            - Existing documents
        WHEN:
            - Rotate action is called with 2 documents, one of which is not a PDF
        THEN:
            - Rotate action should be performed 1 time, with the non-PDF document skipped
        """
        with self.assertLogs("paperless.bulk_edit", level="INFO") as cm:
            result = bulk_edit.rotate([self.doc2.id, self.img_doc.id], 90)
            output_str = cm.output[1]
            expected_str = "Document 4 is not a PDF, skipping rotation"
            self.assertIn(expected_str, output_str)
            self.assertEqual(mock_update_document.call_count, 1)
            mock_update_documents.assert_called_once()
            mock_chord.assert_called_once()
            self.assertEqual(result, "OK")

    @mock.patch("documents.tasks.update_document_content_maybe_archive_file.delay")
    @mock.patch("pikepdf.Pdf.save")
    def test_delete_pages(self, mock_pdf_save, mock_update_archive_file):
        """
        GIVEN:
            - Existing documents
        WHEN:
            - Delete pages action is called with 1 document and 2 pages
        THEN:
            - Save should be called once
            - Archive file should be updated once
            - The document's page_count should be reduced by the number of deleted pages
        """
        doc_ids = [self.doc2.id]
        initial_page_count = self.doc2.page_count
        pages = [1, 3]
        result = bulk_edit.delete_pages(doc_ids, pages)
        mock_pdf_save.assert_called_once()
        mock_update_archive_file.assert_called_once()
        self.assertEqual(result, "OK")

        expected_page_count = initial_page_count - len(pages)
        self.doc2.refresh_from_db()
        self.assertEqual(self.doc2.page_count, expected_page_count)

    @mock.patch("documents.tasks.update_document_content_maybe_archive_file.delay")
    @mock.patch("pikepdf.Pdf.save")
    def test_delete_pages_with_error(self, mock_pdf_save, mock_update_archive_file):
        """
        GIVEN:
            - Existing documents
        WHEN:
            - Delete pages action is called with 1 document and 2 pages
            - PikePDF raises an error
        THEN:
            - Save should be called once
            - Archive file should not be updated
        """
        mock_pdf_save.side_effect = Exception("Error saving PDF")
        doc_ids = [self.doc2.id]
        pages = [1, 3]

        with self.assertLogs("paperless.bulk_edit", level="ERROR") as cm:
            bulk_edit.delete_pages(doc_ids, pages)
            error_str = cm.output[0]
            expected_str = "Error deleting pages from document"
            self.assertIn(expected_str, error_str)
            mock_update_archive_file.assert_not_called()
