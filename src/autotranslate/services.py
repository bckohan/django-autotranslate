import asyncio
import contextlib
import re
import time
import typing as t

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext as _

# matches printf style (%s, %d, %(name)s) and brace style ({}, {name}) placeholders
PLACEHOLDER = r"%(?:\((\w+)\))?([sd])|(?<!\{)\{(\w*)\}(?!\})"


def placeholders(text: str) -> list[str]:
    """
    Return the placeholders found in the given message, in order.

    :param text: The message to search for placeholders
    :return: The placeholders (e.g. ``%(name)s`` or ``{name}``) in the message
    """
    return [match.group(0) for match in re.finditer(PLACEHOLDER, text)]


class ServiceUnavailable(Exception):
    """
    Raised when a translation service refuses or fails to fulfil a request (e.g. it
    is rate limiting us).
    """


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

    def service_language(self, language: str) -> str | None:
        """
        Map a Django language code (e.g. ``pt-br``) to the code this service uses
        for that language.

        :param language: The Django language code
        :return: The service's code for the language, or None if the service does
            not support the language.
        """
        return language

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
        {name}   -> __name__
        %s, {}   -> __item__
        %d       -> __number__
        """

        def humanize(match):
            name = match.group(1) or match.group(3)
            if name:
                return f"__{name.lower()}__"
            return "__number__" if match.group(2) == "d" else "__item__"

        return re.sub(PLACEHOLDER, humanize, msgid)

    def restore_placeholders(self, msgid, translation):
        """
        Restore placeholders in the translated message. Named placeholders are
        restored by name because translations may reorder them, any others are
        restored in the order they appear in the msgid.
        """
        # (placeholder, lower case name) - groups: 1 printf name, 3 brace name
        remaining = [
            (match.group(0), (match.group(1) or match.group(3) or "").lower())
            for match in re.finditer(PLACEHOLDER, msgid)
        ]

        def restore(match):
            if not remaining:
                return match.group(0)
            token = match.group(0)[2:-2].lower()
            index = next(
                (idx for idx, ph in enumerate(remaining) if ph[1] and ph[1] == token),
                0,
            )
            return remaining.pop(index)[0]

        return re.sub(r"__\w+?__", restore, translation)

    def validate_translation(self, msgid: str, translation: str) -> bool:
        """
        Check that the translation contains exactly the same placeholders as the
        msgid. Translations that fail this check would break string formatting.

        :param msgid: The source message
        :param translation: The translated message
        :return: True if the translation's placeholders match the msgid's
        """
        return sorted(placeholders(msgid)) == sorted(placeholders(translation))

    def fix_translation(self, msgid, translation):
        # Google Translate removes a lot of formatting, these are the fixes:
        # - Add newline in the beginning if msgid also has that
        if msgid.startswith("\n") and not translation.startswith("\n"):
            translation = "\n" + translation

        # - Add newline at the end if msgid also has that
        if msgid.endswith("\n") and not translation.endswith("\n"):
            translation += "\n"

        # Restore the placeholders that were humanized for translation
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

    # how many times to retry a request that fails with a network error, and the
    # delay in seconds before the first retry (doubled for each subsequent retry)
    retries: int = 3
    retry_delay: float = 1.0
    # the delay in seconds before the first retry when Google rejects a request,
    # usually because we are being rate limited (doubled for each retry)
    rate_limit_delay: float = 30.0

    # Django language codes that do not map directly onto a Google language code.
    # None marks languages Google does not support (e.g. Google's Serbian is
    # Cyrillic only, so it cannot be used for sr-latn).
    language_map: t.ClassVar[dict[str, str | None]] = {
        "zh-hans": "zh-cn",
        "zh-hant": "zh-tw",
        "nb": "no",
        "sr-latn": None,
    }

    def service_language(self, language: str) -> str | None:
        import googletrans

        language = language.lower()
        if language in self.language_map:
            return self.language_map[language]
        if language in googletrans.LANGUAGES:
            return language
        # fall back to the base language for regional variants (e.g. pt-br -> pt)
        base = language.split("-")[0]
        return base if base in googletrans.LANGUAGES else None

    @staticmethod
    async def _open_translator():
        import googletrans

        # by default googletrans silently returns the untranslated text when Google
        # rejects a request, which would write the source text as the translation
        return await googletrans.Translator(raise_exception=True).__aenter__()

    @staticmethod
    async def _call(translator, text, target_language: str, source_language: str):
        try:
            return await translator.translate(
                text, dest=target_language, src=source_language
            )
        except Exception as err:
            # googletrans raises a bare Exception when Google rejects a request
            if str(err).startswith("Unexpected status code"):
                raise ServiceUnavailable(str(err)) from err
            raise

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
        import httpx

        # Google drops long-lived connections and throttles bursts of requests, so
        # retry these failures with a fresh client and an increasing delay
        attempt = 0
        while True:
            try:
                return self._translate_once(text, target_language, source_language)
            except (httpx.TransportError, ServiceUnavailable) as err:
                if attempt >= self.retries:
                    raise
                delay = (
                    self.rate_limit_delay
                    if isinstance(err, ServiceUnavailable)
                    else self.retry_delay
                )
                time.sleep(delay * 2**attempt)
                attempt += 1
                if self._runner is not None:
                    self._reopen_translator()

    def _reopen_translator(self):
        import httpx

        assert self._runner is not None
        # the old connection is already broken, so errors closing it don't matter
        with contextlib.suppress(httpx.TransportError):
            self._runner.run(self._translator.__aexit__(None, None, None))
        self._translator = self._runner.run(self._open_translator())

    def _translate_once(self, text, target_language: str, source_language: str):
        if self._runner is not None:
            return self._runner.run(
                self._call(self._translator, text, target_language, source_language)
            )

        # not in a with block - use a single-use client and event loop
        async def translate_once():
            translator = await self._open_translator()
            try:
                return await self._call(
                    translator, text, target_language, source_language
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
