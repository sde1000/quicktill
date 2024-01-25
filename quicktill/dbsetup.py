"""
Help with populating the database with basic configuration information
like the name of the business, the various departments, and VAT rates.

"""

import tomli
import argparse
from . import models
from . import td
from . import cmdline


def setup(f):
    t = tomli.load(f)

    # Keys in the file are database model class names, values are
    # lists of dicts giving initial data for rows of these

    for modelname, rows in t.items():
        model = models.__dict__.get(modelname)
        if not model:
            raise Exception(f"Unknown model {modelname}")
        for row in rows:
            td.s.merge(model(**row))
            td.s.flush()


class dbsetup(cmdline.command):
    """Add initial records to the database
    """
    help = "add initial records to the database"

    @staticmethod
    def add_arguments(parser):
        parser.add_argument("dbfile", help="Initial records file "
                            "in TOML", type=argparse.FileType('rb'))

    @staticmethod
    def run(args):
        with td.orm_session():
            try:
                setup(args.dbfile)
            except Exception:
                td.s.rollback()
                raise
