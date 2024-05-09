"""This module is referred to by all the other modules that make up
the till software for global till configuration.  It is expected that
the local till configuration file will import this module and replace
most of the entries here.

"""

from .models import penny
from . import config

# Has the --debug flag been set on the command line?
debug = False

configversion = "file:/dev/null"
configname = "default"
configdescription = "default"

terminal_name = "default"

# A new register_id is generated each time the register is started. It
# is used by the register to ensure each user is only active on one
# register at a time.
register_id = None

keyboard = None
keyboard_right = None

receipt_printer = None
label_printers = []
cash_drawer = None

publogo = config.ConfigItem(
    'core:sitelogo', None, display_name="Site logo",
    description=(
        "Logo image to be printed on receipts.  "
        "To update it, use 'base64 filename | runtill config -s core:sitelogo'"
    )
)
pubname = config.ConfigItem(
    'core:sitename', "Default site name", display_name="Site name",
    description="Site name to be printed on receipts")
pubnumber = config.ConfigItem(
    'core:telephone', "01234 567890", display_name="Telephone number",
    description="Telephone number to be printed on receipts")
pubaddr = config.MultiLineConfigItem(
    'core:address', "31337 Beer Street\nBurton\nZZ9 9AA",
    display_name="Site address",
    description="Site address to be printed on receipts")

currency = config.ConfigItem(
    'core:currency', "", display_name="Currency symbol",
    description="Currency symbol used throughout the system")

hotkeys = {}


def fc(a):
    """Format currency, using the configured currency symbol."""
    if a is None:
        return "None"
    return f"{currency}{a.quantize(penny)}"


database = None

firstpage = None

barcode_listen = None
barcode_listen_v6 = None


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
