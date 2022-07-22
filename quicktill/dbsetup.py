"""
Help with populating the database with basic configuration information
like the name of the business, the various departments, and VAT rates.

"""

import yaml
import argparse
from . import models
from . import td
from . import cmdline


def setup(f):
    t = yaml.safe_load(f)

    for m in t:
        if 'model' not in m:
            print(f"Missing model from {m}")
            continue
        model = models.__dict__[m['model']]
        del m['model']
        td.s.merge(model(**m))
        td.s.flush()


class dbsetup(cmdline.command):
    """Add initial records to the database
    """
    help = "add initial records to the database"

    @staticmethod
    def add_arguments(parser):
        parser.add_argument("dbfile", help="Initial records file "
                            "in YAML", type=argparse.FileType('r'))

    @staticmethod
    def run(args):
        with td.orm_session():
            setup(args.dbfile)
