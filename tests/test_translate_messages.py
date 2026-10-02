import shutil
import tempfile
from pathlib import Path

import polib
from django.core.management import call_command
from django.test import TestCase

from autotranslate.management.commands.translate_messages import Command
from autotranslate.services import TranslatorService

DATA_DIR = Path(__file__).parent / "data"


class FakeTranslatorService(TranslatorService):
    """Upper-cases strings and tags them with the target language."""

    def translate_string(self, text, target_language, source_language="en"):
        return f"[{target_language}] {text.upper()}"

    def translate_strings(self, strings, target_language, source_language="en"):
        for text in strings:
            yield self.translate_string(text, target_language, source_language)


class HumanizeTestCase(TestCase):
    def setUp(self):
        self.service = TranslatorService()

    def test_named_placeholders(self):
        humanize = self.service.humanize_placeholders
        self.assertEqual("foo __item__ bar", humanize("foo %(item)s bar"))
        self.assertEqual("foo __item_name__ bar", humanize("foo %(item_name)s bar"))
        self.assertEqual("foo % (item)s bar", humanize("foo % (item)s bar"))

    def test_positional_placeholders(self):
        humanize = self.service.humanize_placeholders
        self.assertEqual("foo __item__ bar", humanize("foo %s bar"))
        self.assertEqual("foo __number__ bar", humanize("foo %d bar"))
        self.assertEqual("foo __item__ bar __item__", humanize("foo %s bar %s"))
        self.assertEqual("foo __item____item__", humanize("foo %s%s"))


class RestoreTestCase(TestCase):
    def test_restore_placeholders(self):
        restore = TranslatorService().restore_placeholders
        self.assertEqual(
            "baz %(item)s zilot",
            restore("foo %(item)s bar", "baz __over__ zilot"),
        )
        self.assertEqual(
            "baz %(item_name)s zilot",
            restore("foo %(item_name)s bar", "baz __item_name__ zilot"),
        )
        self.assertEqual("baz %s zilot", restore("foo %s bar", "baz __item__ zilot"))
        self.assertEqual(
            "baz %s%s zilot",
            restore("foo %s%s bar", "baz __item____item__ zilot"),
        )


class POFileTestCase(TestCase):
    def setUp(self):
        self.cmd = Command()
        self.cmd.service = TranslatorService()
        self.cmd.retranslate = False
        self.cmd.set_fuzzy = False
        self.po = polib.pofile(str(DATA_DIR / "django.po"))

    def test_should_read_single(self):
        strings = self.cmd.get_strings_to_translate(self.po)
        self.assertIn("Location", strings)

    def test_should_update_single(self):
        translations = ["XXXX"]
        entry = self.po[0]
        self.cmd.update_translations([entry], translations)
        self.assertEqual("XXXX", entry.msgstr)
        self.assertTrue(entry.translated())

    def test_should_read_plural(self):
        strings = self.cmd.get_strings_to_translate(self.po)
        self.assertIn("City", strings)
        self.assertIn("Cities", strings)

    def test_should_update_plural(self):
        translations = ["SINGULAR", "PLURAL"]
        entry = self.po[1]
        self.cmd.update_translations([entry], translations)
        self.assertEqual("", entry.msgstr)
        self.assertEqual("SINGULAR", entry.msgstr_plural[0])
        self.assertEqual(
            ["PLURAL"] * (len(entry.msgstr_plural) - 1),
            [v for k, v in entry.msgstr_plural.items() if k != 0],
        )
        self.assertTrue(entry.translated())

    def test_skips_translated_unless_retranslate(self):
        self.po[0].msgstr = "Ort"
        self.assertNotIn("Location", self.cmd.get_strings_to_translate(self.po))
        self.cmd.retranslate = True
        self.assertIn("Location", self.cmd.get_strings_to_translate(self.po))


class TranslateMessagesCommandTestCase(TestCase):
    service = f"{__name__}.FakeTranslatorService"

    def setUp(self):
        self.locale_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.locale_dir)
        for lang in ["de", "es"]:
            messages = self.locale_dir / lang / "LC_MESSAGES"
            messages.mkdir(parents=True)
            shutil.copy(DATA_DIR / "django.po", messages / "django.po")

    def po(self, lang):
        return polib.pofile(str(self.locale_dir / lang / "LC_MESSAGES" / "django.po"))

    def test_translate_all_locales(self):
        call_command(
            "translate_messages",
            "--path",
            str(self.locale_dir),
            "--service",
            self.service,
        )
        for lang in ["de", "es"]:
            po = self.po(lang)
            self.assertEqual(f"[{lang}] LOCATION", po[0].msgstr)
            self.assertEqual(f"[{lang}] CITY", po[1].msgstr_plural[0])
            self.assertEqual(f"[{lang}] CITIES", po[1].msgstr_plural[1])
            self.assertNotIn("fuzzy", po[0].flags)

    def test_translate_one_locale_fuzzy(self):
        call_command(
            "translate_messages",
            "--path",
            str(self.locale_dir),
            "--service",
            self.service,
            "--locale",
            "es",
            "--set-fuzzy",
        )
        self.assertEqual("", self.po("de")[0].msgstr)
        es = self.po("es")
        self.assertEqual("[es] LOCATION", es[0].msgstr)
        self.assertIn("fuzzy", es[0].flags)

    def test_invalid_service(self):
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            call_command(
                "translate_messages",
                "--path",
                str(self.locale_dir),
                "--service",
                "autotranslate.config.language_codes",
            )
