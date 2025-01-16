import json
from collections.abc import Callable
from datetime import date
from unittest.mock import Mock
from urllib.parse import quote

from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from documents.models import CustomField
from documents.models import Document
from documents.serialisers import DocumentSerializer
from documents.tests.utils import DirectoriesMixin


class DocumentWrapper:
    """
    Allows Pythonic access to the custom fields associated with the wrapped document.
    """

    def __init__(self, document: Document) -> None:
        self._document = document

    def __contains__(self, custom_field: str) -> bool:
        return self._document.custom_fields.filter(field__name=custom_field).exists()

    def __getitem__(self, custom_field: str):
        return self._document.custom_fields.get(field__name=custom_field).value


class TestCustomFieldsSearch(DirectoriesMixin, APITestCase):
    def setUp(self):
        super().setUp()

        self.user = User.objects.create_superuser(username="temp_admin")
        self.client.force_authenticate(user=self.user)

        # Create one custom field per type. The fields are called f"{type}_field".
        self.custom_fields = {}
        for data_type in CustomField.FieldDataType.values:
            name = data_type + "_field"
            self.custom_fields[name] = CustomField.objects.create(
                name=name,
                data_type=data_type,
            )

        # Add some options to the select_field
        select = self.custom_fields["select_field"]
        select.extra_data = {
            "select_options": [
                {"label": "A", "id": "abc-123"},
                {"label": "B", "id": "def-456"},
                {"label": "C", "id": "ghi-789"},
            ],
        }
        select.save()

        # Now we will create some test documents
        self.documents = []

        # CustomField.FieldDataType.STRING
        self._create_document(string_field=None)
        self._create_document(string_field="")
        self._create_document(string_field="paperless")
        self._create_document(string_field="Paperless")
        self._create_document(string_field="PAPERLESS")
        self._create_document(string_field="pointless")
        self._create_document(string_field="pointy")

        # CustomField.FieldDataType.URL
        self._create_document(url_field=None)
        self._create_document(url_field="")
        self._create_document(url_field="https://docs.paperless-ngx.com/")
        self._create_document(url_field="https://www.django-rest-framework.org/")
        self._create_document(url_field="http://example.com/")

        # A document to check if the filter correctly associates field names with values.
        # E.g., ["url_field", "exact", "https://docs.paperless-ngx.com/"] should not
        # yield this document.
        self._create_document(
            string_field="https://docs.paperless-ngx.com/",
            url_field="http://example.com/",
        )

        # CustomField.FieldDataType.DATE
        self._create_document(date_field=None)
        self._create_document(date_field=date(2023, 8, 22))
        self._create_document(date_field=date(2024, 8, 22))
        self._create_document(date_field=date(2024, 11, 15))

        # CustomField.FieldDataType.BOOL
        self._create_document(boolean_field=None)
        self._create_document(boolean_field=True)
        self._create_document(boolean_field=False)

        # CustomField.FieldDataType.INT
        self._create_document(integer_field=None)
        self._create_document(integer_field=-1)
        self._create_document(integer_field=0)
        self._create_document(integer_field=1)

        # CustomField.FieldDataType.FLOAT
        self._create_document(float_field=None)
        self._create_document(float_field=-1e9)
        self._create_document(float_field=0.05)
        self._create_document(float_field=270.0)

        # CustomField.FieldDataType.MONETARY
        self._create_document(monetary_field=None)
        self._create_document(monetary_field="USD100.00")
        self._create_document(monetary_field="USD1.00")
        self._create_document(monetary_field="EUR50.00")
        self._create_document(monetary_field="101.00")

        # CustomField.FieldDataType.DOCUMENTLINK
        self._create_document(documentlink_field=None)
        self._create_document(documentlink_field=[])
        self._create_document(
            documentlink_field=[
                self.documents[0].id,
                self.documents[1].id,
                self.documents[2].id,
            ],
        )
        self._create_document(
            documentlink_field=[self.documents[4].id, self.documents[5].id],
        )

        # CustomField.FieldDataType.SELECT
        self._create_document(select_field=None)
        self._create_document(select_field="abc-123")
        self._create_document(select_field="def-456")
        self._create_document(select_field="ghi-789")

    def _create_document(self, **kwargs):
        title = str(kwargs)
        document = Document.objects.create(
            title=title,
            checksum=title,
            archive_serial_number=len(self.documents) + 1,
        )
        data = {
            "custom_fields": [
                {"field": self.custom_fields[name].id, "value": value}
                for name, value in kwargs.items()
            ],
        }
        serializer = DocumentSerializer(
            document,
            data=data,
            partial=True,
            context={"request": Mock()},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        self.documents.append(document)
        return document

    def _assert_query_match_predicate(
        self,
        query: list,
        reference_predicate: Callable[[DocumentWrapper], bool],
        *,
        match_nothing_ok=False,
    ):
        """
        Checks the results of the query against a callable reference predicate.
        """
        reference_document_ids = [
            document.id
            for document in self.documents
            if reference_predicate(DocumentWrapper(document))
        ]
        # First sanity check our test cases
        if not match_nothing_ok:
            self.assertTrue(
                reference_document_ids,
                msg="Bad test case - should match at least one document.",
            )
        self.assertNotEqual(
            len(reference_document_ids),
            len(self.documents),
            msg="Bad test case - should not match all documents.",
        )

        # Now make the API call.
        query_string = quote(json.dumps(query), safe="")
        response = self.client.get(
            "/api/documents/?"
            + "&".join(
                (
                    f"custom_field_query={query_string}",
                    "ordering=archive_serial_number",
                    "page=1",
                    f"page_size={len(self.documents)}",
                    "truncate_content=true",
                ),
            ),
        )
        self.assertEqual(response.status_code, 200, msg=str(response.json()))
        response_document_ids = [
            document["id"] for document in response.json()["results"]
        ]
        self.assertEqual(reference_document_ids, response_document_ids)

    def _assert_validation_error(self, query: str, path: list, keyword: str):
        """
        Asserts that the query raises a validation error.
        Checks the message to make sure it points to the right place.
        """
        query_string = quote(query, safe="")
        response = self.client.get(
            "/api/documents/?"
            + "&".join(
                (
                    f"custom_field_query={query_string}",
                    "ordering=archive_serial_number",
                    "page=1",
                    f"page_size={len(self.documents)}",
                    "truncate_content=true",
                ),
            ),
        )
        self.assertEqual(response.status_code, 400)

        exception_path = []
        detail = response.json()
        while not isinstance(detail, list):
            path_item, detail = next(iter(detail.items()))
            exception_path.append(path_item)

        self.assertEqual(path, exception_path)
        self.assertIn(keyword, " ".join(detail))

    # ==========================================================#
    # Sanity checks                                             #
    # ==========================================================#
    def test_name_value_association(self):
        """
        GIVEN:
            - A document with `{"string_field": "https://docs.paperless-ngx.com/",
              "url_field": "http://example.com/"}`
        WHEN:
            - Filtering by `["url_field", "exact", "https://docs.paperless-ngx.com/"]`
        THEN:
            - That document should not get matched.
        """
        self._assert_query_match_predicate(
            ["url_field", "exact", "https://docs.paperless-ngx.com/"],
            lambda document: "url_field" in document
            and document["url_field"] == "https://docs.paperless-ngx.com/",
        )

    def test_filter_by_multiple_fields(self):
        """
        GIVEN:
            - A document with `{"string_field": "https://docs.paperless-ngx.com/",
              "url_field": "http://example.com/"}`
        WHEN:
            - Filtering by `['AND', [["string_field", "exists", True], ["url_field", "exists", True]]]`
        THEN:
            - That document should get matched.
        """
        self._assert_query_match_predicate(
            ["AND", [["string_field", "exists", True], ["url_field", "exists", True]]],
            lambda document: "url_field" in document and "string_field" in document,
        )

    # ==========================================================#
    # Basic expressions supported by all custom field types     #
    # ==========================================================#
    def test_exact(self):
        self._assert_query_match_predicate(
            ["string_field", "exact", "paperless"],
            lambda document: "string_field" in document
            and document["string_field"] == "paperless",
        )

    def test_in(self):
        self._assert_query_match_predicate(
            ["string_field", "in", ["paperless", "Paperless"]],
            lambda document: "string_field" in document
            and document["string_field"] in ("paperless", "Paperless"),
        )

    def test_isnull(self):
        self._assert_query_match_predicate(
            ["string_field", "isnull", True],
            lambda document: "string_field" in document
            and document["string_field"] is None,
        )

    def test_exists(self):
        self._assert_query_match_predicate(
            ["string_field", "exists", True],
            lambda document: "string_field" in document,
        )

    def test_exists_false(self):
        self._assert_query_match_predicate(
            ["string_field", "exists", False],
            lambda document: "string_field" not in document,
        )

    def test_select(self):
        # For select fields, you can either specify the id of the option
        # or the name of the option. They function exactly the same.
        self._assert_query_match_predicate(
            ["select_field", "exact", "def-456"],
            lambda document: "select_field" in document
            and document["select_field"] == "def-456",
        )
        # This is the same as:
        self._assert_query_match_predicate(
            ["select_field", "exact", "B"],
            lambda document: "select_field" in document
            and document["select_field"] == "def-456",
        )

    # ==========================================================#
    # Expressions for string, URL, and monetary fields          #
    # ==========================================================#
    def test_icontains(self):
        self._assert_query_match_predicate(
            ["string_field", "icontains", "aper"],
            lambda document: "string_field" in document
            and document["string_field"] is not None
            and "aper" in document["string_field"].lower(),
        )

    def test_istartswith(self):
        self._assert_query_match_predicate(
            ["string_field", "istartswith", "paper"],
            lambda document: "string_field" in document
            and document["string_field"] is not None
            and document["string_field"].lower().startswith("paper"),
        )

    def test_iendswith(self):
        self._assert_query_match_predicate(
            ["string_field", "iendswith", "less"],
            lambda document: "string_field" in document
            and document["string_field"] is not None
            and document["string_field"].lower().endswith("less"),
        )

    def test_url_field_istartswith(self):
        # URL fields supports all of the expressions above.
        # Just showing one of them here.
        self._assert_query_match_predicate(
            ["url_field", "istartswith", "http://"],
            lambda document: "url_field" in document
            and document["url_field"] is not None
            and document["url_field"].startswith("http://"),
        )

    # ==========================================================#
    # Arithmetic comparisons                                    #
    # ==========================================================#
    def test_gt(self):
        self._assert_query_match_predicate(
            ["date_field", "gt", date(2024, 8, 22).isoformat()],
            lambda document: "date_field" in document
            and document["date_field"] is not None
            and document["date_field"] > date(2024, 8, 22),
        )

    def test_gte(self):
        self._assert_query_match_predicate(
            ["date_field", "gte", date(2024, 8, 22).isoformat()],
            lambda document: "date_field" in document
            and document["date_field"] is not None
            and document["date_field"] >= date(2024, 8, 22),
        )

    def test_lt(self):
        self._assert_query_match_predicate(
            ["integer_field", "lt", 0],
            lambda document: "integer_field" in document
            and document["integer_field"] is not None
            and document["integer_field"] < 0,
        )

    def test_lte(self):
        self._assert_query_match_predicate(
            ["integer_field", "lte", 0],
            lambda document: "integer_field" in document
            and document["integer_field"] is not None
            and document["integer_field"] <= 0,
        )

    def test_range(self):
        self._assert_query_match_predicate(
            ["float_field", "range", [-0.05, 0.05]],
            lambda document: "float_field" in document
            and document["float_field"] is not None
            and -0.05 <= document["float_field"] <= 0.05,
        )

    def test_date_modifier(self):
        # For date fields you can optionally prefix the operator
        # with the part of the date you are comparing with.
        self._assert_query_match_predicate(
            ["date_field", "year__gte", 2024],
            lambda document: "date_field" in document
            and document["date_field"] is not None
            and document["date_field"].year >= 2024,
        )

    def test_gt_monetary(self):
        self._assert_query_match_predicate(
            ["monetary_field", "gt", "99"],
            lambda document: "monetary_field" in document
            and document["monetary_field"] is not None
            and (
                document["monetary_field"] == "USD100.00"  # With currency symbol
                or document["monetary_field"] == "101.00"  # No currency symbol
            ),
        )

    # ==========================================================#
    # Subset check (document link field only)                   #
    # ==========================================================#
    def test_document_link_contains(self):
        # Document link field "contains" performs a subset check.
        self._assert_query_match_predicate(
            ["documentlink_field", "contains", [1, 2]],
            lambda document: "documentlink_field" in document
            and document["documentlink_field"] is not None
            and set(document["documentlink_field"]) >= {1, 2},
        )
        # The order of IDs don't matter - this is the same as above.
        self._assert_query_match_predicate(
            ["documentlink_field", "contains", [2, 1]],
            lambda document: "documentlink_field" in document
            and document["documentlink_field"] is not None
            and set(document["documentlink_field"]) >= {1, 2},
        )

    def test_document_link_contains_empty_set(self):
        # An empty set is a subset of any set.
        self._assert_query_match_predicate(
            ["documentlink_field", "contains", []],
            lambda document: "documentlink_field" in document
            and document["documentlink_field"] is not None,
        )

    def test_document_link_contains_no_reverse_link(self):
        # An edge case is that the document in the value list
        # doesn't have a document link field and thus has no reverse link.
        self._assert_query_match_predicate(
            ["documentlink_field", "contains", [self.documents[6].id]],
            lambda document: "documentlink_field" in document
            and document["documentlink_field"] is not None
            and set(document["documentlink_field"]) >= {self.documents[6].id},
            match_nothing_ok=True,
        )

    # ==========================================================#
    # Logical expressions                                       #
    # ==========================================================#
    def test_logical_and(self):
        self._assert_query_match_predicate(
            [
                "AND",
                [["date_field", "year__exact", 2024], ["date_field", "month__lt", 9]],
            ],
            lambda document: "date_field" in document
            and document["date_field"] is not None
            and document["date_field"].year == 2024
            and document["date_field"].month < 9,
        )

    def test_logical_or(self):
        # This is also the recommend way to check for "empty" text, URL, and monetary fields.
        self._assert_query_match_predicate(
            [
                "OR",
                [["string_field", "exact", ""], ["string_field", "isnull", True]],
            ],
            lambda document: "string_field" in document
            and not bool(document["string_field"]),
        )

    def test_logical_not(self):
        # This means `NOT ((document has string_field) AND (string_field iexact "paperless"))`,
        # not `(document has string_field) AND (NOT (string_field iexact "paperless"))`!
        self._assert_query_match_predicate(
            [
                "NOT",
                ["string_field", "exact", "paperless"],
            ],
            lambda document: not (
                "string_field" in document and document["string_field"] == "paperless"
            ),
        )

    # ==========================================================#
    # Tests for invalid queries                                 #
    # ==========================================================#

    def test_invalid_json(self):
        self._assert_validation_error(
            "not valid json",
            ["custom_field_query"],
            "must be valid JSON",
        )

    def test_invalid_expression(self):
        self._assert_validation_error(
            json.dumps("valid json but not valid expr"),
            ["custom_field_query"],
            "Invalid custom field query expression",
        )

    def test_invalid_custom_field_name(self):
        self._assert_validation_error(
            json.dumps(["invalid name", "iexact", "foo"]),
            ["custom_field_query", "0"],
            "is not a valid custom field",
        )

    def test_invalid_operator(self):
        self._assert_validation_error(
            json.dumps(["integer_field", "iexact", "foo"]),
            ["custom_field_query", "1"],
            "does not support query expr",
        )

    def test_invalid_value(self):
        self._assert_validation_error(
            json.dumps(["select_field", "exact", []]),
            ["custom_field_query", "2"],
            "string",
        )

    def test_invalid_logical_operator(self):
        self._assert_validation_error(
            json.dumps(["invalid op", ["integer_field", "gt", 0]]),
            ["custom_field_query", "0"],
            "Invalid logical operator",
        )

    def test_invalid_expr_list(self):
        self._assert_validation_error(
            json.dumps(["AND", "not a list"]),
            ["custom_field_query", "1"],
            "Invalid expression list",
        )

    def test_invalid_operator_prefix(self):
        self._assert_validation_error(
            json.dumps(["integer_field", "foo__gt", 0]),
            ["custom_field_query", "1"],
            "does not support query expr",
        )

    def test_query_too_deep(self):
        query = ["string_field", "exact", "paperless"]
        for _ in range(10):
            query = ["NOT", query]
        self._assert_validation_error(
            json.dumps(query),
            ["custom_field_query", *(["1"] * 10)],
            "Maximum nesting depth exceeded",
        )

    def test_query_too_many_atoms(self):
        atom = ["string_field", "exact", "paperless"]
        query = ["AND", [atom for _ in range(21)]]
        self._assert_validation_error(
            json.dumps(query),
            ["custom_field_query", "1", "20"],
            "Maximum number of query conditions exceeded",
        )
