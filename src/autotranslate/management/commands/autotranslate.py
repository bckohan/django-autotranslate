import os
import typing as t
from functools import cached_property
from pathlib import Path

import polib
from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import CommandError
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _
from django.utils.translation import to_language
from django_typer.completers.apps import app_labels
from django_typer.completers.path import directories, import_paths
from django_typer.completers.settings import languages
from django_typer.management import TyperCommand
from django_typer.parsers.apps import app_config
from typer import Option

from ...config import (
    SERVICE_SETTING,
    get_service_import_path,
    get_translator,
    language_codes,
)
from ...services import TranslatorService


class Command(TyperCommand, rich_markup_mode="markdown"):
    """
    .. typer:: autotranslate.management.commands.autotranslate.Command:typer_app
        :prog: django-admin autotranslate
        :width: 80
        :show-nested:
        :convert-png: latex
    """

    help = format_lazy(
        _(
            "Machine translate all the message files that have been generated "
            "using the {makemessages} command in the given apps or directories. By "
            "default, only directories in {locale_paths} are translated."
        ),
        makemessages=(
            "[makemessages]"
            "(https://docs.djangoproject.com/en/stable/ref/django-admin/#django-admin-makemessages)"
        ),
        locale_paths=(
            "[LOCALE_PATHS]"
            "(https://docs.djangoproject.com/en/stable/ref/settings/#locale-paths)"
        ),
    )

    locale: list[str]
    retranslate: bool = False
    set_fuzzy: bool = False
    source_language: str = "en"

    to_translate: list[Path]

    service: TranslatorService

    @cached_property
    def language_codes(self) -> dict[str, str]:
        return language_codes()

    def handle(
        self,
        paths: t.Annotated[
            list[Path] | None,
            Option(
                "--path",
                "-p",
                help=t.cast(
                    str,
                    _(
                        "The path(s) to the locale directories containing the .po "
                        "files to translate."
                    ),
                ),
                shell_complete=directories,
            ),
        ] = None,
        apps: t.Annotated[
            list[AppConfig] | None,
            Option(
                "--app",
                "-a",
                help=t.cast(str, _("The app(s) to translate messages for.")),
                parser=app_config,
                shell_complete=app_labels,
            ),
        ] = None,
        locale: t.Annotated[
            list[str] | None,
            Option(
                "--locale",
                "-l",
                help=t.cast(
                    str,
                    _(
                        "Translate the message files for the given locale(s) (e.g. "
                        "pt_BR). By default, translations will be generated for all "
                        "locales supported by the configured translator service."
                    ),
                ),
                shell_complete=languages,
            ),
        ] = None,
        retranslate: t.Annotated[
            bool,
            Option(
                "--retranslate",
                "-r",
                help=t.cast(
                    str, _("Re-translate messages that already have translations.")
                ),
            ),
        ] = retranslate,
        set_fuzzy: t.Annotated[
            bool,
            Option(
                "--set-fuzzy",
                "-f",
                help=t.cast(
                    str,
                    _(
                        "Mark machine translations as fuzzy so they are reviewed "
                        "before use (fuzzy entries are not compiled by default)."
                    ),
                ),
            ),
        ] = set_fuzzy,
        source_language: t.Annotated[
            str,
            Option(
                "--source-language",
                "-s",
                help=t.cast(str, _("Set the source language used for translation.")),
                shell_complete=languages,
            ),
        ] = source_language,
        service: t.Annotated[
            str,
            Option(
                "--service",
                help=t.cast(
                    str,
                    format_lazy(
                        _(
                            "The translation service to use if different than the "
                            "configured service in settings ({settings}.{setting})."
                        ),
                        settings="settings",
                        setting=SERVICE_SETTING,
                    ),
                ),
                shell_complete=import_paths,
            ),
        ] = get_service_import_path(),
    ):
        if not getattr(settings, "USE_I18N", False):
            raise ImproperlyConfigured(
                _("{framework} framework is disabled").format(framework="i18n")
            )

        self.service = get_translator(service)
        self.locale = locale or []
        self.retranslate = retranslate
        self.set_fuzzy = set_fuzzy
        self.source_language = source_language
        self.to_translate = list(paths or [])
        for app in apps or []:
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

        # use the service as a context manager so it can reuse resources (e.g.
        # network clients) across all of the files we translate
        with self.service:
            for directory in self.to_translate:
                self.translate_directory(directory)

    def translate_directory(self, directory: Path):
        """
        Translate all of the message files found under the given locale directory.

        :param directory: The locale directory to search for message files
        """
        if not directory.exists():
            self.secho(
                _("Directory `{}` does not exist.").format(directory),
                fg="red",
            )
            return

        for root_dir, _dirs, files in os.walk(directory):
            root = Path(root_dir)
            for file in files:
                if not file.endswith(".po"):
                    # process file only
                    # if its a pot file
                    continue

                # get the locale from the <locale>/LC_MESSAGES/ folder name
                locale_name = root.parent.name
                language = to_language(locale_name)

                if (
                    self.locale
                    and locale_name not in self.locale
                    and language not in self.locale
                ):
                    self.secho(
                        _("Skipping translation for locale `{}`").format(locale_name),
                        fg="yellow",
                    )
                    continue

                self.translate_file(root / file, language)

    def translate_file(self, po_file: Path, target_language: str):
        """
        Translate the given pot file to the target language.

        :param po_file: The path to the pot file to translate
        :param target_language: The Django language code (e.g. pt-br) to translate
            the file into
        """
        service_language = self.service.service_language(target_language)
        if service_language is None:
            self.secho(
                _("Skipping {file}: {service} does not support `{language}`").format(
                    file=po_file,
                    service=self.service.__class__.__name__,
                    language=target_language,
                ),
                fg="yellow",
            )
            return

        po = polib.pofile(po_file)
        strings = self.get_strings_to_translate(po)
        if not strings:
            return

        self.secho(
            _("Translating {file} into `{target_language}`").format(
                file=po_file,
                target_language=self.language_codes.get(
                    target_language, target_language
                ),
            ),
            fg="blue",
        )

        # translate the strings,
        # all the translated strings are returned
        # in the same order on the same index
        # viz. [a, b] -> [trans_a, trans_b]
        translated_strings = self.service.translate_strings(
            strings, service_language, self.source_language
        )
        self.update_translations(po, translated_strings)
        po.save()

    def need_translate(self, entry: polib.POEntry) -> bool:
        """
        Should the given entry be machine translated?

        Entries are translated if they have no translation, or if makemessages marked
        them fuzzy because their source string changed (it records the previous
        msgid when it does this). Other fuzzy entries are awaiting review (e.g.
        drafts made with --set-fuzzy) and are left alone unless --retranslate is
        given.

        :param entry: The message file entry
        :return: True if the entry should be translated
        """
        if entry.obsolete:
            return False
        if self.retranslate:
            return True
        if entry.fuzzy:
            return bool(entry.previous_msgid or entry.previous_msgid_plural)
        return not entry.translated()

    def get_strings_to_translate(self, po: polib.POFile) -> list[str]:
        """Return list of string to translate from po file.

        :param po: POFile object to translate
        :return: list of string to translate
        """
        strings = []
        for entry in po:
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
                singular = self.service.fix_translation(entry.msgid, next(translations))
                plural = self.service.fix_translation(
                    entry.msgid_plural, next(translations)
                )
                if not (
                    self.check_translation(entry.msgid, singular)
                    and self.check_translation(entry.msgid_plural, plural)
                ):
                    continue

                # fill the first plural form with the entry.msgid translation
                entry.msgstr_plural[0] = singular

                # fill the rest of plural forms with the entry.msgid_plural translation
                for k in entry.msgstr_plural:
                    if k != 0:
                        entry.msgstr_plural[k] = plural
            else:
                translation = self.service.fix_translation(
                    entry.msgid, next(translations)
                )
                if not self.check_translation(entry.msgid, translation):
                    continue
                entry.msgstr = translation

            # this is now a translation of the current source string
            entry.previous_msgid = None
            entry.previous_msgid_plural = None
            entry.previous_msgctxt = None

            # fuzzy entries are not compiled, so they will not be used until they
            # have been reviewed and the flag removed
            if self.set_fuzzy:
                if "fuzzy" not in entry.flags:
                    entry.flags.append("fuzzy")
            elif "fuzzy" in entry.flags:
                entry.flags.remove("fuzzy")

    def check_translation(self, msgid: str, translation: str) -> bool:
        """
        Check that the translation is safe to use, warning if it is not.

        :param msgid: The source message
        :param translation: The translated message
        :return: True if the translation may be used
        """
        if self.service.validate_translation(msgid, translation):
            return True
        self.secho(
            _(
                "Discarding translation with mismatched placeholders: "
                "{msgid!r} -> {translation!r}"
            ).format(msgid=msgid, translation=translation),
            fg="yellow",
        )
        return False
