.. include:: ./refs.rst

.. _tutorial:

=========================
Tutorial: your first run
=========================

In this tutorial you will create a small Django project, mark a few messages for
translation, machine translate them into German and Spanish, and see the translations
in use. It takes about ten minutes.

You will need Python 3.11 or newer and the `GNU gettext
<https://www.gnu.org/software/gettext/>`_ tools, which Django's
:django-admin:`makemessages` and :django-admin:`compilemessages` commands use. Check
that they are installed:

.. code-block:: console

    $ msgfmt --version

If the command is not found, install gettext (``brew install gettext`` on macOS,
``apt install gettext`` on Debian and Ubuntu).

Create a project
================

Create and activate a virtual environment, then install django-autotranslate, which
also installs Django:

.. code-block:: console

    $ python -m venv .venv
    $ source .venv/bin/activate
    $ pip install django-autotranslate

Create a project and an app:

.. code-block:: console

    $ django-admin startproject mysite .
    $ python manage.py startapp greetings

Configure the languages
=======================

Open ``mysite/settings.py`` and add ``autotranslate`` and the new app to
:setting:`INSTALLED_APPS`:

.. code-block:: python

    INSTALLED_APPS = [
        ...
        "autotranslate",
        "greetings",
    ]

Then, after :setting:`LANGUAGE_CODE`, list the languages your site supports and tell
Django where to keep its message files:

.. code-block:: python

    LANGUAGES = [
        ("en", "English"),
        ("de", "German"),
        ("es", "Spanish"),
    ]

    LOCALE_PATHS = [BASE_DIR / "locale"]

:setting:`USE_I18N` is already ``True`` in a new project, which django-autotranslate
needs.

Write some messages
===================

Create ``greetings/messages.py`` with three messages marked for translation: one with
a placeholder, one with singular and plural forms, and one with HTML markup:

.. code-block:: python

    from django.utils.translation import gettext as _
    from django.utils.translation import ngettext


    def welcome(name, count):
        return [
            _("Welcome back, %(name)s!") % {"name": name},
            ngettext(
                "You have %(count)d new message.",
                "You have %(count)d new messages.",
                count,
            )
            % {"count": count},
            _('Read the <a href="/help/">help pages</a> to get started.'),
        ]

Create the message files
========================

Create the ``locale`` directory and run :django-admin:`makemessages` for German and
Spanish:

.. code-block:: console

    $ mkdir locale
    $ python manage.py makemessages -l de -l es
    processing locale de
    processing locale es

This creates ``locale/de/LC_MESSAGES/django.po`` and
``locale/es/LC_MESSAGES/django.po``. Open the German file. Each message is a
``msgid`` with an empty ``msgstr`` waiting for its translation:

.. code-block:: po

    #: greetings/messages.py:7
    #, python-format
    msgid "Welcome back, %(name)s!"
    msgstr ""

Translate them
==============

Now run ``autotranslate``:

.. code-block:: console

    $ python manage.py autotranslate
    Translating /home/you/mysite/locale/de/LC_MESSAGES/django.po into German
    Translating /home/you/mysite/locale/es/LC_MESSAGES/django.po into Spanish
    Discarded the translation of 'Welcome back, %(name)s!' because its placeholders or
    markup changed: '¡Bienvenido de nuevo, __nombre__!'

The command found both message files in :setting:`LOCALE_PATHS`, worked out each
file's language from its directory name, and sent the empty messages to the free
Google Translate service.

Open the German file again. The messages are translated, and the placeholder and the
link survived translation unchanged:

.. code-block:: po

    #, python-format
    msgid "Welcome back, %(name)s!"
    msgstr "Willkommen zurück, %(name)s!"

    #, python-format
    msgid "You have %(count)d new message."
    msgid_plural "You have %(count)d new messages."
    msgstr[0] "Sie haben %(count)d neue Nachrichten."
    msgstr[1] "Sie haben %(count)d neue Nachrichten."

    msgid "Read the <a href=\"/help/\">help pages</a> to get started."
    msgstr "Lesen Sie die <a href=\"/help/\">Hilfeseiten</a>, um loszulegen."

Notice two things:

* **One Spanish translation was discarded.** The free service only translates plain
  text, so placeholders are sent as word-like tokens such as ``__name__``. Here Google
  translated the token itself into ``__nombre__``. A translation that loses a
  placeholder would break your site, so django-autotranslate discarded it and left
  the message untranslated. Django shows the English text until it is translated.
* **The German singular is wrong.** "Sie haben 1 neue Nachrichten" should be "eine
  neue Nachricht". Machine translations need reviewing, see :ref:`howto-review`.

Use the translations
====================

Compile the message files so Django can use them:

.. code-block:: console

    $ python manage.py compilemessages

Then try them in the Django shell:

.. code-block:: console

    $ python manage.py shell -c "
    from django.utils import translation
    from greetings.messages import welcome
    for language in ['en', 'de', 'es']:
        with translation.override(language):
            print(language, welcome('Ada', 3))
    "
    en ['Welcome back, Ada!', 'You have 3 new messages.', 'Read the <a href="/help/">help pages</a> to get started.']
    de ['Willkommen zurück, Ada!', 'Sie haben 3 neue Nachrichten.', 'Lesen Sie die <a href="/help/">Hilfeseiten</a>, um loszulegen.']
    es ['Welcome back, Ada!', 'Tienes 3 mensajes nuevos.', 'Lea las <a href="/help/">páginas de ayuda</a> para comenzar.']

The discarded Spanish message falls back to English, everything else is translated.

Run it again
============

Run ``autotranslate`` a second time:

.. code-block:: console

    $ python manage.py autotranslate
    Translating /home/you/mysite/locale/es/LC_MESSAGES/django.po into Spanish
    Discarded the translation of 'Welcome back, %(name)s!' because its placeholders or
    markup changed: '¡Bienvenido de nuevo, __nombre__!'

Only the Spanish file had anything left to translate. By default ``autotranslate``
only sends messages that have no translation, or whose English text has changed, so
running it again is cheap and never overwrites existing translations.

Next steps
==========

You have translated a Django project. From here:

* Get more reliable results from a paid service: :ref:`howto-google-cloud` or
  :ref:`howto-amazon`. Paid services are told not to translate placeholders, so they
  rarely need discarding.
* Fit ``autotranslate`` into your workflow: :ref:`howto-update`.
* Learn what happened behind the scenes: :ref:`explanation-how`.
