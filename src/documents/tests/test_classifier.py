import re
import shutil
from pathlib import Path
from unittest import mock

import pytest
from django.conf import settings
from django.test import TestCase
from django.test import override_settings

from documents.classifier import ClassifierModelCorruptError
from documents.classifier import DocumentClassifier
from documents.classifier import IncompatibleClassifierVersionError
from documents.classifier import load_classifier
from documents.models import Correspondent
from documents.models import Document
from documents.models import DocumentType
from documents.models import MatchingModel
from documents.models import StoragePath
from documents.models import Tag
from documents.tests.utils import DirectoriesMixin


def dummy_preprocess(content: str):
    """
    Simpler, faster pre-processing for testing purposes
    """
    content = content.lower().strip()
    content = re.sub(r"\s+", " ", content)
    return content


class TestClassifier(DirectoriesMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.classifier = DocumentClassifier()
        self.classifier.preprocess_content = mock.MagicMock(
            side_effect=dummy_preprocess,
        )

    def generate_test_data(self):
        self.c1 = Correspondent.objects.create(
            name="c1",
            matching_algorithm=Correspondent.MATCH_AUTO,
        )
        self.c2 = Correspondent.objects.create(name="c2")
        self.c3 = Correspondent.objects.create(
            name="c3",
            matching_algorithm=Correspondent.MATCH_AUTO,
        )

        self.t1 = Tag.objects.create(
            name="t1",
            matching_algorithm=Tag.MATCH_AUTO,
            pk=12,
        )
        self.t2 = Tag.objects.create(
            name="t2",
            matching_algorithm=Tag.MATCH_ANY,
            pk=34,
            is_inbox_tag=True,
        )
        self.t3 = Tag.objects.create(
            name="t3",
            matching_algorithm=Tag.MATCH_AUTO,
            pk=45,
        )
        self.t4 = Tag.objects.create(
            name="t4",
            matching_algorithm=Tag.MATCH_ANY,
            pk=46,
        )

        self.dt = DocumentType.objects.create(
            name="dt",
            matching_algorithm=DocumentType.MATCH_AUTO,
        )
        self.dt2 = DocumentType.objects.create(
            name="dt2",
            matching_algorithm=DocumentType.MATCH_AUTO,
        )

        self.sp1 = StoragePath.objects.create(
            name="sp1",
            path="path1",
            matching_algorithm=DocumentType.MATCH_AUTO,
        )
        self.sp2 = StoragePath.objects.create(
            name="sp2",
            path="path2",
            matching_algorithm=DocumentType.MATCH_AUTO,
        )
        self.store_paths = [self.sp1, self.sp2]

        self.doc1 = Document.objects.create(
            title="doc1",
            content="this is a document from c1",
            correspondent=self.c1,
            checksum="A",
            document_type=self.dt,
            storage_path=self.sp1,
        )

        self.doc2 = Document.objects.create(
            title="doc1",
            content="this is another document, but from c2",
            correspondent=self.c2,
            checksum="B",
        )

        self.doc_inbox = Document.objects.create(
            title="doc235",
            content="aa",
            checksum="C",
        )

        self.doc1.tags.add(self.t1)
        self.doc2.tags.add(self.t1)
        self.doc2.tags.add(self.t3)
        self.doc_inbox.tags.add(self.t2)

    def generate_train_and_save(self):
        """
        Generates the training data, trains and saves the updated pickle
        file. This ensures the test is using the same scikit learn version
        and eliminates a warning from the test suite
        """
        self.generate_test_data()
        self.classifier.train()
        self.classifier.save()

    def test_no_training_data(self):
        """
        GIVEN:
            - No documents exist to train
        WHEN:
            - Classifier training is requested
        THEN:
            - Exception is raised
        """
        with self.assertRaisesMessage(ValueError, "No training data available."):
            self.classifier.train()

    def test_no_non_inbox_tags(self):
        """
        GIVEN:
            - No documents without an inbox tag exist
        WHEN:
            - Classifier training is requested
        THEN:
            - Exception is raised
        """

        t1 = Tag.objects.create(
            name="t1",
            matching_algorithm=Tag.MATCH_ANY,
            pk=34,
            is_inbox_tag=True,
        )

        doc1 = Document.objects.create(
            title="doc1",
            content="this is a document from c1",
            checksum="A",
        )
        doc1.tags.add(t1)

        with self.assertRaisesMessage(ValueError, "No training data available."):
            self.classifier.train()

    def testEmpty(self):
        """
        GIVEN:
            - A document exists
            - No tags/not enough data to predict
        WHEN:
            - Classifier prediction is requested
        THEN:
            - Classifier returns no predictions
        """
        Document.objects.create(title="WOW", checksum="3457", content="ASD")
        self.classifier.train()

        self.assertIsNone(self.classifier.document_type_classifier)
        self.assertIsNone(self.classifier.tags_classifier)
        self.assertIsNone(self.classifier.correspondent_classifier)

        self.assertListEqual(self.classifier.predict_tags(""), [])
        self.assertIsNone(self.classifier.predict_document_type(""))
        self.assertIsNone(self.classifier.predict_correspondent(""))

    def testTrain(self):
        """
        GIVEN:
            - Test data
        WHEN:
            - Classifier is trained
        THEN:
            - Classifier uses correct values for correspondent learning
            - Classifier uses correct values for tags learning
        """
        self.generate_test_data()
        self.classifier.train()

        self.assertListEqual(
            list(self.classifier.correspondent_classifier.classes_),
            [-1, self.c1.pk],
        )
        self.assertListEqual(
            list(self.classifier.tags_binarizer.classes_),
            [self.t1.pk, self.t3.pk],
        )

    def testPredict(self):
        """
        GIVEN:
            - Classifier trained against test data
        WHEN:
            - Prediction requested for correspondent, tags, type
        THEN:
            - Expected predictions based on training set
        """
        self.generate_test_data()
        self.classifier.train()

        self.assertEqual(
            self.classifier.predict_correspondent(self.doc1.content),
            self.c1.pk,
        )
        self.assertEqual(self.classifier.predict_correspondent(self.doc2.content), None)
        self.assertListEqual(
            self.classifier.predict_tags(self.doc1.content),
            [self.t1.pk],
        )
        self.assertListEqual(
            self.classifier.predict_tags(self.doc2.content),
            [self.t1.pk, self.t3.pk],
        )
        self.assertEqual(
            self.classifier.predict_document_type(self.doc1.content),
            self.dt.pk,
        )
        self.assertEqual(self.classifier.predict_document_type(self.doc2.content), None)

    def test_no_retrain_if_no_change(self):
        """
        GIVEN:
            - Classifier trained with current data
        WHEN:
            - Classifier training is requested again
        THEN:
            - Classifier does not redo training
        """

        self.generate_test_data()

        self.assertTrue(self.classifier.train())
        self.assertFalse(self.classifier.train())

    def test_retrain_if_change(self):
        """
        GIVEN:
            - Classifier trained with current data
        WHEN:
            - Classifier training is requested again
            - Documents have changed
        THEN:
            - Classifier does not redo training
        """

        self.generate_test_data()

        self.assertTrue(self.classifier.train())

        self.doc1.correspondent = self.c2
        self.doc1.save()

        self.assertTrue(self.classifier.train())

    def test_retrain_if_auto_match_set_changed(self):
        """
        GIVEN:
            - Classifier trained with current data
        WHEN:
            - Classifier training is requested again
            - Some new AUTO match object exists
        THEN:
            - Classifier does redo training
        """
        self.generate_test_data()
        # Add the ANY type
        self.doc1.tags.add(self.t4)

        self.assertTrue(self.classifier.train())

        # Change the matching type
        self.t4.matching_algorithm = MatchingModel.MATCH_AUTO
        self.t4.save()

        self.assertTrue(self.classifier.train())

    def testVersionIncreased(self):
        """
        GIVEN:
            - Existing classifier model saved at a version
        WHEN:
            - Attempt to load classifier file from newer version
        THEN:
            - Exception is raised
        """
        self.generate_train_and_save()

        classifier2 = DocumentClassifier()

        current_ver = DocumentClassifier.FORMAT_VERSION
        with mock.patch(
            "documents.classifier.DocumentClassifier.FORMAT_VERSION",
            current_ver + 1,
        ):
            # assure that we won't load old classifiers.
            self.assertRaises(IncompatibleClassifierVersionError, classifier2.load)

            self.classifier.save()

            # assure that we can load the classifier after saving it.
            classifier2.load()

    def testSaveClassifier(self):
        self.generate_train_and_save()

        new_classifier = DocumentClassifier()
        new_classifier.load()
        new_classifier.preprocess_content = mock.MagicMock(side_effect=dummy_preprocess)

        self.assertFalse(new_classifier.train())

    def test_load_and_classify(self):
        self.generate_train_and_save()

        new_classifier = DocumentClassifier()
        new_classifier.load()
        new_classifier.preprocess_content = mock.MagicMock(side_effect=dummy_preprocess)

        self.assertCountEqual(new_classifier.predict_tags(self.doc2.content), [45, 12])

    @mock.patch("documents.classifier.pickle.load")
    def test_load_corrupt_file(self, patched_pickle_load: mock.MagicMock):
        """
        GIVEN:
            - Corrupted classifier pickle file
        WHEN:
            - An attempt is made to load the classifier
        THEN:
            - The ClassifierModelCorruptError is raised
        """
        self.generate_train_and_save()

        # First load is the schema version,allow it
        patched_pickle_load.side_effect = [DocumentClassifier.FORMAT_VERSION, OSError()]

        with self.assertRaises(ClassifierModelCorruptError):
            self.classifier.load()
            patched_pickle_load.assert_called()

        patched_pickle_load.reset_mock()
        patched_pickle_load.side_effect = [
            DocumentClassifier.FORMAT_VERSION,
            ClassifierModelCorruptError(),
        ]

        self.assertIsNone(load_classifier())
        patched_pickle_load.assert_called()

    def test_load_new_scikit_learn_version(self):
        """
        GIVEN:
            - classifier pickle file created with a different scikit-learn version
        WHEN:
            - An attempt is made to load the classifier
        THEN:
            - The classifier reports the warning was captured and processed
        """
        # TODO: This wasn't testing the warning anymore, as the schema changed
        # but as it was implemented, it would require installing an old version
        # rebuilding the file and committing that.  Not developer friendly
        # Need to rethink how to pass the load through to a file with a single
        # old model?

    def test_one_correspondent_predict(self):
        c1 = Correspondent.objects.create(
            name="c1",
            matching_algorithm=Correspondent.MATCH_AUTO,
        )
        doc1 = Document.objects.create(
            title="doc1",
            content="this is a document from c1",
            correspondent=c1,
            checksum="A",
        )

        self.classifier.train()
        self.assertEqual(self.classifier.predict_correspondent(doc1.content), c1.pk)

    def test_one_correspondent_predict_manydocs(self):
        c1 = Correspondent.objects.create(
            name="c1",
            matching_algorithm=Correspondent.MATCH_AUTO,
        )
        doc1 = Document.objects.create(
            title="doc1",
            content="this is a document from c1",
            correspondent=c1,
            checksum="A",
        )
        doc2 = Document.objects.create(
            title="doc2",
            content="this is a document from no one",
            checksum="B",
        )

        self.classifier.train()
        self.assertEqual(self.classifier.predict_correspondent(doc1.content), c1.pk)
        self.assertIsNone(self.classifier.predict_correspondent(doc2.content))

    def test_one_type_predict(self):
        dt = DocumentType.objects.create(
            name="dt",
            matching_algorithm=DocumentType.MATCH_AUTO,
        )

        doc1 = Document.objects.create(
            title="doc1",
            content="this is a document from c1",
            checksum="A",
            document_type=dt,
        )

        self.classifier.train()
        self.assertEqual(self.classifier.predict_document_type(doc1.content), dt.pk)

    def test_one_type_predict_manydocs(self):
        dt = DocumentType.objects.create(
            name="dt",
            matching_algorithm=DocumentType.MATCH_AUTO,
        )

        doc1 = Document.objects.create(
            title="doc1",
            content="this is a document from c1",
            checksum="A",
            document_type=dt,
        )

        doc2 = Document.objects.create(
            title="doc1",
            content="this is a document from c2",
            checksum="B",
        )

        self.classifier.train()
        self.assertEqual(self.classifier.predict_document_type(doc1.content), dt.pk)
        self.assertIsNone(self.classifier.predict_document_type(doc2.content))

    def test_one_path_predict(self):
        sp = StoragePath.objects.create(
            name="sp",
            matching_algorithm=StoragePath.MATCH_AUTO,
        )

        doc1 = Document.objects.create(
            title="doc1",
            content="this is a document from c1",
            checksum="A",
            storage_path=sp,
        )

        self.classifier.train()
        self.assertEqual(self.classifier.predict_storage_path(doc1.content), sp.pk)

    def test_one_path_predict_manydocs(self):
        sp = StoragePath.objects.create(
            name="sp",
            matching_algorithm=StoragePath.MATCH_AUTO,
        )

        doc1 = Document.objects.create(
            title="doc1",
            content="this is a document from c1",
            checksum="A",
            storage_path=sp,
        )

        doc2 = Document.objects.create(
            title="doc1",
            content="this is a document from c2",
            checksum="B",
        )

        self.classifier.train()
        self.assertEqual(self.classifier.predict_storage_path(doc1.content), sp.pk)
        self.assertIsNone(self.classifier.predict_storage_path(doc2.content))

    def test_one_tag_predict(self):
        t1 = Tag.objects.create(name="t1", matching_algorithm=Tag.MATCH_AUTO, pk=12)

        doc1 = Document.objects.create(
            title="doc1",
            content="this is a document from c1",
            checksum="A",
        )

        doc1.tags.add(t1)
        self.classifier.train()
        self.assertListEqual(self.classifier.predict_tags(doc1.content), [t1.pk])

    def test_one_tag_predict_unassigned(self):
        Tag.objects.create(name="t1", matching_algorithm=Tag.MATCH_AUTO, pk=12)

        doc1 = Document.objects.create(
            title="doc1",
            content="this is a document from c1",
            checksum="A",
        )

        self.classifier.train()
        self.assertListEqual(self.classifier.predict_tags(doc1.content), [])

    def test_two_tags_predict_singledoc(self):
        t1 = Tag.objects.create(name="t1", matching_algorithm=Tag.MATCH_AUTO, pk=12)
        t2 = Tag.objects.create(name="t2", matching_algorithm=Tag.MATCH_AUTO, pk=121)

        doc4 = Document.objects.create(
            title="doc1",
            content="this is a document from c4",
            checksum="D",
        )

        doc4.tags.add(t1)
        doc4.tags.add(t2)
        self.classifier.train()
        self.assertListEqual(self.classifier.predict_tags(doc4.content), [t1.pk, t2.pk])

    def test_two_tags_predict(self):
        t1 = Tag.objects.create(name="t1", matching_algorithm=Tag.MATCH_AUTO, pk=12)
        t2 = Tag.objects.create(name="t2", matching_algorithm=Tag.MATCH_AUTO, pk=121)

        doc1 = Document.objects.create(
            title="doc1",
            content="this is a document from c1",
            checksum="A",
        )
        doc2 = Document.objects.create(
            title="doc1",
            content="this is a document from c2",
            checksum="B",
        )
        doc3 = Document.objects.create(
            title="doc1",
            content="this is a document from c3",
            checksum="C",
        )
        doc4 = Document.objects.create(
            title="doc1",
            content="this is a document from c4",
            checksum="D",
        )

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

        doc1 = Document.objects.create(
            title="doc1",
            content="this is a document from c1",
            checksum="A",
        )
        doc2 = Document.objects.create(
            title="doc2",
            content="this is a document from c2",
            checksum="B",
        )

        doc1.tags.add(t1)
        doc2.tags.add(t1)
        self.classifier.train()
        self.assertListEqual(self.classifier.predict_tags(doc1.content), [t1.pk])
        self.assertListEqual(self.classifier.predict_tags(doc2.content), [t1.pk])

    def test_one_tag_predict_multi_2(self):
        t1 = Tag.objects.create(name="t1", matching_algorithm=Tag.MATCH_AUTO, pk=12)

        doc1 = Document.objects.create(
            title="doc1",
            content="this is a document from c1",
            checksum="A",
        )
        doc2 = Document.objects.create(
            title="doc2",
            content="this is a document from c2",
            checksum="B",
        )

        doc1.tags.add(t1)
        self.classifier.train()
        self.assertListEqual(self.classifier.predict_tags(doc1.content), [t1.pk])
        self.assertListEqual(self.classifier.predict_tags(doc2.content), [])

    def test_load_classifier_not_exists(self):
        self.assertFalse(Path(settings.MODEL_FILE).exists())
        self.assertIsNone(load_classifier())

    @mock.patch("documents.classifier.DocumentClassifier.load")
    def test_load_classifier(self, load):
        Path(settings.MODEL_FILE).touch()
        self.assertIsNotNone(load_classifier())
        load.assert_called_once()

    @override_settings(
        CACHES={
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        },
    )
    @override_settings(
        MODEL_FILE=(Path(__file__).parent / "data" / "model.pickle").as_posix(),
    )
    @pytest.mark.skip(
        reason="Disabled caching due to high memory usage - need to investigate.",
    )
    def test_load_classifier_cached(self):
        classifier = load_classifier()
        self.assertIsNotNone(classifier)

        with mock.patch("documents.classifier.DocumentClassifier.load") as load:
            load_classifier()
            load.assert_not_called()

    @mock.patch("documents.classifier.DocumentClassifier.load")
    def test_load_classifier_incompatible_version(self, load):
        Path(settings.MODEL_FILE).touch()
        self.assertTrue(Path(settings.MODEL_FILE).exists())

        load.side_effect = IncompatibleClassifierVersionError("Dummy Error")
        self.assertIsNone(load_classifier())
        self.assertFalse(Path(settings.MODEL_FILE).exists())

    @mock.patch("documents.classifier.DocumentClassifier.load")
    def test_load_classifier_os_error(self, load):
        Path(settings.MODEL_FILE).touch()
        self.assertTrue(Path(settings.MODEL_FILE).exists())

        load.side_effect = OSError()
        self.assertIsNone(load_classifier())
        self.assertTrue(Path(settings.MODEL_FILE).exists())

    def test_load_old_classifier_version(self):
        shutil.copy(
            Path(__file__).parent / "data" / "v1.17.4.model.pickle",
            self.dirs.scratch_dir,
        )
        with override_settings(
            MODEL_FILE=self.dirs.scratch_dir / "v1.17.4.model.pickle",
        ):
            classifier = load_classifier()
            self.assertIsNone(classifier)

    @mock.patch("documents.classifier.DocumentClassifier.load")
    def test_load_classifier_raise_exception(self, mock_load):
        Path(settings.MODEL_FILE).touch()
        mock_load.side_effect = IncompatibleClassifierVersionError("Dummy Error")
        with self.assertRaises(IncompatibleClassifierVersionError):
            load_classifier(raise_exception=True)

        Path(settings.MODEL_FILE).touch()
        mock_load.side_effect = ClassifierModelCorruptError()
        with self.assertRaises(ClassifierModelCorruptError):
            load_classifier(raise_exception=True)

        Path(settings.MODEL_FILE).touch()
        mock_load.side_effect = OSError()
        with self.assertRaises(OSError):
            load_classifier(raise_exception=True)

        Path(settings.MODEL_FILE).touch()
        mock_load.side_effect = Exception()
        with self.assertRaises(Exception):
            load_classifier(raise_exception=True)
