"""
Help with populating the database with basic configuration information
like the name of the business, the various departments, and VAT rates.

"""

template = r"""
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

- {model: Unit, description: 'Pint (draught)', name: pint, item_name: pint, item_name_plural: pints}
- {model: Unit, description: 'Packet', name: packet, item_name: packet, item_name_plural: packets}
- {model: Unit, description: 'Capsule', name: capsule, item_name: capsule, item_name_plural: capsules}
- {model: Unit, description: 'Bottle (whole)', name: bottle, item_name: bottle, item_name_plural: bottles}
- {model: Unit, description: '50ml spirits', name: 50ml, item_name: 50ml measure, item_name_plural: 50ml measures}
- {model: Unit, description: '25ml spirits', name: 25ml, item_name: 25ml measure, item_name_plural: 25ml measures}
- {model: Unit, description: 'Bottle (wine)', name: ml, item_name: bottle, item_name_plural: bottles, units_per_item: 750}
- {model: Unit, description: 'Pint (soft drink carton)', name: ml, item_name: pint, item_name_plural: pints, units_per_item: 568}

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
import argparse
from . import models
from . import td
from . import cmdline
from . import tillconfig

def setup(f):
    t = yaml.load(f)

    for m in t:
        if 'model' not in m:
            print("Missing model from %s"%m)
            continue
        model = models.__dict__[m['model']]
        del m['model']
        td.s.merge(model(**m))
        td.s.flush()

class dbsetup(cmdline.command):
    """Add initial records to the database.

    With no arguments, print a template database setup file.
    With one argument, import and process a database setup file.

    """
    help = "add initial records to the database"
    database_required = False

    @staticmethod
    def add_arguments(parser):
        parser.add_argument("dbfile", help="Initial records file "
                            "in YAML", type=argparse.FileType('r'),
                            nargs="?")

    @staticmethod
    def run(args):
        if not args.dbfile:
            print(template)
        else:
            if not tillconfig.database:
                print("No database specified; use --database or "
                      "specify in config file")
                return 1
            td.init(tillconfig.database)
            with td.orm_session():
                setup(args.dbfile)
