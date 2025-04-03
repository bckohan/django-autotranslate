import asyncio
import typing as t

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext as _


class BaseTranslatorService:
    """
    Defines the base methods that should be implemented
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


class GoogleTranslatorService(BaseTranslatorService):
    """
    Uses the free web-based API for translating.
    https://github.com/ssut/py-googletrans
    """

    def __init__(self):
        import googletrans

        self.service = googletrans.Translator()

    def translate_string(
        self, text: str, target_language: str, source_language: str = "en"
    ):
        return asyncio.run(
            self.service.translate(text, dest=target_language, src=source_language)
        ).text

    def translate_strings(
        self,
        strings: t.Sequence[str],
        target_language: str,
        source_language: str = "en",
    ) -> t.Generator[str, None, None]:
        translations = asyncio.run(
            self.service.translate(
                list(strings), dest=target_language, src=source_language
            )
        )
        return (item.text for item in translations)


class GoogleAPITranslatorService(BaseTranslatorService):
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


class AmazonTranslateTranslatorService(BaseTranslatorService):
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
