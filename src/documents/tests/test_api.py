import json
import os
import shutil
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from rest_framework.test import APITestCase
from whoosh.writing import AsyncWriter

from documents import index, bulk_edit
from documents.models import Document, Correspondent, DocumentType, Tag, SavedView
from documents.tests.utils import DirectoriesMixin


class TestDocumentApi(DirectoriesMixin, APITestCase):

    def setUp(self):
        super(TestDocumentApi, self).setUp()

        self.user = User.objects.create_superuser(username="temp_admin")
        self.client.force_login(user=self.user)

    def testDocuments(self):

        response = self.client.get("/api/documents/").data

        self.assertEqual(response['count'], 0)

        c = Correspondent.objects.create(name="c", pk=41)
        dt = DocumentType.objects.create(name="dt", pk=63)
        tag = Tag.objects.create(name="t", pk=85)

        doc = Document.objects.create(title="WOW", content="the content", correspondent=c, document_type=dt, checksum="123", mime_type="application/pdf")

        doc.tags.add(tag)

        response = self.client.get("/api/documents/", format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)

        returned_doc = response.data['results'][0]
        self.assertEqual(returned_doc['id'], doc.id)
        self.assertEqual(returned_doc['title'], doc.title)
        self.assertEqual(returned_doc['correspondent'], c.id)
        self.assertEqual(returned_doc['document_type'], dt.id)
        self.assertListEqual(returned_doc['tags'], [tag.id])

        c2 = Correspondent.objects.create(name="c2")

        returned_doc['correspondent'] = c2.pk
        returned_doc['title'] = "the new title"

        response = self.client.put('/api/documents/{}/'.format(doc.pk), returned_doc, format='json')

        self.assertEqual(response.status_code, 200)

        doc_after_save = Document.objects.get(id=doc.id)

        self.assertEqual(doc_after_save.correspondent, c2)
        self.assertEqual(doc_after_save.title, "the new title")

        self.client.delete("/api/documents/{}/".format(doc_after_save.pk))

        self.assertEqual(len(Document.objects.all()), 0)

    def test_document_fields(self):
        c = Correspondent.objects.create(name="c", pk=41)
        dt = DocumentType.objects.create(name="dt", pk=63)
        tag = Tag.objects.create(name="t", pk=85)
        doc = Document.objects.create(title="WOW", content="the content", correspondent=c, document_type=dt, checksum="123", mime_type="application/pdf")

        response = self.client.get("/api/documents/", format='json')
        self.assertEqual(response.status_code, 200)
        results_full = response.data['results']
        self.assertTrue("content" in results_full[0])
        self.assertTrue("id" in results_full[0])

        response = self.client.get("/api/documents/?fields=id", format='json')
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertFalse("content" in results[0])
        self.assertTrue("id" in results[0])
        self.assertEqual(len(results[0]), 1)

        response = self.client.get("/api/documents/?fields=content", format='json')
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertTrue("content" in results[0])
        self.assertFalse("id" in results[0])
        self.assertEqual(len(results[0]), 1)

        response = self.client.get("/api/documents/?fields=id,content", format='json')
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertTrue("content" in results[0])
        self.assertTrue("id" in results[0])
        self.assertEqual(len(results[0]), 2)

        response = self.client.get("/api/documents/?fields=id,conteasdnt", format='json')
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertFalse("content" in results[0])
        self.assertTrue("id" in results[0])
        self.assertEqual(len(results[0]), 1)

        response = self.client.get("/api/documents/?fields=", format='json')
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(results_full, results)

        response = self.client.get("/api/documents/?fields=dgfhs", format='json')
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(len(results[0]), 0)

    def test_document_actions(self):

        _, filename = tempfile.mkstemp(dir=self.dirs.originals_dir)

        content = b"This is a test"
        content_thumbnail = b"thumbnail content"

        with open(filename, "wb") as f:
            f.write(content)

        doc = Document.objects.create(title="none", filename=os.path.basename(filename), mime_type="application/pdf")

        with open(os.path.join(self.dirs.thumbnail_dir, "{:07d}.png".format(doc.pk)), "wb") as f:
            f.write(content_thumbnail)

        response = self.client.get('/api/documents/{}/download/'.format(doc.pk))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, content)

        response = self.client.get('/api/documents/{}/preview/'.format(doc.pk))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, content)

        response = self.client.get('/api/documents/{}/thumb/'.format(doc.pk))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, content_thumbnail)

    def test_download_with_archive(self):

        _, filename = tempfile.mkstemp(dir=self.dirs.originals_dir)

        content = b"This is a test"
        content_archive = b"This is the same test but archived"

        with open(filename, "wb") as f:
            f.write(content)

        filename = os.path.basename(filename)

        doc = Document.objects.create(title="none", filename=filename,
                                      mime_type="application/pdf")

        with open(doc.archive_path, "wb") as f:
            f.write(content_archive)

        response = self.client.get('/api/documents/{}/download/'.format(doc.pk))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, content_archive)

        response = self.client.get('/api/documents/{}/download/?original=true'.format(doc.pk))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, content)

        response = self.client.get('/api/documents/{}/preview/'.format(doc.pk))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, content_archive)

        response = self.client.get('/api/documents/{}/preview/?original=true'.format(doc.pk))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, content)

    def test_document_actions_not_existing_file(self):

        doc = Document.objects.create(title="none", filename=os.path.basename("asd"), mime_type="application/pdf")

        response = self.client.get('/api/documents/{}/download/'.format(doc.pk))
        self.assertEqual(response.status_code, 404)

        response = self.client.get('/api/documents/{}/preview/'.format(doc.pk))
        self.assertEqual(response.status_code, 404)

        response = self.client.get('/api/documents/{}/thumb/'.format(doc.pk))
        self.assertEqual(response.status_code, 404)

    def test_document_filters(self):

        doc1 = Document.objects.create(title="none1", checksum="A", mime_type="application/pdf")
        doc2 = Document.objects.create(title="none2", checksum="B", mime_type="application/pdf")
        doc3 = Document.objects.create(title="none3", checksum="C", mime_type="application/pdf")

        tag_inbox = Tag.objects.create(name="t1", is_inbox_tag=True)
        tag_2 = Tag.objects.create(name="t2")
        tag_3 = Tag.objects.create(name="t3")

        doc1.tags.add(tag_inbox)
        doc2.tags.add(tag_2)
        doc3.tags.add(tag_2)
        doc3.tags.add(tag_3)

        response = self.client.get("/api/documents/?is_in_inbox=true")
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], doc1.id)

        response = self.client.get("/api/documents/?is_in_inbox=false")
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(len(results), 2)
        self.assertCountEqual([results[0]['id'], results[1]['id']], [doc2.id, doc3.id])

        response = self.client.get("/api/documents/?tags__id__in={},{}".format(tag_inbox.id, tag_3.id))
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(len(results), 2)
        self.assertCountEqual([results[0]['id'], results[1]['id']], [doc1.id, doc3.id])

        response = self.client.get("/api/documents/?tags__id__all={},{}".format(tag_2.id, tag_3.id))
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], doc3.id)

        response = self.client.get("/api/documents/?tags__id__all={},{}".format(tag_inbox.id, tag_3.id))
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(len(results), 0)

        response = self.client.get("/api/documents/?tags__id__all={}a{}".format(tag_inbox.id, tag_3.id))
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(len(results), 3)

        response = self.client.get("/api/documents/?tags__id__none={}".format(tag_3.id))
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(len(results), 2)
        self.assertCountEqual([results[0]['id'], results[1]['id']], [doc1.id, doc2.id])

        response = self.client.get("/api/documents/?tags__id__none={},{}".format(tag_3.id, tag_2.id))
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], doc1.id)

        response = self.client.get("/api/documents/?tags__id__none={},{}".format(tag_2.id, tag_inbox.id))
        self.assertEqual(response.status_code, 200)
        results = response.data['results']
        self.assertEqual(len(results), 0)

    def test_search_no_query(self):
        response = self.client.get("/api/search/")
        results = response.data['results']

        self.assertEqual(len(results), 0)

    def test_search(self):
        d1=Document.objects.create(title="invoice", content="the thing i bought at a shop and paid with bank account", checksum="A", pk=1)
        d2=Document.objects.create(title="bank statement 1", content="things i paid for in august", pk=2, checksum="B")
        d3=Document.objects.create(title="bank statement 3", content="things i paid for in september", pk=3, checksum="C")
        with AsyncWriter(index.open_index()) as writer:
            # Note to future self: there is a reason we dont use a model signal handler to update the index: some operations edit many documents at once
            # (retagger, renamer) and we don't want to open a writer for each of these, but rather perform the entire operation with one writer.
            # That's why we cant open the writer in a model on_save handler or something.
            index.update_document(writer, d1)
            index.update_document(writer, d2)
            index.update_document(writer, d3)
        response = self.client.get("/api/search/?query=bank")
        results = response.data['results']
        self.assertEqual(response.data['count'], 3)
        self.assertEqual(response.data['page'], 1)
        self.assertEqual(response.data['page_count'], 1)
        self.assertEqual(len(results), 3)

        response = self.client.get("/api/search/?query=september")
        results = response.data['results']
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['page'], 1)
        self.assertEqual(response.data['page_count'], 1)
        self.assertEqual(len(results), 1)

        response = self.client.get("/api/search/?query=statement")
        results = response.data['results']
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(response.data['page'], 1)
        self.assertEqual(response.data['page_count'], 1)
        self.assertEqual(len(results), 2)

        response = self.client.get("/api/search/?query=sfegdfg")
        results = response.data['results']
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['page'], 0)
        self.assertEqual(response.data['page_count'], 0)
        self.assertEqual(len(results), 0)

    def test_search_multi_page(self):
        with AsyncWriter(index.open_index()) as writer:
            for i in range(55):
                doc = Document.objects.create(checksum=str(i), pk=i+1, title=f"Document {i+1}", content="content")
                index.update_document(writer, doc)

        # This is here so that we test that no document gets returned twice (might happen if the paging is not working)
        seen_ids = []

        for i in range(1, 6):
            response = self.client.get(f"/api/search/?query=content&page={i}")
            results = response.data['results']
            self.assertEqual(response.data['count'], 55)
            self.assertEqual(response.data['page'], i)
            self.assertEqual(response.data['page_count'], 6)
            self.assertEqual(len(results), 10)

            for result in results:
                self.assertNotIn(result['id'], seen_ids)
                seen_ids.append(result['id'])

        response = self.client.get(f"/api/search/?query=content&page=6")
        results = response.data['results']
        self.assertEqual(response.data['count'], 55)
        self.assertEqual(response.data['page'], 6)
        self.assertEqual(response.data['page_count'], 6)
        self.assertEqual(len(results), 5)

        for result in results:
            self.assertNotIn(result['id'], seen_ids)
            seen_ids.append(result['id'])

        response = self.client.get(f"/api/search/?query=content&page=7")
        results = response.data['results']
        self.assertEqual(response.data['count'], 55)
        self.assertEqual(response.data['page'], 6)
        self.assertEqual(response.data['page_count'], 6)
        self.assertEqual(len(results), 5)

    def test_search_invalid_page(self):
        with AsyncWriter(index.open_index()) as writer:
            for i in range(15):
                doc = Document.objects.create(checksum=str(i), pk=i+1, title=f"Document {i+1}", content="content")
                index.update_document(writer, doc)

        first_page = self.client.get(f"/api/search/?query=content&page=1").data
        second_page = self.client.get(f"/api/search/?query=content&page=2").data
        should_be_first_page_1 = self.client.get(f"/api/search/?query=content&page=0").data
        should_be_first_page_2 = self.client.get(f"/api/search/?query=content&page=dgfd").data
        should_be_first_page_3 = self.client.get(f"/api/search/?query=content&page=").data
        should_be_first_page_4 = self.client.get(f"/api/search/?query=content&page=-7868").data

        self.assertDictEqual(first_page, should_be_first_page_1)
        self.assertDictEqual(first_page, should_be_first_page_2)
        self.assertDictEqual(first_page, should_be_first_page_3)
        self.assertDictEqual(first_page, should_be_first_page_4)
        self.assertNotEqual(len(first_page['results']), len(second_page['results']))

    @mock.patch("documents.index.autocomplete")
    def test_search_autocomplete(self, m):
        m.side_effect = lambda ix, term, limit: [term for _ in range(limit)]

        response = self.client.get("/api/search/autocomplete/?term=test")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 10)

        response = self.client.get("/api/search/autocomplete/?term=test&limit=20")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 20)

        response = self.client.get("/api/search/autocomplete/?term=test&limit=-1")
        self.assertEqual(response.status_code, 400)

        response = self.client.get("/api/search/autocomplete/")
        self.assertEqual(response.status_code, 400)

        response = self.client.get("/api/search/autocomplete/?term=")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 10)

    def test_search_spelling_correction(self):
        with AsyncWriter(index.open_index()) as writer:
            for i in range(55):
                doc = Document.objects.create(checksum=str(i), pk=i+1, title=f"Document {i+1}", content=f"Things document {i+1}")
                index.update_document(writer, doc)

        response = self.client.get("/api/search/?query=thing")
        correction = response.data['corrected_query']

        self.assertEqual(correction, "things")

        response = self.client.get("/api/search/?query=things")
        correction = response.data['corrected_query']

        self.assertEqual(correction, None)

    def test_search_more_like(self):
        d1=Document.objects.create(title="invoice", content="the thing i bought at a shop and paid with bank account", checksum="A", pk=1)
        d2=Document.objects.create(title="bank statement 1", content="things i paid for in august", pk=2, checksum="B")
        d3=Document.objects.create(title="bank statement 3", content="things i paid for in september", pk=3, checksum="C")
        with AsyncWriter(index.open_index()) as writer:
            index.update_document(writer, d1)
            index.update_document(writer, d2)
            index.update_document(writer, d3)

        response = self.client.get(f"/api/search/?more_like={d2.id}")

        self.assertEqual(response.status_code, 200)

        results = response.data['results']

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['id'], d3.id)
        self.assertEqual(results[1]['id'], d1.id)

    def test_statistics(self):

        doc1 = Document.objects.create(title="none1", checksum="A")
        doc2 = Document.objects.create(title="none2", checksum="B")
        doc3 = Document.objects.create(title="none3", checksum="C")

        tag_inbox = Tag.objects.create(name="t1", is_inbox_tag=True)

        doc1.tags.add(tag_inbox)

        response = self.client.get("/api/statistics/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['documents_total'], 3)
        self.assertEqual(response.data['documents_inbox'], 1)

    @mock.patch("documents.views.async_task")
    def test_upload(self, m):

        with open(os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"), "rb") as f:
            response = self.client.post("/api/documents/post_document/", {"document": f})

        self.assertEqual(response.status_code, 200)

        m.assert_called_once()

        args, kwargs = m.call_args
        self.assertEqual(kwargs['override_filename'], "simple.pdf")
        self.assertIsNone(kwargs['override_title'])
        self.assertIsNone(kwargs['override_correspondent_id'])
        self.assertIsNone(kwargs['override_document_type_id'])
        self.assertIsNone(kwargs['override_tag_ids'])

    @mock.patch("documents.views.async_task")
    def test_upload_empty_metadata(self, m):

        with open(os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"), "rb") as f:
            response = self.client.post("/api/documents/post_document/", {"document": f, "title": "", "correspondent": "", "document_type": ""})

        self.assertEqual(response.status_code, 200)

        m.assert_called_once()

        args, kwargs = m.call_args
        self.assertEqual(kwargs['override_filename'], "simple.pdf")
        self.assertIsNone(kwargs['override_title'])
        self.assertIsNone(kwargs['override_correspondent_id'])
        self.assertIsNone(kwargs['override_document_type_id'])
        self.assertIsNone(kwargs['override_tag_ids'])

    @mock.patch("documents.views.async_task")
    def test_upload_invalid_form(self, m):

        with open(os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"), "rb") as f:
            response = self.client.post("/api/documents/post_document/", {"documenst": f})
        self.assertEqual(response.status_code, 400)
        m.assert_not_called()

    @mock.patch("documents.views.async_task")
    def test_upload_invalid_file(self, m):

        with open(os.path.join(os.path.dirname(__file__), "samples", "simple.zip"), "rb") as f:
            response = self.client.post("/api/documents/post_document/", {"document": f})
        self.assertEqual(response.status_code, 400)
        m.assert_not_called()

    @mock.patch("documents.views.async_task")
    def test_upload_with_title(self, async_task):
        with open(os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"), "rb") as f:
            response = self.client.post("/api/documents/post_document/", {"document": f, "title": "my custom title"})
        self.assertEqual(response.status_code, 200)

        async_task.assert_called_once()

        args, kwargs = async_task.call_args

        self.assertEqual(kwargs['override_title'], "my custom title")

    @mock.patch("documents.views.async_task")
    def test_upload_with_correspondent(self, async_task):
        c = Correspondent.objects.create(name="test-corres")
        with open(os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"), "rb") as f:
            response = self.client.post("/api/documents/post_document/", {"document": f, "correspondent": c.id})
        self.assertEqual(response.status_code, 200)

        async_task.assert_called_once()

        args, kwargs = async_task.call_args

        self.assertEqual(kwargs['override_correspondent_id'], c.id)

    @mock.patch("documents.views.async_task")
    def test_upload_with_invalid_correspondent(self, async_task):
        with open(os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"), "rb") as f:
            response = self.client.post("/api/documents/post_document/", {"document": f, "correspondent": 3456})
        self.assertEqual(response.status_code, 400)

        async_task.assert_not_called()

    @mock.patch("documents.views.async_task")
    def test_upload_with_document_type(self, async_task):
        dt = DocumentType.objects.create(name="invoice")
        with open(os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"), "rb") as f:
            response = self.client.post("/api/documents/post_document/", {"document": f, "document_type": dt.id})
        self.assertEqual(response.status_code, 200)

        async_task.assert_called_once()

        args, kwargs = async_task.call_args

        self.assertEqual(kwargs['override_document_type_id'], dt.id)

    @mock.patch("documents.views.async_task")
    def test_upload_with_invalid_document_type(self, async_task):
        with open(os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"), "rb") as f:
            response = self.client.post("/api/documents/post_document/", {"document": f, "document_type": 34578})
        self.assertEqual(response.status_code, 400)

        async_task.assert_not_called()

    @mock.patch("documents.views.async_task")
    def test_upload_with_tags(self, async_task):
        t1 = Tag.objects.create(name="tag1")
        t2 = Tag.objects.create(name="tag2")
        with open(os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"), "rb") as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f, "tags": [t2.id, t1.id]})
        self.assertEqual(response.status_code, 200)

        async_task.assert_called_once()

        args, kwargs = async_task.call_args

        self.assertCountEqual(kwargs['override_tag_ids'], [t1.id, t2.id])

    @mock.patch("documents.views.async_task")
    def test_upload_with_invalid_tags(self, async_task):
        t1 = Tag.objects.create(name="tag1")
        t2 = Tag.objects.create(name="tag2")
        with open(os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"), "rb") as f:
            response = self.client.post(
                "/api/documents/post_document/",
                {"document": f, "tags": [t2.id, t1.id, 734563]})
        self.assertEqual(response.status_code, 400)

        async_task.assert_not_called()

    def test_get_metadata(self):
        doc = Document.objects.create(title="test", filename="file.pdf", mime_type="image/png", archive_checksum="A")

        shutil.copy(os.path.join(os.path.dirname(__file__), "samples", "documents", "thumbnails", "0000001.png"), doc.source_path)
        shutil.copy(os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"), doc.archive_path)

        response = self.client.get(f"/api/documents/{doc.pk}/metadata/")
        self.assertEqual(response.status_code, 200)

        meta = response.data

        self.assertEqual(meta['original_mime_type'], "image/png")
        self.assertTrue(meta['has_archive_version'])
        self.assertEqual(len(meta['original_metadata']), 0)
        self.assertGreater(len(meta['archive_metadata']), 0)

    def test_get_metadata_no_archive(self):
        doc = Document.objects.create(title="test", filename="file.pdf", mime_type="application/pdf")

        shutil.copy(os.path.join(os.path.dirname(__file__), "samples", "simple.pdf"), doc.source_path)

        response = self.client.get(f"/api/documents/{doc.pk}/metadata/")
        self.assertEqual(response.status_code, 200)

        meta = response.data

        self.assertEqual(meta['original_mime_type'], "application/pdf")
        self.assertFalse(meta['has_archive_version'])
        self.assertGreater(len(meta['original_metadata']), 0)
        self.assertIsNone(meta['archive_metadata'])

    def test_saved_views(self):
        u1 = User.objects.create_user("user1")
        u2 = User.objects.create_user("user2")

        v1 = SavedView.objects.create(user=u1, name="test1", sort_field="", show_on_dashboard=False, show_in_sidebar=False)
        v2 = SavedView.objects.create(user=u2, name="test2", sort_field="", show_on_dashboard=False, show_in_sidebar=False)
        v3 = SavedView.objects.create(user=u2, name="test3", sort_field="", show_on_dashboard=False, show_in_sidebar=False)

        response = self.client.get("/api/saved_views/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)

        self.assertEqual(self.client.get(f"/api/saved_views/{v1.id}/").status_code, 404)

        self.client.force_login(user=u1)

        response = self.client.get("/api/saved_views/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)

        self.assertEqual(self.client.get(f"/api/saved_views/{v1.id}/").status_code, 200)

        self.client.force_login(user=u2)

        response = self.client.get("/api/saved_views/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)

        self.assertEqual(self.client.get(f"/api/saved_views/{v1.id}/").status_code, 404)

    def test_create_update_patch(self):

        u1 = User.objects.create_user("user1")

        view = {
            "name": "test",
            "show_on_dashboard": True,
            "show_in_sidebar": True,
            "sort_field": "created2",
            "filter_rules": [
                {
                    "rule_type": 4,
                    "value": "test"
                }
            ]
        }

        response = self.client.post("/api/saved_views/", view, format='json')
        self.assertEqual(response.status_code, 201)

        v1 = SavedView.objects.get(name="test")
        self.assertEqual(v1.sort_field, "created2")
        self.assertEqual(v1.filter_rules.count(), 1)
        self.assertEqual(v1.user, self.user)

        response = self.client.patch(f"/api/saved_views/{v1.id}/", {
            "show_in_sidebar": False
        }, format='json')

        v1 = SavedView.objects.get(id=v1.id)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(v1.show_in_sidebar)
        self.assertEqual(v1.filter_rules.count(), 1)

        view['filter_rules'] = [{
            "rule_type": 12,
            "value": "secret"
        }]

        response = self.client.put(f"/api/saved_views/{v1.id}/", view, format='json')
        self.assertEqual(response.status_code, 200)

        v1 = SavedView.objects.get(id=v1.id)
        self.assertEqual(v1.filter_rules.count(), 1)
        self.assertEqual(v1.filter_rules.first().value, "secret")

        view['filter_rules'] = []

        response = self.client.put(f"/api/saved_views/{v1.id}/", view, format='json')
        self.assertEqual(response.status_code, 200)

        v1 = SavedView.objects.get(id=v1.id)
        self.assertEqual(v1.filter_rules.count(), 0)


class TestBulkEdit(DirectoriesMixin, APITestCase):

    def setUp(self):
        super(TestBulkEdit, self).setUp()

        user = User.objects.create_superuser(username="temp_admin")
        self.client.force_login(user=user)

        patcher = mock.patch('documents.bulk_edit.async_task')
        self.async_task = patcher.start()
        self.addCleanup(patcher.stop)
        self.c1 = Correspondent.objects.create(name="c1")
        self.c2 = Correspondent.objects.create(name="c2")
        self.dt1 = DocumentType.objects.create(name="dt1")
        self.dt2 = DocumentType.objects.create(name="dt2")
        self.t1 = Tag.objects.create(name="t1")
        self.t2 = Tag.objects.create(name="t2")
        self.doc1 = Document.objects.create(checksum="A", title="A")
        self.doc2 = Document.objects.create(checksum="B", title="B", correspondent=self.c1, document_type=self.dt1)
        self.doc3 = Document.objects.create(checksum="C", title="C", correspondent=self.c2, document_type=self.dt2)
        self.doc4 = Document.objects.create(checksum="D", title="D")
        self.doc5 = Document.objects.create(checksum="E", title="E")
        self.doc2.tags.add(self.t1)
        self.doc3.tags.add(self.t2)
        self.doc4.tags.add(self.t1, self.t2)

    def test_set_correspondent(self):
        self.assertEqual(Document.objects.filter(correspondent=self.c2).count(), 1)
        bulk_edit.set_correspondent([self.doc1.id, self.doc2.id, self.doc3.id], self.c2.id)
        self.assertEqual(Document.objects.filter(correspondent=self.c2).count(), 3)
        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        self.assertCountEqual(kwargs['document_ids'], [self.doc1.id, self.doc2.id])

    def test_unset_correspondent(self):
        self.assertEqual(Document.objects.filter(correspondent=self.c2).count(), 1)
        bulk_edit.set_correspondent([self.doc1.id, self.doc2.id, self.doc3.id], None)
        self.assertEqual(Document.objects.filter(correspondent=self.c2).count(), 0)
        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        self.assertCountEqual(kwargs['document_ids'], [self.doc2.id, self.doc3.id])

    def test_set_document_type(self):
        self.assertEqual(Document.objects.filter(document_type=self.dt2).count(), 1)
        bulk_edit.set_document_type([self.doc1.id, self.doc2.id, self.doc3.id], self.dt2.id)
        self.assertEqual(Document.objects.filter(document_type=self.dt2).count(), 3)
        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        self.assertCountEqual(kwargs['document_ids'], [self.doc1.id, self.doc2.id])

    def test_unset_document_type(self):
        self.assertEqual(Document.objects.filter(document_type=self.dt2).count(), 1)
        bulk_edit.set_document_type([self.doc1.id, self.doc2.id, self.doc3.id], None)
        self.assertEqual(Document.objects.filter(document_type=self.dt2).count(), 0)
        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        self.assertCountEqual(kwargs['document_ids'], [self.doc2.id, self.doc3.id])

    def test_add_tag(self):
        self.assertEqual(Document.objects.filter(tags__id=self.t1.id).count(), 2)
        bulk_edit.add_tag([self.doc1.id, self.doc2.id, self.doc3.id, self.doc4.id], self.t1.id)
        self.assertEqual(Document.objects.filter(tags__id=self.t1.id).count(), 4)
        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        self.assertCountEqual(kwargs['document_ids'], [self.doc1.id, self.doc3.id])

    def test_remove_tag(self):
        self.assertEqual(Document.objects.filter(tags__id=self.t1.id).count(), 2)
        bulk_edit.remove_tag([self.doc1.id, self.doc3.id, self.doc4.id], self.t1.id)
        self.assertEqual(Document.objects.filter(tags__id=self.t1.id).count(), 1)
        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        self.assertCountEqual(kwargs['document_ids'], [self.doc4.id])

    def test_modify_tags(self):
        tag_unrelated = Tag.objects.create(name="unrelated")
        self.doc2.tags.add(tag_unrelated)
        self.doc3.tags.add(tag_unrelated)
        bulk_edit.modify_tags([self.doc2.id, self.doc3.id], add_tags=[self.t2.id], remove_tags=[self.t1.id])

        self.assertCountEqual(list(self.doc2.tags.all()), [self.t2, tag_unrelated])
        self.assertCountEqual(list(self.doc3.tags.all()), [self.t2, tag_unrelated])

        self.async_task.assert_called_once()
        args, kwargs = self.async_task.call_args
        # TODO: doc3 should not be affected, but the query for that is rather complicated
        self.assertCountEqual(kwargs['document_ids'], [self.doc2.id, self.doc3.id])

    def test_delete(self):
        self.assertEqual(Document.objects.count(), 5)
        bulk_edit.delete([self.doc1.id, self.doc2.id])
        self.assertEqual(Document.objects.count(), 3)
        self.assertCountEqual([doc.id for doc in Document.objects.all()], [self.doc3.id, self.doc4.id, self.doc5.id])

    @mock.patch("documents.serialisers.bulk_edit.set_correspondent")
    def test_api_set_correspondent(self, m):
        m.return_value = "OK"
        response = self.client.post("/api/documents/bulk_edit/", json.dumps({
            "documents": [self.doc1.id],
            "method": "set_correspondent",
            "parameters": {"correspondent": self.c1.id}
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        m.assert_called_once()
        args, kwargs = m.call_args
        self.assertEqual(args[0], [self.doc1.id])
        self.assertEqual(kwargs['correspondent'], self.c1.id)

    @mock.patch("documents.serialisers.bulk_edit.set_correspondent")
    def test_api_unset_correspondent(self, m):
        m.return_value = "OK"
        response = self.client.post("/api/documents/bulk_edit/", json.dumps({
            "documents": [self.doc1.id],
            "method": "set_correspondent",
            "parameters": {"correspondent": None}
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        m.assert_called_once()
        args, kwargs = m.call_args
        self.assertEqual(args[0], [self.doc1.id])
        self.assertIsNone(kwargs['correspondent'])

    @mock.patch("documents.serialisers.bulk_edit.set_document_type")
    def test_api_set_type(self, m):
        m.return_value = "OK"
        response = self.client.post("/api/documents/bulk_edit/", json.dumps({
            "documents": [self.doc1.id],
            "method": "set_document_type",
            "parameters": {"document_type": self.dt1.id}
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        m.assert_called_once()
        args, kwargs = m.call_args
        self.assertEqual(args[0], [self.doc1.id])
        self.assertEqual(kwargs['document_type'], self.dt1.id)

    @mock.patch("documents.serialisers.bulk_edit.set_document_type")
    def test_api_unset_type(self, m):
        m.return_value = "OK"
        response = self.client.post("/api/documents/bulk_edit/", json.dumps({
            "documents": [self.doc1.id],
            "method": "set_document_type",
            "parameters": {"document_type": None}
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        m.assert_called_once()
        args, kwargs = m.call_args
        self.assertEqual(args[0], [self.doc1.id])
        self.assertIsNone(kwargs['document_type'])

    @mock.patch("documents.serialisers.bulk_edit.add_tag")
    def test_api_add_tag(self, m):
        m.return_value = "OK"
        response = self.client.post("/api/documents/bulk_edit/", json.dumps({
            "documents": [self.doc1.id],
            "method": "add_tag",
            "parameters": {"tag": self.t1.id}
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        m.assert_called_once()
        args, kwargs = m.call_args
        self.assertEqual(args[0], [self.doc1.id])
        self.assertEqual(kwargs['tag'], self.t1.id)

    @mock.patch("documents.serialisers.bulk_edit.remove_tag")
    def test_api_remove_tag(self, m):
        m.return_value = "OK"
        response = self.client.post("/api/documents/bulk_edit/", json.dumps({
            "documents": [self.doc1.id],
            "method": "remove_tag",
            "parameters": {"tag": self.t1.id}
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        m.assert_called_once()
        args, kwargs = m.call_args
        self.assertEqual(args[0], [self.doc1.id])
        self.assertEqual(kwargs['tag'], self.t1.id)

    @mock.patch("documents.serialisers.bulk_edit.modify_tags")
    def test_api_modify_tags(self, m):
        m.return_value = "OK"
        response = self.client.post("/api/documents/bulk_edit/", json.dumps({
            "documents": [self.doc1.id, self.doc3.id],
            "method": "modify_tags",
            "parameters": {"add_tags": [self.t1.id], "remove_tags": [self.t2.id]}
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        m.assert_called_once()
        args, kwargs = m.call_args
        self.assertListEqual(args[0], [self.doc1.id, self.doc3.id])
        self.assertEqual(kwargs['add_tags'], [self.t1.id])
        self.assertEqual(kwargs['remove_tags'], [self.t2.id])

    @mock.patch("documents.serialisers.bulk_edit.delete")
    def test_api_delete(self, m):
        m.return_value = "OK"
        response = self.client.post("/api/documents/bulk_edit/", json.dumps({
            "documents": [self.doc1.id],
            "method": "delete",
            "parameters": {}
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        m.assert_called_once()
        args, kwargs = m.call_args
        self.assertEqual(args[0], [self.doc1.id])
        self.assertEqual(len(kwargs), 0)

    def test_api_invalid_doc(self):
        self.assertEqual(Document.objects.count(), 5)
        response = self.client.post("/api/documents/bulk_edit/", json.dumps({
            "documents": [-235],
            "method": "delete",
            "parameters": {}
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Document.objects.count(), 5)

    def test_api_invalid_method(self):
        self.assertEqual(Document.objects.count(), 5)
        response = self.client.post("/api/documents/bulk_edit/", json.dumps({
            "documents": [self.doc2.id],
            "method": "exterminate",
            "parameters": {}
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Document.objects.count(), 5)

    def test_api_invalid_correspondent(self):
        self.assertEqual(self.doc2.correspondent, self.c1)
        response = self.client.post("/api/documents/bulk_edit/", json.dumps({
            "documents": [self.doc2.id],
            "method": "set_correspondent",
            "parameters": {'correspondent': 345657}
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)

        doc2 = Document.objects.get(id=self.doc2.id)
        self.assertEqual(doc2.correspondent, self.c1)

    def test_api_invalid_document_type(self):
        self.assertEqual(self.doc2.document_type, self.dt1)
        response = self.client.post("/api/documents/bulk_edit/", json.dumps({
            "documents": [self.doc2.id],
            "method": "set_document_type",
            "parameters": {'document_type': 345657}
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)

        doc2 = Document.objects.get(id=self.doc2.id)
        self.assertEqual(doc2.document_type, self.dt1)

    def test_api_add_invalid_tag(self):
        self.assertEqual(list(self.doc2.tags.all()), [self.t1])
        response = self.client.post("/api/documents/bulk_edit/", json.dumps({
            "documents": [self.doc2.id],
            "method": "add_tag",
            "parameters": {'tag': 345657}
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)

        self.assertEqual(list(self.doc2.tags.all()), [self.t1])

    def test_api_delete_invalid_tag(self):
        self.assertEqual(list(self.doc2.tags.all()), [self.t1])
        response = self.client.post("/api/documents/bulk_edit/", json.dumps({
            "documents": [self.doc2.id],
            "method": "remove_tag",
            "parameters": {'tag': 345657}
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)

        self.assertEqual(list(self.doc2.tags.all()), [self.t1])

    def test_api_modify_invalid_tags(self):
        self.assertEqual(list(self.doc2.tags.all()), [self.t1])
        response = self.client.post("/api/documents/bulk_edit/", json.dumps({
            "documents": [self.doc2.id],
            "method": "modify_tags",
            "parameters": {'add_tags': [self.t2.id, 1657], "remove_tags": [1123123]}
        }), content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_api_selection_data_empty(self):
        response = self.client.post("/api/documents/selection_data/", json.dumps({
            "documents": []
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        for field, Entity in [('selected_correspondents', Correspondent), ('selected_tags', Tag), ('selected_document_types', DocumentType)]:
            self.assertEqual(len(response.data[field]), Entity.objects.count())
            for correspondent in response.data[field]:
                self.assertEqual(correspondent['document_count'], 0)
            self.assertCountEqual(
                map(lambda c: c['id'], response.data[field]),
                map(lambda c: c['id'], Entity.objects.values('id')))

    def test_api_selection_data(self):
        response = self.client.post("/api/documents/selection_data/", json.dumps({
            "documents": [self.doc1.id, self.doc2.id, self.doc4.id, self.doc5.id]
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)

        self.assertCountEqual(response.data['selected_correspondents'], [{"id": self.c1.id, "document_count": 1}, {"id": self.c2.id, "document_count": 0}])
        self.assertCountEqual(response.data['selected_tags'], [{"id": self.t1.id, "document_count": 2}, {"id": self.t2.id, "document_count": 1}])
        self.assertCountEqual(response.data['selected_document_types'], [{"id": self.c1.id, "document_count": 1}, {"id": self.c2.id, "document_count": 0}])


class TestApiAuth(APITestCase):

    def test_auth_required(self):

        d = Document.objects.create(title="Test")

        self.assertEqual(self.client.get("/api/documents/").status_code, 401)

        self.assertEqual(self.client.get(f"/api/documents/{d.id}/").status_code, 401)
        self.assertEqual(self.client.get(f"/api/documents/{d.id}/download/").status_code, 401)
        self.assertEqual(self.client.get(f"/api/documents/{d.id}/preview/").status_code, 401)
        self.assertEqual(self.client.get(f"/api/documents/{d.id}/thumb/").status_code, 401)

        self.assertEqual(self.client.get("/api/tags/").status_code, 401)
        self.assertEqual(self.client.get("/api/correspondents/").status_code, 401)
        self.assertEqual(self.client.get("/api/document_types/").status_code, 401)

        self.assertEqual(self.client.get("/api/logs/").status_code, 401)
        self.assertEqual(self.client.get("/api/saved_views/").status_code, 401)

        self.assertEqual(self.client.get("/api/search/").status_code, 401)
        self.assertEqual(self.client.get("/api/search/auto_complete/").status_code, 401)
        self.assertEqual(self.client.get("/api/documents/bulk_edit/").status_code, 401)
        self.assertEqual(self.client.get("/api/documents/selection_data/").status_code, 401)
