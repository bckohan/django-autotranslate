from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _

from .services import BaseTranslatorService, GoogleTranslatorService

SERVICE_SETTING = "AUTOTRANSLATE_TRANSLATOR_SERVICE"


def get_translator() -> BaseTranslatorService:
    """
    Returns the default translator.
    """
    translator = getattr(settings, SERVICE_SETTING, GoogleTranslatorService)
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
    if translator is None or not issubclass(BaseTranslatorService, translator):
        raise ImproperlyConfigured(
            _(
                "The translator service '{translator}' specified in {setting} "
                "does not subclass BaseTranslatorService."
            ).format(translator=translator, setting=f"settings.{SERVICE_SETTING}")
        )
    return translator()
