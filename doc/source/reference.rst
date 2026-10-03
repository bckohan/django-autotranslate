.. include:: ./refs.rst

.. _reference:

=========
Reference
=========

.. automodule:: autotranslate

.. _autotranslate:

``autotranslate``
-----------------

.. autoclass:: autotranslate.management.commands.autotranslate.Command
    :members:

.. _services:

Services
--------

.. autoclass:: autotranslate.services.TranslatorService
    :members:

.. autoclass:: autotranslate.services.GoogleTranslatorService
    :members:

.. autoclass:: autotranslate.services.GoogleAPITranslatorService
    :members:

.. autoclass:: autotranslate.services.AmazonTranslateTranslatorService
    :members:

.. _config:

Config
------

.. automodule:: autotranslate.config
    :members:

.. _protect:

Placeholder and markup protection
---------------------------------

.. automodule:: autotranslate.protect.pipeline
    :members:

.. automodule:: autotranslate.protect.parse
    :members: parse, newlines

.. automodule:: autotranslate.protect.segments
    :members:

.. automodule:: autotranslate.protect.guards
    :members: Guard, TokenGuard, HTMLGuard, same_opaques

.. automodule:: autotranslate.protect.repair
    :members: repair, match_edges

.. automodule:: autotranslate.protect.formats
    :members: printf, brace, tokenizers_for

.. automodule:: autotranslate.protect.html
    :members: html, OPAQUE_ELEMENTS, VOID_ELEMENTS
