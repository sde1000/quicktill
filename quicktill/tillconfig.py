"""This module is referred to by all the other modules that make up
the till software for global till configuration.  It is expected that
the local till configuration file will import this module and replace
most of the entries here.

"""

from . import keyboard

configversion="tillconfig.py"

pubname="Test Pub Name"
pubnumber="07715 422132"
pubaddr=("31337 Beer Street","Burton","ZZ9 9AA")

# Test multi-character currency name... monopoly money!
currency="MPL"

kbtype=1

cashback_limit=50.0

def pricepolicy(sd,qty):
    """How much does qty of stock item sd cost? qty is a float,
    eg. 1.0 or 0.5, and sd is a dictionary as returned by
    td.stock_info()

    """
    return qty*sd['saleprice']

def qtystring(qty,unitname):
    if qty==1.0:
        qtys=unitname
    elif qty==0.5:
        qtys="half %s"%unitname
    else:
        qtys="%.1f %s"%(qty,unitname)
        if qtys=='4.0 pint': qtys='4pt jug'
        if qtys=='2.0 25ml': qtys='double'
        if qtys=='2.0 50ml': qtys='double'
    return qtys

def fc(a):
    """Format currency, using the configured currency symbol."""
    if a is None: return "None"
    return "%s%s"%(currency,a)

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

# modkeyinfo is a dictionary of modifiers (eg. Half, Double, Jug), which
# containes tuples of (quantity, [list of acceptable departments])
modkeyinfo={}

# Is the "No Sale" function enabled?
nosale=True

# Do we print check digits on stock labels?
checkdigit_print=False
# Do we ask the user to input check digits when using stock?
checkdigit_on_usestock=False

# Do we allow transactions to be stored for use as tabs?
allow_tabs=True

# Does the card popup ask for cashback before receipt number?
cashback_first=False

# Pre-defined transaction notes
transaction_notes=[
    "","Kitchen tab","Staff tab","Party tab","Brewery tab","Festival staff tab"]

# Hook that is called whenever an item of stock is put on sale, with
# the output of td.stock_info() as an argument.
def usestock_hook(sd):
    pass

transaction_to_free_drinks_function=False

pingapint_api=None

btcmerch_api=None
