"""
Help with populating the database with basic configuration information
like the name of the business, the various departments, and VAT rates.

"""
from __future__ import print_function,unicode_literals

template=r"""
# This is a database setup file for quicktill.  It is written in YAML
# (see http://en.wikipedia.org/wiki/YAML)

# Import this file into the till database using the 'dbsetup' command:
# runtill dbsetup this-file

# If you re-import this file, it will update rows in the database
# based on the primary keys.


# It's possible for multiple businesses to sell through the same till.
# Business receipts are separated out by department (the relationship
# is defined later through the VAT rate and department mechanism).

- model:   Business
  id:      1
  name:    Individual Pubs Ltd
  abbrev:  IPL
  address: |
    Pegasus House
    Pembroke Avenue
    Waterbeach
    Cambridge CB25 9PY
  vatno:   783 9983 50

- model:   Business
  id:      2
  name:    A Chef
  abbrev:  Chef
  address: |
    A Chef's House
    Some Town
    ST1 2AB
  vatno:   xxx xxxx xx

# VAT bands are identified by single letters.  Each department has a
# single VAT band associated with it.  VAT details for each band can
# change over time; here we list the business (which can also change),
# the rate and the effective date of that rate.

# Historic VAT rate information is used when printing old receipts and
# when reporting through the web interface.

# The VatBand model sets defaults for each band which are used when
# looking up a date not covered vby any VatRate objects.

- model:      VatBand
  band:       A
  rate:       17.5
  businessid: 1
- model:      VatBand
  band:       B
  rate:       0.0
  businessid: 2

- {model: VatRate, band: A, businessid: 1, rate: 15.0, active: 2008-12-01}
- {model: VatRate, band: A, businessid: 1, rate: 17.5, active: 2010-01-01}
- {model: VatRate, band: A, businessid: 1, rate: 20.0, active: 2011-01-04}
- {model: VatRate, band: B, businessid: 2, rate: 20.0, active: 2013-08-01}

# At least one department must be defined otherwise the UI will not
# work!  Departments are referred to by integers.

# Note that if you change the vatband for a department, this will take
# effect retrospectively.  If you need to change the vat rate or
# business a department refers to on a particular date you should be
# careful to set up a new vat band that duplicates the old one up to
# the date at which you want to make the change.

- {model: Department, id: 1, vatband: A, description: Real Ale}
- {model: Department, id: 2, vatband: A, description: Keg}
- {model: Department, id: 3, vatband: A, description: Real Cider}
- {model: Department, id: 4, vatband: A, description: Spirits}
- {model: Department, id: 5, vatband: A, description: Snacks}
- {model: Department, id: 6, vatband: A, description: Bottles}
- {model: Department, id: 7, vatband: A, description: Soft Drinks}
- {model: Department, id: 8, vatband: A, description: Misc}
- {model: Department, id: 9, vatband: A, description: Wine}
- {model: Department, id: 10, vatband: B, description: Food}
- {model: Department, id: 11, vatband: A, description: Hot Drinks}

- {model: UnitType, id: pt, name: pint}
- {model: UnitType, id: pkt, name: packet}
- {model: UnitType, id: cap, name: capsule}
- {model: UnitType, id: bottle, name: bottle}
- {model: UnitType, id: 50ml, name: 50ml}
- {model: UnitType, id: 25ml, name: 25ml}

# Common sizes of stock.

- {model: StockUnit, id: pin,      name: Pin,             unit_id: pt,  size: 36.0}
- {model: StockUnit, id: tub,      name: 5 gal tub,       unit_id: pt,  size: 40.0}
- {model: StockUnit, id: keg30l,   name: 30l keg,         unit_id: pt,  size: 52.8}
- {model: StockUnit, id: firkin,   name: Firkin,          unit_id: pt,  size: 72.0}
- {model: StockUnit, id: plfirkin, name: Plastic Firkin,  unit_id: pt,  size: 75.0}
- {model: StockUnit, id: ten,      name: Ten gal cask,    unit_id: pt,  size: 80.0}
- {model: StockUnit, id: eleven,   name: Eleven gal cask, unit_id: pt,  size: 88.0}
- {model: StockUnit, id: kil,      name: Kilderkin,       unit_id: pt,  size: 144.0}
- {model: StockUnit, id: barrel,   name: Barrel,          unit_id: pt,  size: 288.0}

- {model: StockUnit, id: card12,  name: 12 pack card/box,  unit_id: pkt, size: 12.0}
- {model: StockUnit, id: card18,  name: 18 pack card/box,  unit_id: pkt, size: 18.0}
- {model: StockUnit, id: card20,  name: 20 pack card/box,  unit_id: pkt, size: 20.0}
- {model: StockUnit, id: card24,  name: 24 pack card/box,  unit_id: pkt, size: 24.0}
- {model: StockUnit, id: card25,  name: 25 pack card/box,  unit_id: pkt, size: 25.0}
- {model: StockUnit, id: card30,  name: 30 pack card/box,  unit_id: pkt, size: 30.0}
- {model: StockUnit, id: card32,  name: 32 pack card/box,  unit_id: pkt, size: 32.0}
- {model: StockUnit, id: card36,  name: 36 pack card/box,  unit_id: pkt, size: 36.0}
- {model: StockUnit, id: card40,  name: 40 pack card/box,  unit_id: pkt, size: 40.0}
- {model: StockUnit, id: card44,  name: 44 pack card/box,  unit_id: pkt, size: 44.0}
- {model: StockUnit, id: card48,  name: 48 pack card/box,  unit_id: pkt, size: 48.0}
- {model: StockUnit, id: card50,  name: 50 pack card/box,  unit_id: pkt, size: 50.0}
- {model: StockUnit, id: card100, name: 100 pack card/box, unit_id: pkt, size: 100.0}

- {model: StockUnit, id: cap50, name: 50 capsule box, unit_id: cap, size: 50.0}

- {model: StockUnit, id: crate6,  name: 6 bottle crate,  unit_id: bottle, size: 6.0}
- {model: StockUnit, id: crate8,  name: 8 bottle crate,  unit_id: bottle, size: 8.0}
- {model: StockUnit, id: crate12, name: 12 bottle crate, unit_id: bottle, size: 12.0}
- {model: StockUnit, id: crate16, name: 16 bottle crate, unit_id: bottle, size: 16.0}
- {model: StockUnit, id: crate20, name: 20 bottle crate, unit_id: bottle, size: 20.0}
- {model: StockUnit, id: crate24, name: 24 bottle crate, unit_id: bottle, size: 24.0}
- {model: StockUnit, id: crate48, name: 48 bottle crate, unit_id: bottle, size: 48.0}

- {model: StockUnit, id: 70cldm, name: "70cl bottle, 50ml measures", unit_id: 50ml, size: 14.0}
- {model: StockUnit, id: 75cldm, name: "75cl bottle, 50ml measures", unit_id: 50ml, size: 15.0}
- {model: StockUnit, id: 1ldm,   name: "1l bottle, 50ml measures",   unit_id: 50ml, size: 20.0}
- {model: StockUnit, id: 1.5ldm, name: "1.5l bottle, 50ml measures", unit_id: 50ml, size: 30.0}

- {model: StockUnit, id: 35clsm, name: "35cl bottle, 25ml measures", unit_id: 25ml, size: 14.0}
- {model: StockUnit, id: 50clsm, name: "50cl bottle, 25ml measures", unit_id: 25ml, size: 20.0}
- {model: StockUnit, id: 70clsm, name: "70cl bottle, 25ml measures", unit_id: 25ml, size: 28.0}
- {model: StockUnit, id: 75clsm, name: "75cl bottle, 25ml measures", unit_id: 25ml, size: 30.0}
- {model: StockUnit, id: 1lsm,   name: "1l bottle, 25ml measures",   unit_id: 25ml, size: 40.0}
- {model: StockUnit, id: 1.5lsm, name: "1.5l bottle, 25ml measures", unit_id: 25ml, size: 60.0}


# These are referred to in the register code, so should not be changed.
- {model: TransCode, code: S, description: Sale}
- {model: TransCode, code: V, description: Void}

# The 'sold' and 'pullthru' and 'freebie' stock removal codes are
# referred to in the register code, so should not be changed.  All the
# other removal reasons are optional.
- {model: RemoveCode, id: sold,     reason: Sold}
- {model: RemoveCode, id: pullthru, reason: "Pulled through"}
- {model: RemoveCode, id: freebie,  reason: "Free drink"}
- {model: RemoveCode, id: ood,      reason: "Out of date"}
- {model: RemoveCode, id: taste,    reason: "Bad taste"}
- {model: RemoveCode, id: taster,   reason: "Free taster"}
- {model: RemoveCode, id: cellar,   reason: "Cellar work"}
- {model: RemoveCode, id: damaged,  reason: Damaged}
- {model: RemoveCode, id: missing,  reason: "Gone missing"}
- {model: RemoveCode, id: driptray, reason: "Drip tray"}

# The 'empty' finishcode is used in the code, so must exist.  All
# other codes are optional.
- {model: FinishCode, id: empty,  description: "All gone"}
- {model: FinishCode, id: credit, description: "Returned for credit"}
- {model: FinishCode, id: turned, description: "Turned sour / off taste"}
- {model: FinishCode, id: ood,    description: "Out of date"}

# The 'location', 'start' and 'stop' annotation types are referred to
# in the code, so must exist.  Other types are optional.
- {model: AnnotationType, id: location, description: "Location"}
- {model: AnnotationType, id: start,    description: "Put on sale"}
- {model: AnnotationType, id: stop,     description: "Removed from sale"}
- {model: AnnotationType, id: vent,     description: "Vented"}
- {model: AnnotationType, id: memo,     description: "Memo"}

"""

import yaml
from . import models
from . import td

def setup(f):
    t=yaml.load(f)

    for m in t:
        if 'model' not in m:
            print("Missing model from %s"%m)
            continue
        model=models.__dict__[m['model']]
        del m['model']
        td.s.merge(model(**m))
        td.s.flush()
