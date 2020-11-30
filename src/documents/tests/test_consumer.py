import os
import re
import tempfile
from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase, override_settings

from .utils import DirectoriesMixin
from ..consumer import Consumer, ConsumerError
from ..models import FileInfo, Tag, Correspondent, DocumentType, Document
from ..parsers import DocumentParser, ParseError


class TestAttributes(TestCase):

    TAGS = ("tag1", "tag2", "tag3")

    def _test_guess_attributes_from_name(self, filename, sender, title, tags):
        file_info = FileInfo.from_filename(filename)

        if sender:
            self.assertEqual(file_info.correspondent.name, sender, filename)
        else:
            self.assertIsNone(file_info.correspondent, filename)

        self.assertEqual(file_info.title, title, filename)

        self.assertEqual(tuple([t.slug for t in file_info.tags]), tags, filename)

    def test_guess_attributes_from_name0(self):
        self._test_guess_attributes_from_name(
            "Sender - Title.pdf", "Sender", "Title", ())

    def test_guess_attributes_from_name1(self):
        self._test_guess_attributes_from_name(
            "Spaced Sender - Title.pdf", "Spaced Sender", "Title", ())

    def test_guess_attributes_from_name2(self):
        self._test_guess_attributes_from_name(
            "Sender - Spaced Title.pdf", "Sender", "Spaced Title", ())

    def test_guess_attributes_from_name3(self):
        self._test_guess_attributes_from_name(
            "Dashed-Sender - Title.pdf", "Dashed-Sender", "Title", ())

    def test_guess_attributes_from_name4(self):
        self._test_guess_attributes_from_name(
            "Sender - Dashed-Title.pdf", "Sender", "Dashed-Title", ())

    def test_guess_attributes_from_name5(self):
        self._test_guess_attributes_from_name(
            "Sender - Title - tag1,tag2,tag3.pdf",
            "Sender",
            "Title",
            self.TAGS
        )

    def test_guess_attributes_from_name6(self):
        self._test_guess_attributes_from_name(
            "Spaced Sender - Title - tag1,tag2,tag3.pdf",
            "Spaced Sender",
            "Title",
            self.TAGS
        )

    def test_guess_attributes_from_name7(self):
        self._test_guess_attributes_from_name(
            "Sender - Spaced Title - tag1,tag2,tag3.pdf",
            "Sender",
            "Spaced Title",
            self.TAGS
        )

    def test_guess_attributes_from_name8(self):
        self._test_guess_attributes_from_name(
            "Dashed-Sender - Title - tag1,tag2,tag3.pdf",
            "Dashed-Sender",
            "Title",
            self.TAGS
        )

    def test_guess_attributes_from_name9(self):
        self._test_guess_attributes_from_name(
            "Sender - Dashed-Title - tag1,tag2,tag3.pdf",
            "Sender",
            "Dashed-Title",
            self.TAGS
        )

    def test_guess_attributes_from_name10(self):
        self._test_guess_attributes_from_name(
            "Σενδερ - Τιτλε - tag1,tag2,tag3.pdf",
            "Σενδερ",
            "Τιτλε",
            self.TAGS
        )

    def test_guess_attributes_from_name_when_correspondent_empty(self):
        self._test_guess_attributes_from_name(
            ' - weird empty correspondent but should not break.pdf',
            None,
            'weird empty correspondent but should not break',
            ()
        )

    def test_guess_attributes_from_name_when_title_starts_with_dash(self):
        self._test_guess_attributes_from_name(
            '- weird but should not break.pdf',
            None,
            '- weird but should not break',
            ()
        )

    def test_guess_attributes_from_name_when_title_ends_with_dash(self):
        self._test_guess_attributes_from_name(
            'weird but should not break -.pdf',
            None,
            'weird but should not break -',
            ()
        )

    def test_guess_attributes_from_name_when_title_is_empty(self):
        self._test_guess_attributes_from_name(
            'weird correspondent but should not break - .pdf',
            'weird correspondent but should not break',
            '',
            ()
        )

    def test_case_insensitive_tag_creation(self):
        """
        Tags should be detected and created as lower case.
        :return:
        """

        filename = "Title - Correspondent - tAg1,TAG2.pdf"
        self.assertEqual(len(FileInfo.from_filename(filename).tags), 2)

        path = "Title - Correspondent - tag1,tag2.pdf"
        self.assertEqual(len(FileInfo.from_filename(filename).tags), 2)

        self.assertEqual(Tag.objects.all().count(), 2)


class TestFieldPermutations(TestCase):

    valid_dates = (
        "20150102030405Z",
        "20150102Z",
    )
    valid_correspondents = [
        "timmy",
        "Dr. McWheelie",
        "Dash Gor-don",
        "ο Θερμαστής",
        ""
    ]
    valid_titles = ["title", "Title w Spaces", "Title a-dash", "Τίτλος", ""]
    valid_tags = ["tag", "tig,tag", "tag1,tag2,tag-3"]

    def _test_guessed_attributes(self, filename, created=None,
                                 correspondent=None, title=None,
                                 tags=None):

        info = FileInfo.from_filename(filename)

        # Created
        if created is None:
            self.assertIsNone(info.created, filename)
        else:
            self.assertEqual(info.created.year, int(created[:4]), filename)
            self.assertEqual(info.created.month, int(created[4:6]), filename)
            self.assertEqual(info.created.day, int(created[6:8]), filename)

        # Correspondent
        if correspondent:
            self.assertEqual(info.correspondent.name, correspondent, filename)
        else:
            self.assertEqual(info.correspondent, None, filename)

        # Title
        self.assertEqual(info.title, title, filename)

        # Tags
        if tags is None:
            self.assertEqual(info.tags, (), filename)
        else:
            self.assertEqual(
                [t.slug for t in info.tags], tags.split(','),
                filename
            )

    def test_just_title(self):
        template = '{title}.pdf'
        for title in self.valid_titles:
            spec = dict(title=title)
            filename = template.format(**spec)
            self._test_guessed_attributes(filename, **spec)

    def test_title_and_correspondent(self):
        template = '{correspondent} - {title}.pdf'
        for correspondent in self.valid_correspondents:
            for title in self.valid_titles:
                spec = dict(correspondent=correspondent, title=title)
                filename = template.format(**spec)
                self._test_guessed_attributes(filename, **spec)

    def test_title_and_correspondent_and_tags(self):
        template = '{correspondent} - {title} - {tags}.pdf'
        for correspondent in self.valid_correspondents:
            for title in self.valid_titles:
                for tags in self.valid_tags:
                    spec = dict(correspondent=correspondent, title=title,
                                tags=tags)
                    filename = template.format(**spec)
                    self._test_guessed_attributes(filename, **spec)

    def test_created_and_correspondent_and_title_and_tags(self):

        template = (
            "{created} - "
            "{correspondent} - "
            "{title} - "
            "{tags}.pdf"
        )

        for created in self.valid_dates:
            for correspondent in self.valid_correspondents:
                for title in self.valid_titles:
                    for tags in self.valid_tags:
                        spec = {
                            "created": created,
                            "correspondent": correspondent,
                            "title": title,
                            "tags": tags,
                        }
                        self._test_guessed_attributes(
                            template.format(**spec), **spec)

    def test_created_and_correspondent_and_title(self):

        template = "{created} - {correspondent} - {title}.pdf"

        for created in self.valid_dates:
            for correspondent in self.valid_correspondents:
                for title in self.valid_titles:

                    # Skip cases where title looks like a tag as we can't
                    # accommodate such cases.
                    if title.lower() == title:
                        continue

                    spec = {
                        "created": created,
                        "correspondent": correspondent,
                        "title": title
                    }
                    self._test_guessed_attributes(
                        template.format(**spec), **spec)

    def test_created_and_title(self):

        template = "{created} - {title}.pdf"

        for created in self.valid_dates:
            for title in self.valid_titles:
                spec = {
                    "created": created,
                    "title": title
                }
                self._test_guessed_attributes(
                    template.format(**spec), **spec)

    def test_created_and_title_and_tags(self):

        template = "{created} - {title} - {tags}.pdf"

        for created in self.valid_dates:
            for title in self.valid_titles:
                for tags in self.valid_tags:
                    spec = {
                        "created": created,
                        "title": title,
                        "tags": tags
                    }
                    self._test_guessed_attributes(
                        template.format(**spec), **spec)

    def test_invalid_date_format(self):
        info = FileInfo.from_filename("06112017Z - title.pdf")
        self.assertEqual(info.title, "title")
        self.assertIsNone(info.created)

    def test_filename_parse_transforms(self):

        filename = "tag1,tag2_20190908_180610_0001.pdf"
        all_patt = re.compile("^.*$")
        none_patt = re.compile("$a")
        exact_patt = re.compile("^([a-z0-9,]+)_(\\d{8})_(\\d{6})_([0-9]+)\\.")
        repl1 = " - \\4 - \\1."    # (empty) corrspondent, title and tags
        repl2 = "\\2Z - " + repl1  # creation date + repl1

        # No transformations configured (= default)
        info = FileInfo.from_filename(filename)
        self.assertEqual(info.title, "tag1,tag2_20190908_180610_0001")
        self.assertEqual(info.tags, ())
        self.assertIsNone(info.created)

        # Pattern doesn't match (filename unaltered)
        with self.settings(
                FILENAME_PARSE_TRANSFORMS=[(none_patt, "none.gif")]):
            info = FileInfo.from_filename(filename)
            self.assertEqual(info.title, "tag1,tag2_20190908_180610_0001")

        # Simple transformation (match all)
        with self.settings(
                FILENAME_PARSE_TRANSFORMS=[(all_patt, "all.gif")]):
            info = FileInfo.from_filename(filename)
            self.assertEqual(info.title, "all")

        # Multiple transformations configured (first pattern matches)
        with self.settings(
                FILENAME_PARSE_TRANSFORMS=[
                    (all_patt, "all.gif"),
                    (all_patt, "anotherall.gif")]):
            info = FileInfo.from_filename(filename)
            self.assertEqual(info.title, "all")

        # Multiple transformations configured (second pattern matches)
        with self.settings(
                FILENAME_PARSE_TRANSFORMS=[
                    (none_patt, "none.gif"),
                    (all_patt, "anotherall.gif")]):
            info = FileInfo.from_filename(filename)
            self.assertEqual(info.title, "anotherall")

        # Complex transformation without date in replacement string
        with self.settings(
                FILENAME_PARSE_TRANSFORMS=[(exact_patt, repl1)]):
            info = FileInfo.from_filename(filename)
            self.assertEqual(info.title, "0001")
            self.assertEqual(len(info.tags), 2)
            self.assertEqual(info.tags[0].slug, "tag1")
            self.assertEqual(info.tags[1].slug, "tag2")
            self.assertIsNone(info.created)

        # Complex transformation with date in replacement string
        with self.settings(
            FILENAME_PARSE_TRANSFORMS=[
                (none_patt, "none.gif"),
                (exact_patt, repl2),    # <-- matches
                (exact_patt, repl1),
                (all_patt, "all.gif")]):
            info = FileInfo.from_filename(filename)
            self.assertEqual(info.title, "0001")
            self.assertEqual(len(info.tags), 2)
            self.assertEqual(info.tags[0].slug, "tag1")
            self.assertEqual(info.tags[1].slug, "tag2")
            self.assertEqual(info.created.year, 2019)
            self.assertEqual(info.created.month, 9)
            self.assertEqual(info.created.day, 8)


class DummyParser(DocumentParser):

    def get_thumbnail(self):
        # not important during tests
        raise NotImplementedError()

    def __init__(self, path, logging_group, scratch_dir):
        super(DummyParser, self).__init__(path, logging_group)
        _, self.fake_thumb = tempfile.mkstemp(suffix=".png", dir=scratch_dir)

    def get_optimised_thumbnail(self):
        return self.fake_thumb

    def get_text(self):
        return "The Text"


class FaultyParser(DocumentParser):

    def get_thumbnail(self):
        # not important during tests
        raise NotImplementedError()

    def __init__(self, path, logging_group, scratch_dir):
        super(FaultyParser, self).__init__(path, logging_group)
        _, self.fake_thumb = tempfile.mkstemp(suffix=".png", dir=scratch_dir)

    def get_optimised_thumbnail(self):
        return self.fake_thumb

    def get_text(self):
        raise ParseError("Does not compute.")


def fake_magic_from_file(file, mime=False):

    if mime:
        if os.path.splitext(file)[1] == ".pdf":
            return "application/pdf"
        else:
            return "unknown"
    else:
        return "A verbose string that describes the contents of the file"


@mock.patch("documents.consumer.magic.from_file", fake_magic_from_file)
class TestConsumer(DirectoriesMixin, TestCase):

    def make_dummy_parser(self, path, logging_group):
        return DummyParser(path, logging_group, self.dirs.scratch_dir)

    def make_faulty_parser(self, path, logging_group):
        return FaultyParser(path, logging_group, self.dirs.scratch_dir)

    def setUp(self):
        super(TestConsumer, self).setUp()

        patcher = mock.patch("documents.parsers.document_consumer_declaration.send")
        m = patcher.start()
        m.return_value = [(None, {
            "parser": self.make_dummy_parser,
            "mime_types": {"application/pdf": ".pdf"},
            "weight": 0
        })]

        self.addCleanup(patcher.stop)

        self.consumer = Consumer()

    def get_test_file(self):
        fd, f = tempfile.mkstemp(suffix=".pdf", dir=self.dirs.scratch_dir)
        return f

    @override_settings(PAPERLESS_FILENAME_FORMAT=None)
    def testNormalOperation(self):

        filename = self.get_test_file()
        document = self.consumer.try_consume_file(filename)

        self.assertEqual(document.content, "The Text")
        self.assertEqual(document.title, os.path.splitext(os.path.basename(filename))[0])
        self.assertIsNone(document.correspondent)
        self.assertIsNone(document.document_type)
        self.assertEqual(document.filename, "0000001.pdf")

        self.assertTrue(os.path.isfile(
            document.source_path
        ))

        self.assertTrue(os.path.isfile(
            document.thumbnail_path
        ))

        self.assertFalse(os.path.isfile(filename))

    def testOverrideFilename(self):
        filename = self.get_test_file()
        override_filename = "My Bank - Statement for November.pdf"

        document = self.consumer.try_consume_file(filename, override_filename=override_filename)

        self.assertEqual(document.correspondent.name, "My Bank")
        self.assertEqual(document.title, "Statement for November")

    def testOverrideTitle(self):

        document = self.consumer.try_consume_file(self.get_test_file(), override_title="Override Title")
        self.assertEqual(document.title, "Override Title")

    def testOverrideCorrespondent(self):
        c = Correspondent.objects.create(name="test")

        document = self.consumer.try_consume_file(self.get_test_file(), override_correspondent_id=c.pk)
        self.assertEqual(document.correspondent.id, c.id)

    def testOverrideDocumentType(self):
        dt = DocumentType.objects.create(name="test")

        document = self.consumer.try_consume_file(self.get_test_file(), override_document_type_id=dt.pk)
        self.assertEqual(document.document_type.id, dt.id)

    def testOverrideTags(self):
        t1 = Tag.objects.create(name="t1")
        t2 = Tag.objects.create(name="t2")
        t3 = Tag.objects.create(name="t3")
        document = self.consumer.try_consume_file(self.get_test_file(), override_tag_ids=[t1.id, t3.id])

        self.assertIn(t1, document.tags.all())
        self.assertNotIn(t2, document.tags.all())
        self.assertIn(t3, document.tags.all())

    def testNotAFile(self):
        try:
            self.consumer.try_consume_file("non-existing-file")
        except ConsumerError as e:
            self.assertTrue(str(e).endswith('It is not a file'))
            return

        self.fail("Should throw exception")

    def testDuplicates(self):
        self.consumer.try_consume_file(self.get_test_file())

        try:
            self.consumer.try_consume_file(self.get_test_file())
        except ConsumerError as e:
            self.assertTrue(str(e).endswith("It is a duplicate."))
            return

        self.fail("Should throw exception")

    @mock.patch("documents.parsers.document_consumer_declaration.send")
    def testNoParsers(self, m):
        m.return_value = []

        try:
            self.consumer.try_consume_file(self.get_test_file())
        except ConsumerError as e:
            self.assertTrue("File extension .pdf does not map to any" in str(e))
            return

        self.fail("Should throw exception")

    @mock.patch("documents.parsers.document_consumer_declaration.send")
    def testFaultyParser(self, m):
        m.return_value = [(None, {
            "parser": self.make_faulty_parser,
            "mime_types": {"application/pdf": ".pdf"},
            "weight": 0
        })]

        try:
            self.consumer.try_consume_file(self.get_test_file())
        except ConsumerError as e:
            self.assertEqual(str(e), "Does not compute.")
            return

        self.fail("Should throw exception.")

    @mock.patch("documents.consumer.Consumer._write")
    def testPostSaveError(self, m):
        filename = self.get_test_file()
        m.side_effect = OSError("NO.")
        try:
            self.consumer.try_consume_file(filename)
        except ConsumerError as e:
            self.assertEqual(str(e), "NO.")
        else:
            self.fail("Should raise exception")

        # file not deleted
        self.assertTrue(os.path.isfile(filename))

        # Database empty
        self.assertEqual(len(Document.objects.all()), 0)

    @override_settings(PAPERLESS_FILENAME_FORMAT="{correspondent}/{title}")
    def testFilenameHandling(self):
        filename = self.get_test_file()

        document = self.consumer.try_consume_file(filename, override_filename="Bank - Test.pdf", override_title="new docs")

        self.assertEqual(document.title, "new docs")
        self.assertEqual(document.correspondent.name, "Bank")
        self.assertEqual(document.filename, "bank/new-docs-0000001.pdf")

    @override_settings(PAPERLESS_FILENAME_FORMAT="{correspondent}/{title}")
    @mock.patch("documents.signals.handlers.generate_filename")
    def testFilenameHandlingUnstableFormat(self, m):

        filenames = ["this", "that", "now this", "i cant decide"]

        def get_filename():
            f = filenames.pop()
            filenames.insert(0, f)
            return f

        m.side_effect = lambda f: get_filename()

        filename = self.get_test_file()

        Tag.objects.create(name="test", is_inbox_tag=True)

        document = self.consumer.try_consume_file(filename, override_filename="Bank - Test.pdf", override_title="new docs")

        self.assertEqual(document.title, "new docs")
        self.assertEqual(document.correspondent.name, "Bank")
        self.assertIsNotNone(os.path.isfile(document.title))
        self.assertTrue(os.path.isfile(document.source_path))

    @mock.patch("documents.consumer.DocumentClassifier")
    def testClassifyDocument(self, m):
        correspondent = Correspondent.objects.create(name="test")
        dtype = DocumentType.objects.create(name="test")
        t1 = Tag.objects.create(name="t1")
        t2 = Tag.objects.create(name="t2")

        m.return_value = MagicMock()
        m.return_value.predict_correspondent.return_value = correspondent.pk
        m.return_value.predict_document_type.return_value = dtype.pk
        m.return_value.predict_tags.return_value = [t1.pk]

        document = self.consumer.try_consume_file(self.get_test_file())

        self.assertEqual(document.correspondent, correspondent)
        self.assertEqual(document.document_type, dtype)
        self.assertIn(t1, document.tags.all())
        self.assertNotIn(t2, document.tags.all())
