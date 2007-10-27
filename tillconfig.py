"""This module is referred to by all the other modules that make up
the till software for global till configuration.  It is expected that
the local till configuration file will import this module and replace
most of the entries here.

"""

pubname="Test Pub Name"
pubnumber="07715 422132"
pubaddr=("31337 Beer Street","Burton","ZZ9 9AA")

vatrate=0.0 # Heh!  That ought to warn people if they forget to configure it
vatno="123 4567 89"
companyaddr=(
    "Boring Pub Chain","Any High Street","Any Town","Britain")

# Test multi-character currency name...
currency="GBP"

kbtype=1

has_media_slot=False
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
    return "%s%0.2f"%(currency,a)

def priceguess(dept,cost,abv):
    """Guess a suitable selling price for a new stock item.  Return a
    price, or None if there is no suitable guess available.  'cost' is
    the cost price _per unit_, eg. per pint for beer.

    """
    return None
