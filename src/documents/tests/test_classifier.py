import tempfile
from time import sleep
from unittest import mock

from django.test import TestCase, override_settings

from documents.classifier import DocumentClassifier, IncompatibleClassifierVersionError
from documents.models import Correspondent, Document, Tag, DocumentType


class TestClassifier(TestCase):

    def setUp(self):

        self.classifier = DocumentClassifier()

    def generate_test_data(self):
        self.c1 = Correspondent.objects.create(name="c1", matching_algorithm=Correspondent.MATCH_AUTO)
        self.c2 = Correspondent.objects.create(name="c2")
        self.c3 = Correspondent.objects.create(name="c3", matching_algorithm=Correspondent.MATCH_AUTO)
        self.t1 = Tag.objects.create(name="t1", matching_algorithm=Tag.MATCH_AUTO, pk=12)
        self.t2 = Tag.objects.create(name="t2", matching_algorithm=Tag.MATCH_ANY, pk=34, is_inbox_tag=True)
        self.t3 = Tag.objects.create(name="t3", matching_algorithm=Tag.MATCH_AUTO, pk=45)
        self.dt = DocumentType.objects.create(name="dt", matching_algorithm=DocumentType.MATCH_AUTO)
        self.dt2 = DocumentType.objects.create(name="dt2", matching_algorithm=DocumentType.MATCH_AUTO)

        self.doc1 = Document.objects.create(title="doc1", content="this is a document from c1", correspondent=self.c1, checksum="A", document_type=self.dt)
        self.doc2 = Document.objects.create(title="doc1", content="this is another document, but from c2", correspondent=self.c2, checksum="B")
        self.doc_inbox = Document.objects.create(title="doc235", content="aa", checksum="C")

        self.doc1.tags.add(self.t1)
        self.doc2.tags.add(self.t1)
        self.doc2.tags.add(self.t3)
        self.doc_inbox.tags.add(self.t2)

    def testNoTrainingData(self):
        try:
            self.classifier.train()
        except ValueError as e:
            self.assertEqual(str(e), "No training data available.")
        else:
            self.fail("Should raise exception")

    def testEmpty(self):
        Document.objects.create(title="WOW", checksum="3457", content="ASD")
        self.classifier.train()
        self.assertIsNone(self.classifier.document_type_classifier)
        self.assertIsNone(self.classifier.tags_classifier)
        self.assertIsNone(self.classifier.correspondent_classifier)

        self.assertListEqual(self.classifier.predict_tags(""), [])
        self.assertIsNone(self.classifier.predict_document_type(""))
        self.assertIsNone(self.classifier.predict_correspondent(""))

    def testTrain(self):
        self.generate_test_data()
        self.classifier.train()
        self.assertListEqual(list(self.classifier.correspondent_classifier.classes_), [-1, self.c1.pk])
        self.assertListEqual(list(self.classifier.tags_binarizer.classes_), [self.t1.pk, self.t3.pk])

    def testPredict(self):
        self.generate_test_data()
        self.classifier.train()
        self.assertEqual(self.classifier.predict_correspondent(self.doc1.content), self.c1.pk)
        self.assertEqual(self.classifier.predict_correspondent(self.doc2.content), None)
        self.assertListEqual(self.classifier.predict_tags(self.doc1.content), [self.t1.pk])
        self.assertListEqual(self.classifier.predict_tags(self.doc2.content), [self.t1.pk, self.t3.pk])
        self.assertEqual(self.classifier.predict_document_type(self.doc1.content), self.dt.pk)
        self.assertEqual(self.classifier.predict_document_type(self.doc2.content), None)

    def testDatasetHashing(self):

        self.generate_test_data()

        self.assertTrue(self.classifier.train())
        self.assertFalse(self.classifier.train())

    def testVersionIncreased(self):

        self.generate_test_data()
        self.assertTrue(self.classifier.train())
        self.assertFalse(self.classifier.train())

        classifier2 = DocumentClassifier()

        current_ver = DocumentClassifier.FORMAT_VERSION
        with mock.patch("documents.classifier.DocumentClassifier.FORMAT_VERSION", current_ver+1):
            # assure that we won't load old classifiers.
            self.assertRaises(IncompatibleClassifierVersionError, self.classifier.reload)

            self.classifier.save_classifier()

            # assure that we can load the classifier after saving it.
            classifier2.reload()

    def testReload(self):

        self.generate_test_data()
        self.assertTrue(self.classifier.train())
        self.classifier.save_classifier()

        classifier2 = DocumentClassifier()
        classifier2.reload()
        v1 = classifier2.classifier_version

        # change the classifier after some time.
        sleep(1)
        self.classifier.save_classifier()

        classifier2.reload()
        v2 = classifier2.classifier_version
        self.assertNotEqual(v1, v2)

    @override_settings(DATA_DIR=tempfile.mkdtemp())
    def testSaveClassifier(self):

        self.generate_test_data()

        self.classifier.train()

        self.classifier.save_classifier()

        new_classifier = DocumentClassifier()
        new_classifier.reload()
        self.assertFalse(new_classifier.train())

    def test_one_correspondent_predict(self):
        c1 = Correspondent.objects.create(name="c1", matching_algorithm=Correspondent.MATCH_AUTO)
        doc1 = Document.objects.create(title="doc1", content="this is a document from c1", correspondent=c1, checksum="A")

        self.classifier.train()
        self.assertEqual(self.classifier.predict_correspondent(doc1.content), c1.pk)

    def test_one_correspondent_predict_manydocs(self):
        c1 = Correspondent.objects.create(name="c1", matching_algorithm=Correspondent.MATCH_AUTO)
        doc1 = Document.objects.create(title="doc1", content="this is a document from c1", correspondent=c1, checksum="A")
        doc2 = Document.objects.create(title="doc2", content="this is a document from noone", checksum="B")

        self.classifier.train()
        self.assertEqual(self.classifier.predict_correspondent(doc1.content), c1.pk)
        self.assertIsNone(self.classifier.predict_correspondent(doc2.content))

    def test_one_type_predict(self):
        dt = DocumentType.objects.create(name="dt", matching_algorithm=DocumentType.MATCH_AUTO)

        doc1 = Document.objects.create(title="doc1", content="this is a document from c1",
                                            checksum="A", document_type=dt)

        self.classifier.train()
        self.assertEqual(self.classifier.predict_document_type(doc1.content), dt.pk)

    def test_one_type_predict_manydocs(self):
        dt = DocumentType.objects.create(name="dt", matching_algorithm=DocumentType.MATCH_AUTO)

        doc1 = Document.objects.create(title="doc1", content="this is a document from c1",
                                            checksum="A", document_type=dt)

        doc2 = Document.objects.create(title="doc1", content="this is a document from c2",
                                            checksum="B")

        self.classifier.train()
        self.assertEqual(self.classifier.predict_document_type(doc1.content), dt.pk)
        self.assertIsNone(self.classifier.predict_document_type(doc2.content))

    def test_one_tag_predict(self):
        t1 = Tag.objects.create(name="t1", matching_algorithm=Tag.MATCH_AUTO, pk=12)

        doc1 = Document.objects.create(title="doc1", content="this is a document from c1", checksum="A")

        doc1.tags.add(t1)
        self.classifier.train()
        self.assertListEqual(self.classifier.predict_tags(doc1.content), [t1.pk])

    def test_one_tag_predict_unassigned(self):
        t1 = Tag.objects.create(name="t1", matching_algorithm=Tag.MATCH_AUTO, pk=12)

        doc1 = Document.objects.create(title="doc1", content="this is a document from c1", checksum="A")

        self.classifier.train()
        self.assertListEqual(self.classifier.predict_tags(doc1.content), [])

    def test_two_tags_predict_singledoc(self):
        t1 = Tag.objects.create(name="t1", matching_algorithm=Tag.MATCH_AUTO, pk=12)
        t2 = Tag.objects.create(name="t2", matching_algorithm=Tag.MATCH_AUTO, pk=121)

        doc4 = Document.objects.create(title="doc1", content="this is a document from c4", checksum="D")

        doc4.tags.add(t1)
        doc4.tags.add(t2)
        self.classifier.train()
        self.assertListEqual(self.classifier.predict_tags(doc4.content), [t1.pk, t2.pk])

    def test_two_tags_predict(self):
        t1 = Tag.objects.create(name="t1", matching_algorithm=Tag.MATCH_AUTO, pk=12)
        t2 = Tag.objects.create(name="t2", matching_algorithm=Tag.MATCH_AUTO, pk=121)

        doc1 = Document.objects.create(title="doc1", content="this is a document from c1", checksum="A")
        doc2 = Document.objects.create(title="doc1", content="this is a document from c2", checksum="B")
        doc3 = Document.objects.create(title="doc1", content="this is a document from c3", checksum="C")
        doc4 = Document.objects.create(title="doc1", content="this is a document from c4", checksum="D")

        doc1.tags.add(t1)
        doc2.tags.add(t2)

        doc4.tags.add(t1)
        doc4.tags.add(t2)
        self.classifier.train()
        self.assertListEqual(self.classifier.predict_tags(doc1.content), [t1.pk])
        self.assertListEqual(self.classifier.predict_tags(doc2.content), [t2.pk])
        self.assertListEqual(self.classifier.predict_tags(doc3.content), [])
        self.assertListEqual(self.classifier.predict_tags(doc4.content), [t1.pk, t2.pk])

    def test_one_tag_predict_multi(self):
        t1 = Tag.objects.create(name="t1", matching_algorithm=Tag.MATCH_AUTO, pk=12)

        doc1 = Document.objects.create(title="doc1", content="this is a document from c1", checksum="A")
        doc2 = Document.objects.create(title="doc2", content="this is a document from c2", checksum="B")

        doc1.tags.add(t1)
        doc2.tags.add(t1)
        self.classifier.train()
        self.assertListEqual(self.classifier.predict_tags(doc1.content), [t1.pk])
        self.assertListEqual(self.classifier.predict_tags(doc2.content), [t1.pk])

    def test_one_tag_predict_multi_2(self):
        t1 = Tag.objects.create(name="t1", matching_algorithm=Tag.MATCH_AUTO, pk=12)

        doc1 = Document.objects.create(title="doc1", content="this is a document from c1", checksum="A")
        doc2 = Document.objects.create(title="doc2", content="this is a document from c2", checksum="B")

        doc1.tags.add(t1)
        self.classifier.train()
        self.assertListEqual(self.classifier.predict_tags(doc1.content), [t1.pk])
        self.assertListEqual(self.classifier.predict_tags(doc2.content), [])
