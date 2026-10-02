import asyncio
import re
import typing as t

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext as _


class TranslatorService:
    """
    Defines the base methods that should be implemented

    Services are also context managers. Callers that make multiple translation
    calls should use the service in a ``with`` block so that services that hold
    resources (e.g. network clients) can set them up once and tear them down when
    finished. Subclasses that need this should override :meth:`__enter__` and
    :meth:`__exit__`, and must still work when used outside of a ``with`` block.
    """

    supported_languages: t.ClassVar[list[str]] = []

    def __enter__(self) -> t.Self:
        """
        Acquire any resources the service needs for the duration of the block.
        """
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """
        Release any resources acquired in :meth:`__enter__`.
        """

    def translate_string(
        self, text: str, target_language: str, source_language: str = "en"
    ) -> str:
        """
        Returns a single translated string literal for the target language.
        """
        raise NotImplementedError(
            _("{function}() must be overridden.").format(function="translate_string")
        )

    def translate_strings(
        self,
        strings: t.Sequence[str],
        target_language: str,
        source_language: str = "en",
    ) -> t.Generator[str, None, None]:
        """
        Yields containing translated strings for the target language in the same order
        as the input strings.

        :yield: translated strings
        """
        raise NotImplementedError(
            _("{function}() must be overridden.").format(function="translate_strings")
        )

    def humanize_placeholders(self, msgid):
        """Convert placeholders to the (google translate) service friendly form.

        %(name)s -> __name__
        %s       -> __item__
        %d       -> __number__
        """
        return re.sub(
            r"%(?:\((\w+)\))?([sd])",
            lambda match: "__{}__".format(
                match.group(1).lower()
                if match.group(1)
                else "number"
                if match.group(2) == "d"
                else "item"
            ),
            msgid,
        )

    def restore_placeholders(self, msgid, translation):
        """Restore placeholders in the translated message."""
        placehoders = re.findall(r"(\s*)(%(?:\(\w+\))?[sd])(\s*)", msgid)
        return re.sub(
            r"(\s*)(__[\w]+?__)(\s*)",
            lambda matches: (
                f"{placehoders[0][0]}{placehoders[0][1]}{placehoders.pop(0)[2]}"
            ),
            translation,
        )

    def fix_translation(self, msgid, translation):
        # Google Translate removes a lot of formatting, these are the fixes:
        # - Add newline in the beginning if msgid also has that
        if msgid.startswith("\n") and not translation.startswith("\n"):
            translation = "\n" + translation

        # - Add newline at the end if msgid also has that
        if msgid.endswith("\n") and not translation.endswith("\n"):
            translation += "\n"

        # Remove spaces that have been placed between %(id) tags
        translation = self.restore_placeholders(msgid, translation)
        return translation


class GoogleTranslatorService(TranslatorService):
    """
    Uses the free web-based API for translating.
    https://github.com/ssut/py-googletrans
    """

    # googletrans clients hold an httpx.AsyncClient that is bound to the event loop
    # it first runs on, so the client and the loop must share the same lifetime
    _runner: asyncio.Runner | None = None
    _translator: t.Any = None

    @staticmethod
    async def _open_translator():
        import googletrans

        return await googletrans.Translator().__aenter__()

    def __enter__(self) -> t.Self:
        self._runner = asyncio.Runner()
        try:
            self._translator = self._runner.run(self._open_translator())
        except BaseException:
            self._runner.close()
            self._runner = None
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._runner is None:
            return
        try:
            self._runner.run(self._translator.__aexit__(None, None, None))
        finally:
            self._runner.close()
            self._runner = None
            self._translator = None

    def _translate(self, text, target_language: str, source_language: str):
        if self._runner is not None:
            return self._runner.run(
                self._translator.translate(
                    text, dest=target_language, src=source_language
                )
            )

        # not in a with block - use a single-use client and event loop
        async def translate_once():
            translator = await self._open_translator()
            try:
                return await translator.translate(
                    text, dest=target_language, src=source_language
                )
            finally:
                await translator.__aexit__(None, None, None)

        return asyncio.run(translate_once())

    def translate_string(
        self, text: str, target_language: str, source_language: str = "en"
    ) -> str:
        return self._translate(text, target_language, source_language).text

    def translate_strings(
        self,
        strings: t.Sequence[str],
        target_language: str,
        source_language: str = "en",
    ) -> t.Generator[str, None, None]:
        translations = self._translate(list(strings), target_language, source_language)
        return (item.text for item in translations)


class GoogleAPITranslatorService(TranslatorService):
    """
    Uses the paid Google API for translating.
    https://github.com/google/google-api-python-client
    """

    def __init__(self, max_segments=128):
        try:
            from googleapiclient.discovery import build

            self.developer_key = getattr(settings, "GOOGLE_TRANSLATE_KEY", None)
            if not self.developer_key:
                raise ImproperlyConfigured(
                    _(
                        "`{setting}` is not configured, it is required by `{service}`"
                    ).format(
                        setting="GOOGLE_TRANSLATE_KEY", service=self.__class__.__name__
                    )
                )

            self.service = build("translate", "v2", developerKey=self.developer_key)

            # the google translation API has a limit of max
            # 128 translations in a single request
            # and throws `Too many text segments Error`
            self.max_segments = max_segments
            self.translated_strings = []
        except ImportError as ie:
            raise ImportError(
                _("`{service}` requires the `{package}` package.").format(
                    service=self.__class__.__name__, package="google-api-python-client"
                )
            ) from ie

    def translate_string(
        self, text: str, target_language: str, source_language: str = "en"
    ) -> str:
        response = (
            self.service.translations()
            .list(source=source_language, target=target_language, q=[text])
            .execute()
        )
        return response.get("translations").pop(0).get("translatedText")

    def translate_strings(
        self,
        strings: t.Sequence[str],
        target_language: str,
        source_language: str = "en",
    ) -> t.Generator[str, None, None]:
        while strings:
            response = (
                self.service.translations()
                .list(
                    source=source_language,
                    target=target_language,
                    q=strings[: self.max_segments],
                )
                .execute()
            )
            yield from (t.get("translatedText") for t in response.get("translations"))
            strings = strings[self.max_segments :]


class AmazonTranslateTranslatorService(TranslatorService):
    """
    Uses the paid Amazon Translate for translating.
    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/translate.html
    """

    def __init__(
        self,
    ):
        try:
            import boto3

            self.service = boto3.client("translate")
        except ImportError as ie:
            raise ImportError(
                _("`{service}` requires the `{package}` package").format(
                    service=self.__class__.__name__, package="boto3"
                )
            ) from ie

    def translate_string(
        self, text: str, target_language: str, source_language: str = "en"
    ) -> str:
        response = self.service.translate_text(
            Text=text,
            SourceLanguageCode=source_language,
            TargetLanguageCode=target_language,
        )
        return response["TranslatedText"]

    def translate_strings(
        self, strings: t.Sequence[str], target_language: str, source_language="en"
    ) -> t.Generator[str, None, None]:
        for text in strings:
            yield self.translate_string(text, target_language, source_language)
