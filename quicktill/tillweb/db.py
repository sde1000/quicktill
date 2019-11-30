# Access to the till database

import threading

# We use thread-local storage for the current sqlalchemy session.  The
# session lifetime is managed explicitly in views.tillweb_view, and
# the session is accessed as "td.s" - the same way the session is
# accessed in the main till code, although the underlying mechanism is
# different.  NB do not import the "quicktill.td" module!
td = threading.local()
