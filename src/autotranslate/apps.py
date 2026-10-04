from django.apps import AppConfig


class AutoTranslateConfig(AppConfig):
    name = "autotranslate"
    # a product name, so it is not translated
    verbose_name = "Django Autotranslate"
