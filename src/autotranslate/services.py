import asyncio
import contextlib
import re
import time
import typing as t
from functools import cached_property

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

    Services are configured by the ``OPTIONS`` in
    ``settings.AUTOTRANSLATE_SERVICE``, which are passed to the service's
    constructor as keyword arguments.

    Services are also context managers. Callers that make multiple translation
    calls should use the service in a ``with`` block so that services that hold
    resources (e.g. network clients) can set them up once and tear them down when
    finished. Subclasses that need this should override :meth:`__enter__` and
    :meth:`__exit__`, and must still work when used outside of a ``with`` block.
    """

    default_language_map: t.ClassVar[dict[str, str | None]] = {}
    """
    Django language codes that do not map onto the service's language codes by the
    rules in :meth:`service_language`. None marks languages the service does not
    support.
    """

    def __init__(self, *, language_map: dict[str, str | None] | None = None):
        """
        :param language_map: Mappings of Django language codes to the service's
            language codes (or None if the service does not support the language).
            These are added to, or override, :attr:`default_language_map`.
        """
        self.language_map = {**self.default_language_map, **(language_map or {})}

    def __enter__(self) -> t.Self:
        """
        Acquire any resources the service needs for the duration of the block.
        """
        return self

    def supported_languages(self) -> t.Collection[str] | None:
        """
        The language codes this service supports. Override this to enable language
        code matching in :meth:`service_language`. It is called at most once per
        service instance.

        :return: The service's language codes, or None if they are not known.
        """
        return None

    @cached_property
    def _supported_languages(self) -> dict[str, str] | None:
        # lower case code -> the service's code
        supported = self.supported_languages()
        if supported is None:
            return None
        return {code.lower(): code for code in supported}

    def service_language(self, language: str) -> str | None:
        """
        Map a Django language code (e.g. ``pt-br``) to the code this service uses
        for that language. Django language codes are lower case BCP 47 language
        tags. The service's code is resolved in this order:

        1. The language map - :attr:`default_language_map` plus any
           ``language_map`` option.
        2. A case insensitive match against :meth:`supported_languages`.
        3. Dropping region subtags until a supported code is found (e.g. ``pt-br``
           -> ``pt``). Script subtags are never dropped because the result would
           be in the wrong writing system (e.g. ``sr-latn`` -> ``sr`` is Cyrillic).

        If the service's supported languages are not known, the Django language
        code is used as is.

        :param language: The Django language code
        :return: The service's code for the language, or None if the service does
            not support the language.
        """
        language = language.lower()
        language_map = {
            code.lower(): mapped
            for code, mapped in getattr(
                self, "language_map", self.default_language_map
            ).items()
        }
        if language in language_map:
            return language_map[language]

        supported = self._supported_languages
        if supported is None:
            return language

        subtags = language.split("-")
        while subtags:
            candidate = "-".join(subtags)
            if candidate in supported:
                return supported[candidate]
            # script subtags are 4 letters (ISO 15924)
            if len(subtags) == 1 or len(subtags[-1]) == 4:
                break
            subtags.pop()
        return None

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

    # Google's Serbian is Cyrillic only, so it cannot be used for sr-latn
    default_language_map: t.ClassVar[dict[str, str | None]] = {
        "zh-hans": "zh-cn",
        "zh-hant": "zh-tw",
        "nb": "no",
        "sr-latn": None,
    }

    def __init__(
        self,
        *,
        retries: int | None = None,
        retry_delay: float | None = None,
        rate_limit_delay: float | None = None,
        language_map: dict[str, str | None] | None = None,
    ):
        """
        :param retries: How many times to retry a request that fails because of a
            network error or because Google rejected it.
        :param retry_delay: The delay in seconds before retrying a request that
            failed because of a network error (doubled for each retry).
        :param rate_limit_delay: The delay in seconds before retrying a request that
            Google rejected, usually because of rate limiting (doubled for each
            retry).
        :param language_map: Mappings of Django language codes to Google language
            codes (or None if Google does not support the language). These are
            added to, or override, :attr:`default_language_map`.
        """
        super().__init__(language_map=language_map)
        if retries is not None:
            self.retries = retries
        if retry_delay is not None:
            self.retry_delay = retry_delay
        if rate_limit_delay is not None:
            self.rate_limit_delay = rate_limit_delay

    def supported_languages(self) -> t.Collection[str]:
        import googletrans

        return googletrans.LANGUAGES.keys()

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

    # Google's Serbian is Cyrillic only, so it cannot be used for sr-latn. Django's
    # pt is European Portuguese, Google's is Brazilian.
    default_language_map: t.ClassVar[dict[str, str | None]] = {
        "pt": "pt-PT",
        "zh-hans": "zh-CN",
        "zh-hant": "zh-TW",
        "nb": "no",
        "sr-latn": None,
    }

    def __init__(
        self,
        *,
        api_key: str | None = None,
        max_segments: int = 128,
        language_map: dict[str, str | None] | None = None,
    ):
        """
        :param api_key: Your Google Cloud Translation API key (required).
        :param max_segments: The maximum number of strings to send in each request.
            The API rejects requests with more than 128.
        :param language_map: Mappings of Django language codes to Google language
            codes (or None if Google does not support the language). These are
            added to, or override, :attr:`default_language_map`.
        """
        super().__init__(language_map=language_map)
        if not api_key:
            raise ImproperlyConfigured(
                _("The `{option}` option is required by `{service}`.").format(
                    option="api_key", service=self.__class__.__name__
                )
            )
        try:
            from googleapiclient.discovery import build
        except ImportError as ie:
            raise ImportError(
                _("`{service}` requires the `{package}` package.").format(
                    service=self.__class__.__name__, package="google-api-python-client"
                )
            ) from ie

        self.service = build("translate", "v2", developerKey=api_key)
        self.max_segments = max_segments

    def supported_languages(self) -> t.Collection[str]:
        response = self.service.languages().list().execute()
        return [language["language"] for language in response["languages"]]

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

    # Amazon has no Latin script Serbian. Django's pt is European Portuguese,
    # Amazon's is Brazilian.
    default_language_map: t.ClassVar[dict[str, str | None]] = {
        "pt": "pt-PT",
        "zh-hans": "zh",
        "zh-hant": "zh-TW",
        "nb": "no",
        "sr-latn": None,
    }

    def __init__(
        self, *, language_map: dict[str, str | None] | None = None, **client_options
    ):
        """
        :param language_map: Mappings of Django language codes to Amazon language
            codes (or None if Amazon does not support the language). These are
            added to, or override, :attr:`default_language_map`.
        :param client_options: Passed to :func:`boto3.client` (e.g. ``region_name``,
            ``aws_access_key_id``, ``aws_secret_access_key``). Anything not given
            is found by boto3 the usual way (environment variables, ``~/.aws``
            config files, instance roles, ...).
        """
        super().__init__(language_map=language_map)
        try:
            import boto3
        except ImportError as ie:
            raise ImportError(
                _("`{service}` requires the `{package}` package.").format(
                    service=self.__class__.__name__, package="boto3"
                )
            ) from ie

        self.service = boto3.client("translate", **client_options)

    def supported_languages(self) -> t.Collection[str]:
        languages: list[str] = []
        kwargs: dict[str, str] = {}
        while True:
            response = self.service.list_languages(**kwargs)
            languages.extend(lang["LanguageCode"] for lang in response["Languages"])
            if not response.get("NextToken"):
                return languages
            kwargs = {"NextToken": response["NextToken"]}

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
