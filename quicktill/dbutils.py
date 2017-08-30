"""Various command-line utilities for dealing with the database
"""

import os
from . import cmdline
from . import td
from . import models
from . import tillconfig

class dbshell(cmdline.command):
    """
    Provide an interactive python prompt with the 'td' module and
    'models.*' already imported, and a database session started.

    """
    help = "interactive python prompt with database initialised"

    @staticmethod
    def run(args):
        import code
        import readline
        td.init(tillconfig.database)
        console = code.InteractiveConsole()
        console.push("import quicktill.td as td")
        console.push("from quicktill.models import *")
        with td.orm_session():
            console.interact()

class syncdb(cmdline.command):
    """
    Create database tables and indexes that have not already been
    created.  This command should always be safe to run; it won't
    alter existing tables and indexes and won't remove any data.

    If this version of the till software requires schema changes that
    are incompatible with previous versions this will be mentioned in
    the release notes, and you should be able to find a migration
    script under "examples".

    """
    help = "create new database tables"

    @staticmethod
    def run(args):
        td.init(tillconfig.database)
        td.create_tables()

class flushdb(cmdline.command):
    """
    Remove database tables.  This command will refuse to run without
    the "--really" option if your database contains more than two
    sessions of data, because it will delete it all!  It's intended
    for use during testing and setup.

    """
    help = "remove database tables"

    @staticmethod
    def add_arguments(parser):
        parser.add_argument("--really", action="store_true", dest="really",
                            help="confirm removal of data")

    @staticmethod
    def run(args):
        td.init(tillconfig.database)
        with td.orm_session():
            sessions = td.s.query(models.Session).count()
        if sessions > 2 and not args.really:
            print("You have more than two sessions in the database!  Try again "
                  "as 'flushdb --really' if you definitely want to remove all "
                  "the data and tables from the database.")
            return 1
        if sessions > 0:
            print("There is some data (%d sessions) in the database.  "
                  "Are you sure you want to remove all the data and tables?"%(
                    sessions,))
            ok = input("Sure? (y/n) ")
            if ok != 'y':
                return 1
        td.remove_tables()
        print("Finished.")

class checkdb(cmdline.command):
    """
    Check that the database schema matches the schema defined in the
    current version of the till software.  Output a series of SQL
    commands that will update the schema to match the current one.

    Do not pipe the output of this command directly to psql!  Always
    read and check it first.

    This command makes use of the external utilities pg_dump and
    apgdiff, and will fail if they are not installed.  It needs to
    create a temporary database and will fail if the current user does
    not have permission to do so.

    """
    help = "check database schema"

    @staticmethod
    def add_arguments(parser):
        parser.add_argument("--tempdb", type=str, dest="tempdb",
                            help="name of temporary database",
                            default="quicktill-test")
        parser.add_argument("--nocreate", action="store_false", dest="createdb",
                            help="assume temporary database exists",
                            default=True)
        parser.add_argument("--keep-tempfiles", action="store_true",
                            dest="keeptmp",
                            help="don't delete the temporary schema dump files",
                            default=False)

    @staticmethod
    def connection_options(u):
        opts = []
        if u.database:
            opts = opts + ["-d", u.database]
        if u.host:
            opts = opts + ["-h", u.host]
        if u.port:
            opts = opts + ["-p", str(u.port)]
        if u.username:
            opts = opts + ["U", u.username]
        return opts

    @staticmethod
    def run(args):
        import sqlalchemy.engine.url
        import sqlalchemy
        import tempfile
        import subprocess
        url = sqlalchemy.engine.url.make_url(
            td.parse_database_name(tillconfig.database))
        try:
            current_schema = subprocess.check_output(
                ["pg_dump","-s"] + checkdb.connection_options(url))
        except OSError as e:
            print("Couldn't run pg_dump on current database; "
                  "is pg_dump installed?")
            print(e)
            return 1
        if args.createdb:
            engine = sqlalchemy.create_engine("postgresql+psycopg2:///postgres")
            conn = engine.connect()
            conn.execute('commit')
            conn.execute('create database "{}"'.format(args.tempdb))
            conn.close()
        try:
            engine = sqlalchemy.create_engine(
                "postgresql+psycopg2:///{}".format(args.tempdb))
            models.metadata.bind = engine
            models.metadata.create_all()
            try:
                pristine_schema = subprocess.check_output(
                    ["pg_dump", "-s", args.tempdb])
            finally:
                models.metadata.drop_all()
                # If we don't explicitly close the connection to the
                # database here, we won't be able to drop it
                engine.dispose()
        finally:
            if args.createdb:
                engine = sqlalchemy.create_engine("postgresql+psycopg2:///postgres")
                conn = engine.connect()
                conn.execute('commit')
                conn.execute('drop database "{}"'.format(args.tempdb))
                conn.close()
        current = tempfile.NamedTemporaryFile(delete=False)
        current.write(current_schema)
        current.close()
        pristine = tempfile.NamedTemporaryFile(delete=False)
        pristine.write(pristine_schema)
        pristine.close()
        try:
            subprocess.check_call(["apgdiff", "--add-transaction",
                                   "--ignore-start-with",
                                   current.name, pristine.name])
        except OSError as e:
            print("Couldn't run apgdiff; is it installed?")
            print(e)
        finally:
            if args.keeptmp:
                print("Current database schema is in {}".format(current.name))
                print("Pristine database schema is in {}".format(pristine.name))
            else:
                os.unlink(current.name)
                os.unlink(pristine.name)
