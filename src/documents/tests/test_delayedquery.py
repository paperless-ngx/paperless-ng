from django.test import TestCase
from whoosh import query

from documents.index import get_permissions_criterias
from documents.models import User


class TestDelayedQuery(TestCase):
    def setUp(self):
        super().setUp()
        # all tests run without permission criteria, so has_no_owner query will always
        # be appended.
        self.has_no_owner = query.Or([query.Term("has_owner", text=False)])

    def _get_testset__id__in(self, param, field):
        return (
            {f"{param}__id__in": "42,43"},
            query.And(
                [
                    query.Or(
                        [
                            query.Term(f"{field}_id", "42"),
                            query.Term(f"{field}_id", "43"),
                        ],
                    ),
                    self.has_no_owner,
                ],
            ),
        )

    def _get_testset__id__none(self, param, field):
        return (
            {f"{param}__id__none": "42,43"},
            query.And(
                [
                    query.Not(query.Term(f"{field}_id", "42")),
                    query.Not(query.Term(f"{field}_id", "43")),
                    self.has_no_owner,
                ],
            ),
        )

    def test_get_permission_criteria(self):
        # tests contains tuples of user instances and the expected filter
        tests = (
            (None, [query.Term("has_owner", text=False)]),
            (User(42, username="foo", is_superuser=True), []),
            (
                User(42, username="foo", is_superuser=False),
                [
                    query.Term("has_owner", text=False),
                    query.Term("owner_id", 42),
                    query.Term("viewer_id", "42"),
                ],
            ),
        )
        for user, expected in tests:
            self.assertEqual(get_permissions_criterias(user), expected)
