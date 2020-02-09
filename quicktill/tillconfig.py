"""This module is referred to by all the other modules that make up
the till software for global till configuration.  It is expected that
the local till configuration file will import this module and replace
most of the entries here.

"""

import datetime
from .models import penny

# Has the --debug flag been set on the command line?
debug = False

configversion = "file:/dev/null"
configname = "default"

keyboard = None
keyboard_right = None

pubname = "Test Pub Name"
pubnumber = "07715 422132"
pubaddr = ("31337 Beer Street", "Burton", "ZZ9 9AA")

# Test multi-character currency name... monopoly money!
currency = "MPL"

hotkeys = {}

all_payment_methods = []
payment_methods = []

def fc(a):
    """Format currency, using the configured currency symbol."""
    if a is None:
        return "None"
    return "".join([currency, str(a.quantize(penny))])

# Do we print check digits on stock labels?
checkdigit_print = False
# Do we ask the user to input check digits when using stock?
checkdigit_on_usestock = False

database = None

firstpage = None

# Called by ui code whenever a usertoken is processed by the default
# page's hotkey handler
def usertoken_handler(t):
    pass
usertoken_listen = None
usertoken_listen_v6 = None

# The user ID to use for creating a page if not otherwise specified.
# An integer if present.
default_user = None

# The options for the "exit / restart" menu.
exitoptions = []

# If not None, an integer exit code to be used when the till is idle
idle_exit_code = None

# The minimum number of seconds the till must run before it can
# consider itself to be idle
minimum_run_time = 30

# The minimum number of seconds the lock screen must be displayed before
# the till can consider itself to be idle
minimum_lock_screen_time = 300

# The time at which this instance of the till was started
start_time = 0.0

# Custom CSS for Gtk
custom_css = None

# How old can a transaction line be before it is unable to be modified
# in place?
max_transline_modify_age = datetime.timedelta(minutes=1)

# When recalling an open transaction, warn if it is older than this
# If set to None, never warn
open_transaction_warn_after = datetime.timedelta(days=2)
