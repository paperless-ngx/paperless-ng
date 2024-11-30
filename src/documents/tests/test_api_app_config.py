import json
from pathlib import Path

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from documents.tests.utils import DirectoriesMixin
from paperless.models import ApplicationConfiguration
from paperless.models import ColorConvertChoices


class TestApiAppConfig(DirectoriesMixin, APITestCase):
    ENDPOINT = "/api/config/"

    def setUp(self) -> None:
        super().setUp()

        user = User.objects.create_superuser(username="temp_admin")
        self.client.force_authenticate(user=user)

    def test_api_get_config(self):
        """
        GIVEN:
            - API request to get app config
        WHEN:
            - API is called
        THEN:
            - Existing config
        """
        response = self.client.get(self.ENDPOINT, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(
            json.dumps(response.data[0]),
            json.dumps(
                {
                    "id": 1,
                    "user_args": None,
                    "output_type": None,
                    "pages": None,
                    "language": None,
                    "mode": None,
                    "skip_archive_file": None,
                    "image_dpi": None,
                    "unpaper_clean": None,
                    "deskew": None,
                    "rotate_pages": None,
                    "rotate_pages_threshold": None,
                    "max_image_pixels": None,
                    "color_conversion_strategy": None,
                    "app_title": None,
                    "app_logo": None,
                },
            ),
        )

    def test_api_get_ui_settings_with_config(self):
        """
        GIVEN:
            - Existing config with app_title, app_logo specified
        WHEN:
            - API to retrieve uisettings is called
        THEN:
            - app_title and app_logo are included
        """
        config = ApplicationConfiguration.objects.first()
        config.app_title = "Fancy New Title"
        config.app_logo = "/logo/example.jpg"
        config.save()
        response = self.client.get("/api/ui_settings/", format="json")
        self.assertDictEqual(
            response.data["settings"],
            {
                "app_title": config.app_title,
                "app_logo": config.app_logo,
            }
            | response.data["settings"],
        )

    def test_api_update_config(self):
        """
        GIVEN:
            - API request to update app config
        WHEN:
            - API is called
        THEN:
            - Correct HTTP response
            - Config is updated
        """
        response = self.client.patch(
            f"{self.ENDPOINT}1/",
            json.dumps(
                {
                    "color_conversion_strategy": ColorConvertChoices.RGB,
                },
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        config = ApplicationConfiguration.objects.first()
        self.assertEqual(config.color_conversion_strategy, ColorConvertChoices.RGB)

    def test_api_update_config_empty_fields(self):
        """
        GIVEN:
            - API request to update app config with empty string for user_args JSONField and language field
        WHEN:
            - API is called
        THEN:
            - Correct HTTP response
            - user_args is set to None
        """
        response = self.client.patch(
            f"{self.ENDPOINT}1/",
            json.dumps(
                {
                    "user_args": "",
                    "language": "",
                },
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        config = ApplicationConfiguration.objects.first()
        self.assertEqual(config.user_args, None)
        self.assertEqual(config.language, None)

    def test_api_replace_app_logo(self):
        """
        GIVEN:
            - Existing config with app_logo specified
        WHEN:
            - API to replace app_logo is called
        THEN:
            - old app_logo file is deleted
        """
        with (Path(__file__).parent / "samples" / "simple.jpg").open("rb") as f:
            self.client.patch(
                f"{self.ENDPOINT}1/",
                {
                    "app_logo": f,
                },
            )
        config = ApplicationConfiguration.objects.first()
        old_logo = config.app_logo
        self.assertTrue(Path(old_logo.path).exists())
        with (Path(__file__).parent / "samples" / "simple.png").open("rb") as f:
            self.client.patch(
                f"{self.ENDPOINT}1/",
                {
                    "app_logo": f,
                },
            )
        self.assertFalse(Path(old_logo.path).exists())
