"""This module is referred to by all the other modules that make up
the till software for global till configuration.  It is expected that
the local till configuration file will import this module and replace
most of the entries here.

"""

from . import keyboard
from .models import penny

configversion="tillconfig.py"

pubname="Test Pub Name"
pubnumber="07715 422132"
pubaddr=("31337 Beer Street","Burton","ZZ9 9AA")

# Test multi-character currency name... monopoly money!
currency="MPL"

hotkeys={}

all_payment_methods=[]
payment_methods=[]

def pricepolicy(si,qty):
    """How much does qty of stock item sd cost? qty is a Decimal,
    eg. 1.0 or 0.5, and si is a StockItem

    """
    return qty*si.stocktype.saleprice

def fc(a):
    """Format currency, using the configured currency symbol."""
    if a is None: return "None"
    return "%s%s"%(currency,a.quantize(penny))

def priceguess(dept,cost,abv):
    """Guess a suitable selling price for a new stock item.  Return a
    price, or None if there is no suitable guess available.  'cost' is
    the cost price _per unit_, eg. per pint for beer.

    """
    return None

def deptkeycheck(dept,price):
    """Check that the price entered when a department key is pressed is
    appropriate for that department.  Returns either None (no problem
    found), a string or a list of strings to display to the user.

    """
    return None

# Is the "No Sale" function enabled?
nosale=True

# Do we print check digits on stock labels?
checkdigit_print=False
# Do we ask the user to input check digits when using stock?
checkdigit_on_usestock=False

# Do we allow transactions to be stored for use as tabs?
allow_tabs=True

# Pre-defined transaction notes
transaction_notes=[
    "","Kitchen tab","Staff tab","Party tab","Brewery tab","Festival staff tab"]

# Hook that is called whenever an item of stock is put on sale, with
# a StockItem and StockLine as the arguments
def usestock_hook(stock,line):
    pass

transaction_to_free_drinks_function=False

database=None

firstpage=None

# Called by ui code whenever a usertoken is processed by the default
# page's hotkey handler
def usertoken_handler(t):
    pass
