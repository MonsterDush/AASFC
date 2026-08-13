from unittest import TestCase

from pydantic import ValidationError

from app.core.i18n import localized, normalize_locale, user_locale
from app.routers.me import ProfileUpdateIn


class _User:
    def __init__(self, preferred_locale=None):
        self.preferred_locale = preferred_locale


class I18nTests(TestCase):
    def test_normalize_locale_accepts_supported_language_tags(self):
        self.assertEqual(normalize_locale("en-US"), "en")
        self.assertEqual(normalize_locale("ru_RU"), "ru")
        self.assertEqual(normalize_locale("de-DE"), "ru")
        self.assertIsNone(normalize_locale("de-DE", default=None))

    def test_user_locale_and_localized_fallback_to_russian(self):
        self.assertEqual(user_locale(_User("en")), "en")
        self.assertEqual(user_locale(_User()), "ru")
        self.assertEqual(localized("en", ru="Ошибка", en="Error"), "Error")
        self.assertEqual(localized(None, ru="Ошибка", en="Error"), "Ошибка")

    def test_profile_locale_is_normalized_and_validated(self):
        self.assertEqual(ProfileUpdateIn(preferred_locale="EN-us").preferred_locale, "en")
        with self.assertRaises(ValidationError):
            ProfileUpdateIn(preferred_locale="de")
