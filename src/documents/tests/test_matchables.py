import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path
from random import randint

from django.contrib.auth.models import User
from django.test import TestCase
from django.test import override_settings

from documents import matching
from documents.models import Correspondent
from documents.models import Document
from documents.models import DocumentType
from documents.models import Tag
from documents.signals import document_consumption_finished


class _TestMatchingBase(TestCase):
    def _test_matching(
        self,
        match_text: str,
        match_algorithm: str,
        should_match: Iterable[str],
        no_match: Iterable[str],
        *,
        case_sensitive: bool = False,
    ):
        for klass in (Tag, Correspondent, DocumentType):
            instance = klass.objects.create(
                name=str(randint(10000, 99999)),
                match=match_text,
                matching_algorithm=getattr(klass, match_algorithm),
                is_insensitive=not case_sensitive,
            )
            for string in should_match:
                doc = Document(content=string)
                self.assertTrue(
                    matching.matches(instance, doc),
                    f'"{match_text}" should match "{string}" but it does not',
                )
            for string in no_match:
                doc = Document(content=string)
                self.assertFalse(
                    matching.matches(instance, doc),
                    f'"{match_text}" should not match "{string}" but it does',
                )


class TestMatching(_TestMatchingBase):
    def test_match_none(self):
        self._test_matching(
            "",
            "MATCH_NONE",
            (),
            (
                "no",
                "match",
            ),
        )

    def test_match_all(self):
        self._test_matching(
            "alpha charlie gamma",
            "MATCH_ALL",
            ("I have alpha, charlie, and gamma in me",),
            (
                "I have alpha in me",
                "I have charlie in me",
                "I have gamma in me",
                "I have alpha and charlie in me",
                "I have alphas, charlie, and gamma in me",
                "I have alphas in me",
                "I have bravo in me",
            ),
        )

        self._test_matching(
            "12 34 56",
            "MATCH_ALL",
            ("I have 12 34, and 56 in me",),
            (
                "I have 12 in me",
                "I have 34 in me",
                "I have 56 in me",
                "I have 12 and 34 in me",
                "I have 120, 34, and 56 in me",
                "I have 123456 in me",
                "I have 01234567 in me",
            ),
        )

        self._test_matching(
            'brown fox "lazy dogs"',
            "MATCH_ALL",
            (
                "the quick brown fox jumped over the lazy dogs",
                "the quick brown fox jumped over the lazy  dogs",
            ),
            (
                "the quick fox jumped over the lazy dogs",
                "the quick brown wolf jumped over the lazy dogs",
                "the quick brown fox jumped over the fat dogs",
                "the quick brown fox jumped over the lazy... dogs",
            ),
        )

    def test_match_any(self):
        self._test_matching(
            "alpha charlie gamma",
            "MATCH_ANY",
            (
                "I have alpha in me",
                "I have charlie in me",
                "I have gamma in me",
                "I have alpha, charlie, and gamma in me",
                "I have alpha and charlie in me",
            ),
            (
                "I have alphas in me",
                "I have bravo in me",
            ),
        )

        self._test_matching(
            "12 34 56",
            "MATCH_ANY",
            (
                "I have 12 in me",
                "I have 34 in me",
                "I have 56 in me",
                "I have 12 and 34 in me",
                "I have 12, 34, and 56 in me",
                "I have 120, 34, and 56 in me",
            ),
            (
                "I have 123456 in me",
                "I have 01234567 in me",
            ),
        )

        self._test_matching(
            '"brown fox" " lazy  dogs "',
            "MATCH_ANY",
            (
                "the quick brown fox",
                "jumped over the lazy  dogs.",
            ),
            ("the lazy fox jumped over the brown dogs",),
        )

    def test_match_literal(self):
        self._test_matching(
            "alpha charlie gamma",
            "MATCH_LITERAL",
            ("I have 'alpha charlie gamma' in me",),
            (
                "I have alpha in me",
                "I have charlie in me",
                "I have gamma in me",
                "I have alpha and charlie in me",
                "I have alpha, charlie, and gamma in me",
                "I have alphas, charlie, and gamma in me",
                "I have alphas in me",
                "I have bravo in me",
            ),
        )

        self._test_matching(
            "12 34 56",
            "MATCH_LITERAL",
            ("I have 12 34 56 in me",),
            (
                "I have 12 in me",
                "I have 34 in me",
                "I have 56 in me",
                "I have 12 and 34 in me",
                "I have 12 34, and 56 in me",
                "I have 120, 34, and 560 in me",
                "I have 120, 340, and 560 in me",
                "I have 123456 in me",
                "I have 01234567 in me",
            ),
        )

    def test_match_regex(self):
        self._test_matching(
            r"alpha\w+gamma",
            "MATCH_REGEX",
            (
                "I have alpha_and_gamma in me",
                "I have alphas_and_gamma in me",
            ),
            (
                "I have alpha in me",
                "I have gamma in me",
                "I have alpha and charlie in me",
                "I have alpha,and,gamma in me",
                "I have alpha and gamma in me",
                "I have alpha, charlie, and gamma in me",
                "I have alphas, charlie, and gamma in me",
                "I have alphas in me",
            ),
        )

    def test_tach_invalid_regex(self):
        self._test_matching("[", "MATCH_REGEX", [], ["Don't match this"])

    def test_match_fuzzy(self):
        self._test_matching(
            "Springfield, Miss.",
            "MATCH_FUZZY",
            (
                "1220 Main Street, Springf eld, Miss.",
                "1220 Main Street, Spring field, Miss.",
                "1220 Main Street, Springfeld, Miss.",
                "1220 Main Street Springfield Miss",
            ),
            ("1220 Main Street, Springfield, Mich.",),
        )


class TestCaseSensitiveMatching(_TestMatchingBase):
    def test_match_all(self):
        self._test_matching(
            "alpha charlie gamma",
            "MATCH_ALL",
            (
                "I have alpha, charlie, and gamma in me",
                "I have gamma, charlie, and alpha in me",
            ),
            (
                "I have Alpha, charlie, and gamma in me",
                "I have gamma, Charlie, and alpha in me",
                "I have alpha, charlie, and Gamma in me",
                "I have gamma, charlie, and ALPHA in me",
            ),
            case_sensitive=True,
        )

        self._test_matching(
            "Alpha charlie Gamma",
            "MATCH_ALL",
            (
                "I have Alpha, charlie, and Gamma in me",
                "I have Gamma, charlie, and Alpha in me",
            ),
            (
                "I have Alpha, charlie, and gamma in me",
                "I have gamma, charlie, and alpha in me",
                "I have alpha, charlie, and Gamma in me",
                "I have Gamma, Charlie, and ALPHA in me",
            ),
            case_sensitive=True,
        )

        self._test_matching(
            'brown fox "lazy dogs"',
            "MATCH_ALL",
            (
                "the quick brown fox jumped over the lazy dogs",
                "the quick brown fox jumped over the lazy  dogs",
            ),
            (
                "the quick Brown fox jumped over the lazy dogs",
                "the quick brown Fox jumped over the lazy  dogs",
                "the quick brown fox jumped over the Lazy dogs",
                "the quick brown fox jumped over the lazy  Dogs",
            ),
            case_sensitive=True,
        )

    def test_match_any(self):
        self._test_matching(
            "alpha charlie gamma",
            "MATCH_ANY",
            (
                "I have alpha in me",
                "I have charlie in me",
                "I have gamma in me",
                "I have alpha, charlie, and gamma in me",
                "I have alpha and charlie in me",
            ),
            (
                "I have Alpha in me",
                "I have chaRLie in me",
                "I have gamMA in me",
                "I have aLPha, cHArlie, and gAMma in me",
                "I have AlphA and CharlIe in me",
            ),
            case_sensitive=True,
        )

        self._test_matching(
            "Alpha Charlie Gamma",
            "MATCH_ANY",
            (
                "I have Alpha in me",
                "I have Charlie in me",
                "I have Gamma in me",
                "I have Alpha, Charlie, and Gamma in me",
                "I have Alpha and Charlie in me",
            ),
            (
                "I have alpha in me",
                "I have ChaRLie in me",
                "I have GamMA in me",
                "I have ALPha, CHArlie, and GAMma in me",
                "I have AlphA and CharlIe in me",
            ),
            case_sensitive=True,
        )

        self._test_matching(
            '"brown fox" " lazy  dogs "',
            "MATCH_ANY",
            (
                "the quick brown fox",
                "jumped over the lazy  dogs.",
            ),
            (
                "the quick Brown fox",
                "jumped over the lazy  Dogs.",
            ),
            case_sensitive=True,
        )

    def test_match_literal(self):
        self._test_matching(
            "alpha charlie gamma",
            "MATCH_LITERAL",
            ("I have 'alpha charlie gamma' in me",),
            (
                "I have 'Alpha charlie gamma' in me",
                "I have 'alpha Charlie gamma' in me",
                "I have 'alpha charlie Gamma' in me",
                "I have 'Alpha Charlie Gamma' in me",
            ),
            case_sensitive=True,
        )

        self._test_matching(
            "Alpha Charlie Gamma",
            "MATCH_LITERAL",
            ("I have 'Alpha Charlie Gamma' in me",),
            (
                "I have 'Alpha charlie gamma' in me",
                "I have 'alpha Charlie gamma' in me",
                "I have 'alpha charlie Gamma' in me",
                "I have 'alpha charlie gamma' in me",
            ),
            case_sensitive=True,
        )

    def test_match_regex(self):
        self._test_matching(
            r"alpha\w+gamma",
            "MATCH_REGEX",
            (
                "I have alpha_and_gamma in me",
                "I have alphas_and_gamma in me",
            ),
            (
                "I have Alpha_and_Gamma in me",
                "I have alpHAs_and_gaMMa in me",
            ),
            case_sensitive=True,
        )

        self._test_matching(
            r"Alpha\w+gamma",
            "MATCH_REGEX",
            (
                "I have Alpha_and_gamma in me",
                "I have Alphas_and_gamma in me",
            ),
            (
                "I have Alpha_and_Gamma in me",
                "I have alphas_and_gamma in me",
            ),
            case_sensitive=True,
        )


@override_settings(POST_CONSUME_SCRIPT=None)
class TestDocumentConsumptionFinishedSignal(TestCase):
    """
    We make use of document_consumption_finished, so we should test that it's
    doing what we expect wrt to tag & correspondent matching.
    """

    def setUp(self):
        TestCase.setUp(self)
        User.objects.create_user(username="test_consumer", password="12345")
        self.doc_contains = Document.objects.create(
            content="I contain the keyword.",
            mime_type="application/pdf",
        )

        self.index_dir = Path(tempfile.mkdtemp())
        # TODO: we should not need the index here.
        override_settings(INDEX_DIR=self.index_dir).enable()

    def tearDown(self) -> None:
        shutil.rmtree(self.index_dir, ignore_errors=True)

    def test_tag_applied_any(self):
        t1 = Tag.objects.create(
            name="test",
            match="keyword",
            matching_algorithm=Tag.MATCH_ANY,
        )
        document_consumption_finished.send(
            sender=self.__class__,
            document=self.doc_contains,
        )
        self.assertTrue(list(self.doc_contains.tags.all()) == [t1])

    def test_tag_not_applied(self):
        Tag.objects.create(
            name="test",
            match="no-match",
            matching_algorithm=Tag.MATCH_ANY,
        )
        document_consumption_finished.send(
            sender=self.__class__,
            document=self.doc_contains,
        )
        self.assertTrue(list(self.doc_contains.tags.all()) == [])

    def test_correspondent_applied(self):
        correspondent = Correspondent.objects.create(
            name="test",
            match="keyword",
            matching_algorithm=Correspondent.MATCH_ANY,
        )
        document_consumption_finished.send(
            sender=self.__class__,
            document=self.doc_contains,
        )
        self.assertTrue(self.doc_contains.correspondent == correspondent)

    def test_correspondent_not_applied(self):
        Tag.objects.create(
            name="test",
            match="no-match",
            matching_algorithm=Correspondent.MATCH_ANY,
        )
        document_consumption_finished.send(
            sender=self.__class__,
            document=self.doc_contains,
        )
        self.assertEqual(self.doc_contains.correspondent, None)
