from importlib.util import find_spec

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _

from .services import TranslatorService

RICH_INSTALLED = find_spec("rich") is not None
SERVICE_SETTING = "AUTOTRANSLATE_SERVICE"
DEFAULT_SERVICE = "autotranslate.services.GoogleTranslatorService"


def get_service_import_path() -> str:
    return getattr(
        settings,
        SERVICE_SETTING,
        getattr(settings, "AUTOTRANSLATE_TRANSLATOR_SERVICE", DEFAULT_SERVICE),
    )


def get_translator(service_path: str | None = None) -> TranslatorService:
    """
    Returns an instantiated service of the configured translator or the translator at
    the given path.

    :param service_path: The path to the translator service to use if different from
        settings.AUTOTRANSLATE_SERVICE.
    :raises ImproperlyConfigured: If the service path is not a valid translator service
        or if the service path does not subclass TranslatorService.
    :return: An instantiated translator service.
    """
    translator = service_path or get_service_import_path()
    if isinstance(translator, str):
        try:
            translator = import_string(translator)
        except ImportError as ie:
            raise ImproperlyConfigured(
                _(
                    "Could not import the translator service '{translator}' specified "
                    "in {setting}."
                ).format(translator=translator, setting=f"settings.{SERVICE_SETTING}")
            ) from ie
    if translator is None or not issubclass(TranslatorService, translator):
        raise ImproperlyConfigured(
            _(
                "The translator service '{translator}' specified in {setting} "
                "does not subclass TranslatorService."
            ).format(translator=translator, setting=f"settings.{SERVICE_SETTING}")
        )
    return translator()


def language_codes() -> dict[str, str]:
    """
    Get a mapping of language codes to their names from Django settings.
    """
    return {code: name for code, name in getattr(settings, "LANGUAGES", {})}
