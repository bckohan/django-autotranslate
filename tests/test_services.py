import asyncio
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import polib
from django.core.management import call_command
from django.test import TestCase

from autotranslate.services import GoogleTranslatorService

DATA_DIR = Path(__file__).parent / "data"


class FakeGoogletransTranslator:
    """
    Stands in for googletrans.Translator. Like the real client, it breaks if it is
    used from more than one event loop or after it has been closed.
    """

    instances: list["FakeGoogletransTranslator"] = []

    def __init__(self):
        self.loop = None
        self.closed = False
        self.calls = 0
        self.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.closed = True

    async def translate(self, text, dest, src):
        loop = asyncio.get_running_loop()
        if self.loop is None:
            self.loop = loop
        if self.loop is not loop or self.closed:
            raise RuntimeError("Event loop is closed")
        self.calls += 1

        def result(string):
            return SimpleNamespace(text=f"[{dest}] {string}")

        if isinstance(text, list):
            return [result(string) for string in text]
        return result(text)


class GoogleTranslatorServiceTestCase(TestCase):
    def setUp(self):
        FakeGoogletransTranslator.instances = []
        patcher = mock.patch("googletrans.Translator", FakeGoogletransTranslator)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reuses_client_in_with_block(self):
        with GoogleTranslatorService() as service:
            self.assertEqual("[de] City", service.translate_string("City", "de"))
            self.assertEqual(
                ["[es] City", "[es] Cities"],
                list(service.translate_strings(["City", "Cities"], "es")),
            )
            self.assertEqual(
                ["[fr] Location"], list(service.translate_strings(["Location"], "fr"))
            )

        self.assertEqual(1, len(FakeGoogletransTranslator.instances))
        translator = FakeGoogletransTranslator.instances[0]
        self.assertEqual(3, translator.calls)
        self.assertTrue(translator.closed)

    def test_repeated_calls_outside_with_block(self):
        service = GoogleTranslatorService()
        self.assertEqual("[de] City", service.translate_string("City", "de"))
        self.assertEqual(
            ["[es] City", "[es] Cities"],
            list(service.translate_strings(["City", "Cities"], "es")),
        )

        self.assertEqual(2, len(FakeGoogletransTranslator.instances))
        self.assertTrue(all(tr.closed for tr in FakeGoogletransTranslator.instances))

    def test_service_reusable_after_with_block(self):
        service = GoogleTranslatorService()
        with service:
            service.translate_string("City", "de")
        self.assertEqual("[es] City", service.translate_string("City", "es"))
        with service:
            self.assertEqual("[fr] City", service.translate_string("City", "fr"))
        self.assertEqual(3, len(FakeGoogletransTranslator.instances))

    def test_command_uses_one_client_for_all_files(self):
        locale_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, locale_dir)
        for lang in ["de", "es", "fr"]:
            messages = locale_dir / lang / "LC_MESSAGES"
            messages.mkdir(parents=True)
            shutil.copy(DATA_DIR / "django.po", messages / "django.po")

        call_command(
            "autotranslate",
            "--path",
            str(locale_dir),
            "--service",
            "autotranslate.services.GoogleTranslatorService",
        )

        for lang in ["de", "es", "fr"]:
            po = polib.pofile(str(locale_dir / lang / "LC_MESSAGES" / "django.po"))
            self.assertEqual(f"[{lang}] Location", po[0].msgstr)
            self.assertEqual(f"[{lang}] City", po[1].msgstr_plural[0])

        self.assertEqual(1, len(FakeGoogletransTranslator.instances))
        self.assertEqual(3, FakeGoogletransTranslator.instances[0].calls)
        self.assertTrue(FakeGoogletransTranslator.instances[0].closed)
