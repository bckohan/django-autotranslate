import shutil
import tempfile
from unittest import mock
from pathlib import Path

import polib
from django.core.management import call_command
from django.test import TestCase

from autotranslate.management.commands.autotranslate import Command
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
            "autotranslate",
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
            "autotranslate",
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
                "autotranslate",
                "--path",
                str(self.locale_dir),
                "--service",
                "autotranslate.config.language_codes",
            )


class BracePlaceholderTestCase(TestCase):
    def setUp(self):
        self.service = TranslatorService()

    def test_humanize_brace_placeholders(self):
        humanize = self.service.humanize_placeholders
        self.assertEqual("foo __name__ bar", humanize("foo {name} bar"))
        self.assertEqual("foo __item__ bar", humanize("foo {} bar"))
        self.assertEqual("{{literal}}", humanize("{{literal}}"))

    def test_restore_named_placeholders_by_name(self):
        # translations may reorder named placeholders
        self.assertEqual(
            "{target} から {file} へ",
            self.service.restore_placeholders(
                "Translating {file} into {target}", "__target__ から __file__ へ"
            ),
        )
        self.assertEqual(
            "%(b)s y %(a)s",
            self.service.restore_placeholders("%(a)s and %(b)s", "__b__ y __a__"),
        )

    def test_validate_translation(self):
        validate = self.service.validate_translation
        self.assertTrue(validate("{file} into {lang}", "{lang} から {file}"))
        self.assertFalse(validate("{file} into {lang}", "{Datei} in {lang}"))
        self.assertFalse(validate("%(name)s saved", "guardado"))
        self.assertTrue(validate("No placeholders", "Sin marcadores"))


class GoogleLanguageMapTestCase(TestCase):
    def test_service_language(self):
        from autotranslate.services import GoogleTranslatorService

        service = GoogleTranslatorService()
        self.assertEqual("de", service.service_language("de"))
        self.assertEqual("pt", service.service_language("pt-br"))
        self.assertEqual("zh-cn", service.service_language("zh-hans"))
        self.assertEqual("zh-tw", service.service_language("zh-hant"))
        self.assertEqual("no", service.service_language("nb"))
        self.assertIsNone(service.service_language("sr-latn"))
        self.assertIsNone(service.service_language("ia"))


class LocaleHandlingTestCase(TestCase):
    service = f"{__name__}.FakeTranslatorService"

    def setUp(self):
        self.locale_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.locale_dir)

    def make_po(self, locale, entries):
        messages = self.locale_dir / locale / "LC_MESSAGES"
        messages.mkdir(parents=True)
        po = polib.POFile()
        for msgid in entries:
            po.append(polib.POEntry(msgid=msgid, msgstr=""))
        po.save(str(messages / "django.po"))

    def read_po(self, locale):
        return polib.pofile(str(self.locale_dir / locale / "LC_MESSAGES" / "django.po"))

    def translate(self, *args):
        call_command(
            "autotranslate",
            "--path",
            str(self.locale_dir),
            "--service",
            self.service,
            *args,
        )

    def test_locale_folder_converted_to_language_code(self):
        self.make_po("pt_BR", ["Hello"])
        self.translate()
        self.assertEqual("[pt-br] HELLO", self.read_po("pt_BR")[0].msgstr)

    def test_locale_filter_accepts_locale_or_language(self):
        for locale_arg in ["pt-br", "pt_BR"]:
            with self.subTest(locale_arg=locale_arg):
                shutil.rmtree(self.locale_dir)
                self.make_po("pt_BR", ["Hello"])
                self.make_po("de", ["Hello"])
                self.translate("-l", locale_arg)
                self.assertEqual("[pt-br] HELLO", self.read_po("pt_BR")[0].msgstr)
                self.assertEqual("", self.read_po("de")[0].msgstr)

    def test_unsupported_language_skipped(self):
        self.make_po("ia", ["Hello"])
        self.make_po("de", ["Hello"])
        with mock.patch.object(
            FakeTranslatorService,
            "service_language",
            lambda self, language: None if language == "ia" else language,
        ):
            self.translate()
        self.assertEqual("", self.read_po("ia")[0].msgstr)
        self.assertEqual("[de] HELLO", self.read_po("de")[0].msgstr)

    def test_mismatched_placeholders_discarded(self):
        # without humanizing, FakeTranslatorService upper-cases the placeholder names
        self.make_po("de", ["Hello {name}", "Hello %(name)s", "Plain"])
        with mock.patch.object(
            FakeTranslatorService, "humanize_placeholders", lambda self, msgid: msgid
        ):
            self.translate()
        po = self.read_po("de")
        self.assertEqual("", po[0].msgstr)
        self.assertEqual("", po[1].msgstr)
        self.assertEqual("[de] PLAIN", po[2].msgstr)


class FuzzyHandlingTestCase(TestCase):
    """
    Entry states:
        empty           - no translation
        changed         - makemessages marked it fuzzy because the source changed
        pending review  - fuzzy without a previous msgid (e.g. a --set-fuzzy draft)
        translated      - translated and not fuzzy
    """

    service = f"{__name__}.FakeTranslatorService"

    def setUp(self):
        self.locale_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.locale_dir)
        self.po_path = self.locale_dir / "de" / "LC_MESSAGES" / "django.po"
        self.po_path.parent.mkdir(parents=True)
        po = polib.POFile()
        po.append(polib.POEntry(msgid="empty", msgstr=""))
        po.append(
            polib.POEntry(
                msgid="changed new",
                msgstr="old translation",
                flags=["fuzzy", "python-format"],
                previous_msgid="changed old",
            )
        )
        po.append(
            polib.POEntry(msgid="pending review", msgstr="draft", flags=["fuzzy"])
        )
        po.append(polib.POEntry(msgid="translated", msgstr="done"))
        po.append(
            polib.POEntry(
                msgid="plural changed",
                msgid_plural="plurals changed",
                msgstr_plural={0: "old", 1: "olds"},
                flags=["fuzzy"],
                previous_msgid="plural old",
                previous_msgid_plural="plurals old",
            )
        )
        po.save(str(self.po_path))

    def translate(self, *args):
        call_command(
            "autotranslate",
            "--path",
            str(self.locale_dir),
            "--service",
            self.service,
            *args,
        )
        return {entry.msgid: entry for entry in polib.pofile(str(self.po_path))}

    def assert_shipped(self, entry, translation):
        self.assertEqual(translation, entry.msgstr)
        self.assertNotIn("fuzzy", entry.flags)
        self.assertIsNone(entry.previous_msgid)

    def assert_for_review(self, entry, translation):
        self.assertEqual(translation, entry.msgstr)
        self.assertIn("fuzzy", entry.flags)
        self.assertIsNone(entry.previous_msgid)

    def test_default(self):
        entries = self.translate()
        self.assert_shipped(entries["empty"], "[de] EMPTY")
        self.assert_shipped(entries["changed new"], "[de] CHANGED NEW")
        # other flags are preserved
        self.assertIn("python-format", entries["changed new"].flags)
        self.assertEqual("draft", entries["pending review"].msgstr)
        self.assertIn("fuzzy", entries["pending review"].flags)
        self.assertEqual("done", entries["translated"].msgstr)

        plural = entries["plural changed"]
        self.assertEqual(
            {0: "[de] PLURAL CHANGED", 1: "[de] PLURALS CHANGED"}, plural.msgstr_plural
        )
        self.assertNotIn("fuzzy", plural.flags)
        self.assertIsNone(plural.previous_msgid)
        self.assertIsNone(plural.previous_msgid_plural)

    def test_set_fuzzy(self):
        entries = self.translate("--set-fuzzy")
        self.assert_for_review(entries["empty"], "[de] EMPTY")
        self.assert_for_review(entries["changed new"], "[de] CHANGED NEW")
        self.assertEqual("draft", entries["pending review"].msgstr)
        self.assertEqual("done", entries["translated"].msgstr)
        self.assertNotIn("fuzzy", entries["translated"].flags)

    def test_drafts_not_retranslated(self):
        self.translate("--set-fuzzy")
        # a second run leaves the drafts made by the first one alone
        with mock.patch.object(
            FakeTranslatorService, "translate_strings"
        ) as translate_strings:
            entries = self.translate("--set-fuzzy")
        translate_strings.assert_not_called()
        self.assert_for_review(entries["empty"], "[de] EMPTY")

    def test_retranslate(self):
        entries = self.translate("--retranslate")
        for msgid in ["empty", "changed new", "pending review", "translated"]:
            self.assert_shipped(entries[msgid], f"[de] {msgid.upper()}")

    def test_retranslate_set_fuzzy(self):
        entries = self.translate("--retranslate", "--set-fuzzy")
        for msgid in ["empty", "changed new", "pending review", "translated"]:
            self.assert_for_review(entries[msgid], f"[de] {msgid.upper()}")
