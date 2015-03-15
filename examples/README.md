Example scripts
===============

Most of these scripts are terribly out of date and are retained in the
hope that they might be updated someday.  Currently useful scripts
are:

 - haymakers.py is an example till configuration file, adapted from
   the one in use at the Haymakers in Cambridge.

 - login-scripts/ may still be useful in setting up automatic startup
   of the till on Ubuntu server or other upstart-based systems.

 - django-project/ is a complete Django-based web service making use
   of the quicktill.tillweb module.  To set up the web service, use a
   command like "django-admin startproject
   --template=quicktill/examples/django-project tillweb" while in the
   till user's home directory, then edit tillweb/tillweb/settings.py
   as appropriate.
