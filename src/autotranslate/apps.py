from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AutoTranslateConfig(AppConfig):
    name = "autotranslate"
    verbose_name = _("Django Autotranslate")
