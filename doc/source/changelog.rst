.. include:: ./refs.rst

==========
Change Log
==========

v2.0.0 (unreleased)
===================

* **Breaking:** the ``translate_messages`` management command has been renamed to
  ``autotranslate``.
* Messages whose source string changed (marked fuzzy by ``makemessages``) are now
  retranslated, and fuzzy entries awaiting review are no longer overwritten.
  ``--set-fuzzy`` marks the new machine translations for review.
* Added an optional progress bar (``--progress/--no-progress``), install the
  ``progress`` extra to use it.
* ``AUTOTRANSLATE_SERVICE`` may now be a dictionary with a ``BACKEND`` import path
  and ``OPTIONS`` that configure the service.
* **Breaking:** ``GOOGLE_TRANSLATE_KEY`` has been removed, set the ``api_key`` option
  of ``GoogleAPITranslatorService`` instead.
* **Breaking:** the ``AUTOTRANSLATE_TRANSLATOR_SERVICE`` setting has been removed, use
  ``AUTOTRANSLATE_SERVICE`` instead.

v1.3.0 (2024-08-23)
===================

v1.2.0 (2021-06-06)
===================

v1.1.1 (2020-05-06)
===================

v1.1.0 (2018-05-06)
===================

v1.0.1 (2017-01-14)
===================

v1.0.0 (2016-01-23)
===================

v0.8.0 (2016-01-02)
===================

v0.7.0 (2015-11-10)
===================

v0.6.0 (2015-11-09)
===================

v0.5.0 (2015-10-31)
===================

v0.4.0 (2015-08-07)
===================

v0.3.0 (2015-06-27)
===================

v0.2.0 (2015-04-04)
===================


v0.1.0 (2015-03-08)
===================

* Initial release.
