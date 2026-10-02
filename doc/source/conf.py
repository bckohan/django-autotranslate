import os
import shutil
import sys
from pathlib import Path

import django
from sphinx.ext.autodoc import between

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
django.setup()

import autotranslate

project = autotranslate.__title__
copyright = autotranslate.__copyright__
author = autotranslate.__author__
release = autotranslate.__version__

extensions = [
    "sphinxcontrib_django",
    "sphinx.ext.intersphinx",
    "sphinx.ext.autodoc",
    "sphinx.ext.todo",
    "sphinx_tabs.tabs",
    "sphinxcontrib.typer",
    "sphinx.ext.viewcode",
]

templates_path = ["_templates"]
exclude_patterns = []

html_theme = "furo"
html_theme_options = {
    "source_repository": "https://github.com/ankitpopli1891/django-autotranslate/",
    "source_branch": "master",
    "source_directory": "doc/source",
}
html_title = f"{project} {release}"

html_static_path = ["_static"]
html_css_files = ["style.css"]

todo_include_todos = True

latex_engine = "xelatex"

suppress_warnings = ["app.add_directive"]

autodoc_typehints = "description"
autodoc_typehints_format = "short"

intersphinx_mapping = {
    "django": (
        "https://docs.djangoproject.com/en/stable",
        "https://docs.djangoproject.com/en/stable/_objects/",
    ),
    "django-typer": ("https://django-typer.readthedocs.io/en/stable", None),
    "python": ("https://docs.python.org/3", None),
}

linkcheck_allow_redirects = True


def setup(app):
    # Register a sphinx.ext.autodoc.between listener to ignore everything
    # between lines that contain the word IGNORE
    app.connect(
        "autodoc-process-docstring", between("^.*[*]{79}.*$", exclude=True)
    )

    # https://sphinxcontrib-typer.readthedocs.io/en/latest/howto.html#build-to-multiple-formats
    if Path(app.doctreedir).exists():
        shutil.rmtree(app.doctreedir)
    return app
