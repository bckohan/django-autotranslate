import os
import typing as t
from functools import cached_property
from pathlib import Path

import polib
from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import CommandError
from django.utils.translation import gettext_lazy as _
from django_typer.completers.apps import app_labels
from django_typer.completers.path import directories, import_paths
from django_typer.completers.settings import languages
from django_typer.management import TyperCommand
from django_typer.parsers.apps import app_config
from typer import Option

from ...config import (
    RICH_INSTALLED,
    SERVICE_SETTING,
    get_service_import_path,
    get_translator,
    language_codes,
)
from ...services import TranslatorService


class Command(TyperCommand, rich_markup_mode="markdown"):
    """
    .. typer:: autotranslate.management.commands.translate_messages.Command:typer_app
        :prog: django-admin translate_messages
        :width: 80
        :show-nested:
        :convert-png: latex
        :theme: dark
    """

    help = _(
        "Machine translate all the message files that have been generated "
        "using the {makemessages} command in the given apps or directories. By "
        "default, only directories in {locale_paths} are translated."
    ).format(
        makemessages=(
            "[makemessages]"
            "(https://docs.djangoproject.com/en/stable/ref/django-admin/#django-admin-makemessages)"
        )
        if RICH_INSTALLED
        else "makemessages",
        locale_paths=(
            "[LOCALE_PATHS]"
            "(https://docs.djangoproject.com/en/stable/ref/settings/#locale-paths)"
        )
        if RICH_INSTALLED
        else "LOCALE_PATHS",
    )

    paths: t.List[Path] = []
    apps: t.List[AppConfig] = []
    retranslate: bool = False
    set_fuzzy: bool = False
    source_language: str = "en"

    to_translate: t.List[Path] = []
    apps: t.List[AppConfig] = []

    service: TranslatorService

    @cached_property
    def language_codes(self) -> t.Dict[str, str]:
        return language_codes()

    def handle(
        self,
        paths: t.Annotated[
            t.List[Path],
            Option(
                "--path",
                "-p",
                help=_(
                    "The path(s) to the locale directories containing the .po files to "
                    "translate."
                ),
                shell_complete=directories,
            ),
        ] = paths,
        apps: t.Annotated[
            t.List[AppConfig],
            Option(
                "--app",
                "-a",
                help=_("The app(s) to translate messages for."),
                parser=app_config,
                shell_complete=app_labels,
            ),
        ] = apps,
        locale: t.Annotated[
            t.List[str],
            Option(
                "--locale",
                "-l",
                help=_(
                    "Translate the message files for the given locale(s) (e.g. pt_BR). "
                    "By default, translations will be generated for all locales "
                    "supported by the configured translator service."
                ),
                shell_complete=languages,
            ),
        ] = [],
        retranslate: t.Annotated[
            bool,
            Option(
                "--retranslate",
                "-r",
                help=_("Re-translate messages that already have translations."),
            ),
        ] = retranslate,
        set_fuzzy: t.Annotated[
            bool,
            Option(
                "--set-fuzzy",
                "-f",
                help=_("Set the fuzzy flag on translated messages."),
            ),
        ] = set_fuzzy,
        source_language: t.Annotated[
            str,
            Option(
                "--source-language",
                "-s",
                help=_("Set the source language used for translation."),
                shell_complete=languages,
            ),
        ] = source_language,
        service: t.Annotated[
            str,
            Option(
                "--service",
                help=_(
                    "The translation service to use if different than the configured "
                    "service in settings (settings.{setting})."
                ).format(setting=SERVICE_SETTING),
                shell_complete=import_paths,
            ),
        ] = get_service_import_path(),
    ):
        if not getattr(settings, "USE_I18N", False):
            raise ImproperlyConfigured(
                _("{framework} framework is disabled").format(framework="i18n")
            )

        self.service = get_translator(service)
        self.locale = locale
        self.retranslate = retranslate
        self.set_fuzzy = set_fuzzy
        self.source_language = source_language
        self.to_translate = paths
        for app in apps:
            # get locale path from app directory
            # and add it to the list of paths
            self.to_translate.append(Path(app.path) / "locale")

        if not self.to_translate:
            self.to_translate = [
                Path(pth) for pth in getattr(settings, "LOCALE_PATHS", [])
            ]

        if not self.to_translate:
            raise CommandError(
                _(
                    "Nothing to translate. Please provide a path or app or configure "
                    "{setting}"
                ).format(setting="settings.LOCALE_PATHS")
            )

        for directory in self.to_translate:
            # walk through all the paths
            # and find all the pot files

            if not directory.exists():
                self.secho(
                    _("Directory `{}` does not exist.").format(directory),
                    fg="red",
                )
                continue

            for root, dirs, files in os.walk(directory):
                root = Path(root)
                for file in files:
                    if not file.endswith(".po"):
                        # process file only
                        # if its a pot file
                        continue

                    # get the target language from the parent folder name
                    target_language = root.name

                    if self.locale and target_language not in self.locale:
                        self.secho(
                            _("Skipping translation for locale `{}`").format(
                                target_language
                            ),
                            fg="yellow",
                        )
                        continue

                    self.translate_file(root / file, target_language)

    def translate_file(self, po_file: Path, target_language: str):
        """
        Translate the given pot file to the target language.

        :param po_file: The path to the pot file to translate
        :param target_language: The language to translate the file into
        """
        self.secho(
            _("Translating {file} into `{target_language}`").format(
                file=po_file,
                target_langauge=self.language_codes.get(
                    target_language, target_language
                ),
            ),
            fg="blue",
        )

        po = polib.pofile(po_file)
        strings = self.get_strings_to_translate(po)

        # translate the strings,
        # all the translated strings are returned
        # in the same order on the same index
        # viz. [a, b] -> [trans_a, trans_b]
        translated_strings = self.service.translate_strings(
            strings, target_language, self.source_language, False
        )
        self.update_translations(po, translated_strings)
        po.save()

    def need_translate(self, entry):
        return not entry.obsolete and (
            not (self.skip_translated and entry.translated())
        )

    def get_strings_to_translate(self, po: polib.POFile) -> t.Iterable[str]:
        """Return list of string to translate from po file.

        :param po: POFile object to translate
        :return: list of string to translate
        """
        strings = []
        for index, entry in enumerate(po):
            if not self.need_translate(entry):
                continue
            strings.append(self.service.humanize_placeholders(entry.msgid))
            if entry.msgid_plural:
                strings.append(self.service.humanize_placeholders(entry.msgid_plural))
        return strings

    def update_translations(self, entries, translated_strings):
        """
        Update translations in entries.

        The order and number of translations should match to get_strings_to_translate()
        result.

        :param entries: list of entries to translate
        :type entries: collections.Iterable[polib.POEntry] | polib.POFile
        :param translated_strings: list of translations
        :type translated_strings: collections.Iterable[six.text_type]
        """
        translations = iter(translated_strings)
        for entry in entries:
            if not self.need_translate(entry):
                continue

            if entry.msgid_plural:
                # fill the first plural form with the entry.msgid translation
                translation = next(translations)
                translation = self.service.fix_translation(entry.msgid, translation)
                entry.msgstr_plural[0] = translation

                # fill the rest of plural forms with the entry.msgid_plural translation
                translation = next(translations)
                translation = self.service.fix_translation(
                    entry.msgid_plural, translation
                )
                for k, v in entry.msgstr_plural.items():
                    if k != 0:
                        entry.msgstr_plural[k] = translation
            else:
                translation = next(translations)
                translation = self.service.fix_translation(entry.msgid, translation)
                entry.msgstr = translation

            # Set the 'fuzzy' flag on translation
            if self.set_fuzzy and "fuzzy" not in entry.flags:
                entry.flags.append("fuzzy")
