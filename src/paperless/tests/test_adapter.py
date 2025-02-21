from unittest import mock

from allauth.account.adapter import get_adapter
from allauth.core import context
from allauth.socialaccount.adapter import get_adapter as get_social_adapter
from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.forms import ValidationError
from django.http import HttpRequest
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse


class TestCustomAccountAdapter(TestCase):
    def test_is_open_for_signup(self):
        adapter = get_adapter()

        # Test when ACCOUNT_ALLOW_SIGNUPS is True
        settings.ACCOUNT_ALLOW_SIGNUPS = True
        self.assertTrue(adapter.is_open_for_signup(None))

        # Test when ACCOUNT_ALLOW_SIGNUPS is False
        settings.ACCOUNT_ALLOW_SIGNUPS = False
        self.assertFalse(adapter.is_open_for_signup(None))

    def test_is_safe_url(self):
        request = HttpRequest()
        request.get_host = mock.Mock(return_value="example.com")
        with context.request_context(request):
            adapter = get_adapter()
            with override_settings(ALLOWED_HOSTS=["*"]):
                # True because request host is same
                url = "https://example.com"
                self.assertTrue(adapter.is_safe_url(url))

            url = "https://evil.com"
            # False despite wildcard because request host is different
            self.assertFalse(adapter.is_safe_url(url))

            settings.ALLOWED_HOSTS = ["example.com"]
            url = "https://example.com"
            # True because request host is same
            self.assertTrue(adapter.is_safe_url(url))

            settings.ALLOWED_HOSTS = ["*", "example.com"]
            url = "//evil.com"
            # False because request host is not in allowed hosts
            self.assertFalse(adapter.is_safe_url(url))

    @mock.patch("allauth.core.ratelimit._consume_rate", return_value=True)
    def test_pre_authenticate(self, mock_consume_rate):
        adapter = get_adapter()
        request = HttpRequest()
        request.get_host = mock.Mock(return_value="example.com")

        settings.DISABLE_REGULAR_LOGIN = False
        adapter.pre_authenticate(request)

        settings.DISABLE_REGULAR_LOGIN = True
        with self.assertRaises(ValidationError):
            adapter.pre_authenticate(request)

    def test_get_reset_password_from_key_url(self):
        request = HttpRequest()
        request.get_host = mock.Mock(return_value="foo.org")
        with context.request_context(request):
            adapter = get_adapter()

            # Test when PAPERLESS_URL is None
            expected_url = f"https://foo.org{reverse('account_reset_password_from_key', kwargs={'uidb36': 'UID', 'key': 'KEY'})}"
            self.assertEqual(
                adapter.get_reset_password_from_key_url("UID-KEY"),
                expected_url,
            )

            # Test when PAPERLESS_URL is not None
            with override_settings(PAPERLESS_URL="https://bar.com"):
                expected_url = f"https://bar.com{reverse('account_reset_password_from_key', kwargs={'uidb36': 'UID', 'key': 'KEY'})}"
                self.assertEqual(
                    adapter.get_reset_password_from_key_url("UID-KEY"),
                    expected_url,
                )

    @override_settings(ACCOUNT_DEFAULT_GROUPS=["group1", "group2"])
    def test_save_user_adds_groups(self):
        Group.objects.create(name="group1")
        user = User.objects.create_user("testuser")
        adapter = get_adapter()
        form = mock.Mock(
            cleaned_data={
                "username": "testuser",
                "email": "user@example.com",
            },
        )

        user = adapter.save_user(HttpRequest(), user, form, commit=True)

        self.assertEqual(user.groups.count(), 1)
        self.assertTrue(user.groups.filter(name="group1").exists())
        self.assertFalse(user.groups.filter(name="group2").exists())


class TestCustomSocialAccountAdapter(TestCase):
    def test_is_open_for_signup(self):
        adapter = get_social_adapter()

        # Test when SOCIALACCOUNT_ALLOW_SIGNUPS is True
        settings.SOCIALACCOUNT_ALLOW_SIGNUPS = True
        self.assertTrue(adapter.is_open_for_signup(None, None))

        # Test when SOCIALACCOUNT_ALLOW_SIGNUPS is False
        settings.SOCIALACCOUNT_ALLOW_SIGNUPS = False
        self.assertFalse(adapter.is_open_for_signup(None, None))

    def test_get_connect_redirect_url(self):
        adapter = get_social_adapter()
        request = None
        socialaccount = None

        # Test the default URL
        expected_url = reverse("base")
        self.assertEqual(
            adapter.get_connect_redirect_url(request, socialaccount),
            expected_url,
        )

    @override_settings(SOCIAL_ACCOUNT_DEFAULT_GROUPS=["group1", "group2"])
    def test_save_user_adds_groups(self):
        Group.objects.create(name="group1")
        adapter = get_social_adapter()
        request = HttpRequest()
        user = User.objects.create_user("testuser")
        sociallogin = mock.Mock(
            user=user,
        )

        user = adapter.save_user(request, sociallogin, None)

        self.assertEqual(user.groups.count(), 1)
        self.assertTrue(user.groups.filter(name="group1").exists())
        self.assertFalse(user.groups.filter(name="group2").exists())
