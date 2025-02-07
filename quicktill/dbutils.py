"""Various command-line utilities for dealing with the database
"""

import os
from . import cmdline
from . import td
from . import models
from . import tillconfig
from .models import Session, PayType, Business, zero
from sqlalchemy import Date, or_
from sqlalchemy.sql.expression import func, cast
from sqlalchemy.orm import joinedload
import random


class dbshell(cmdline.command):
    """
    Provide an interactive python prompt with the 'td' module and
    'models.*' already imported, and a database session started.

    """
    help = "interactive python prompt with database initialised"

    @staticmethod
    def run(args):
        import code
        import readline  # noqa: F401
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
        with td.orm_session():
            sessions = td.s.query(models.Session).count()
        if sessions > 2 and not args.really:
            print(
                "You have more than two sessions in the database!  Try again "
                "as 'flushdb --really' if you definitely want to remove all "
                "the data and tables from the database.")
            return 1
        if sessions > 0:
            print(
                f"There is some data ({sessions} sessions) in the database.  "
                "Are you sure you want to remove all the data and tables?")
            ok = input("Sure? (y/n) ")
            if ok != 'y':
                return 1
        td.remove_tables()
        print("Finished.")


class anonymise(cmdline.command):
    """Remove Personally Identifiable Information from the database.  This
    is intended to be used prior to releasing till databases publicly
    to use as sample data.  All user names are set to random values,
    transaction notes are blanked, and the refusals list is truncated.
    """
    command = "anonymise-users"
    help = "remove personally identifiable information from the database"

    # Lists of names from Tom Lynch:
    # https://gist.github.com/unknowndomain/455cbc44e37080fd49bdc370982544fa
    firstnames = [
        "Amelia", "Oliver", "Olivia", "Jack", "Emily",
        "Harry", "Isla", "George", "Ava", "Jacob",
        "Ella", "Charlie", "Jessica", "Noah", "Isabella",
        "William", "Mia", "Thomas", "Poppy", "Oscar",
        "Sophie", "James", "Sophia", "Muhammad", "Lily",
        "Henry", "Grace", "Alfie", "Evie", "Leo",
        "Scarlett", "Joshua", "Ruby", "Freddie", "Chloe",
        "Ethan", "Isabelle", "Archie", "Daisy", "Isaac",
        "Freya", "Joseph", "Phoebe", "Alexander", "Florence",
        "Samuel", "Alice", "Daniel", "Charlotte", "Logan",
        "Sienna", "Edward", "Matilda", "Lucas", "Evelyn",
        "Max", "Eva", "Mohammed", "Millie", "Benjamin",
        "Sofia", "Mason", "Lucy", "Harrison", "Elsie",
        "Theo", "Imogen", "Jake", "Layla", "Sebastian",
        "Rosie", "Finley", "Maya", "Arthur", "Esme",
        "Adam", "Elizabeth", "Dylan", "Lola", "Riley",
        "Willow", "Zachary", "Ivy", "Teddy", "Erin",
        "David", "Holly", "Toby", "Emilia", "Theodore",
        "Molly", "Elijah", "Ellie", "Matthew", "Jasmine",
        "Jenson", "Eliza", "Jayden", "Lilly", "Harvey",
        "Abigail", "Reuben", "Georgia", "Harley", "Maisie",
        "Luca", "Eleanor", "Michael", "Hannah", "Hugo",
        "Harriet", "Lewis", "Amber", "Frankie", "Bella",
        "Luke", "Thea", "Stanley", "Annabelle", "Tommy",
        "Emma", "Jude", "Amelie", "Blake", "Harper",
        "Louie", "Gracie", "Nathan", "Rose", "Gabriel",
        "Summer", "Charles", "Martha", "Bobby", "Violet",
        "Mohammad", "Penelope", "Ryan", "Anna", "Tyler",
        "Nancy", "Elliott", "Zara", "Albert", "Maria",
        "Elliot", "Darcie", "Rory", "Maryam", "Alex",
        "Megan", "Frederick", "Darcey", "Ollie", "Lottie",
        "Louis", "Mila", "Dexter", "Heidi", "Jaxon",
        "Lexi", "Liam", "Lacey", "Jackson", "Francesca",
        "Callum", "Robyn", "Ronnie", "Bethany", "Leon",
        "Julia", "Kai", "Sara", "Aaron", "Aisha",
        "Roman", "Darcy", "Austin", "Zoe", "Ellis",
        "Clara", "Jamie", "Victoria", "Reggie", "Beatrice",
        "Seth", "Hollie", "Carter", "Arabella", "Felix",
        "Sarah", "Ibrahim", "Maddison", "Sonny", "Leah",
        "Kian", "Katie", "Caleb", "Aria", "Connor",
    ]
    surnames = [
        "Smith", "Brown", "Wilson", "Campbell", "Stewart",
        "Thomson", "Robertson", "Anderson", "Macdonald", "Taylor",
        "Scott", "Reid", "Murray", "Clark", "Watson",
        "Ross", "Young", "Mitchell", "Walker", "Morrison",
        "Paterson", "Graham", "Hamilton", "Fraser", "Martin",
        "Gray", "Henderson", "Kerr", "Mcdonald", "Ferguson",
        "Miller", "Cameron", "Davidson", "Johnston", "Bell",
        "Kelly", "Duncan", "Hunter", "Simpson", "Macleod",
        "Mackenzie", "Allan", "Grant", "Wallace", "Black",
        "Russell", "Jones", "Mackay", "Marshall", "Sutherland",
        "Wright", "Gibson", "Burns", "Kennedy", "Mclean",
        "Hughes", "Gordon", "White", "Murphy", "Wood",
        "Craig", "Stevenson", "Johnstone", "Cunningham", "Williamson",
        "Milne", "Sinclair", "Mcmillan", "Muir", "Mckenzie",
        "Ritchie", "Watt", "Docherty", "Crawford", "Mckay",
        "Millar", "Mcintosh", "Moore", "Douglas", "Fleming",
        "Thompson", "King", "Munro", "Williams", "Maclean",
        "Christie", "Dickson", "Jackson", "Shaw", "Jamieson",
        "Lindsay", "Hill", "Mcgregor", "Boyle", "Bruce",
        "Green", "Mclaughlin", "Ward", "Richardson", "Currie",
        "Quinn", "Reilly", "Alexander", "Cooper", "Davies",
    ]

    @staticmethod
    def run(args):
        with td.orm_session():
            sessions = td.s.query(models.Session).count()
        if sessions > 0:
            print(f"There is some data ({sessions} sessions) in the database.  "
                  "Are you sure you want to remove all the PII?  "
                  "This operation cannot be undone.")
            ok = input("Sure? (y/n) ")
            if ok != 'y':
                return 1
        with td.orm_session():
            users = td.s.query(models.User).all()
            for u in users:
                firstname = random.choice(anonymise.firstnames)
                lastname = random.choice(anonymise.surnames)
                u.fullname = f"{firstname} {lastname}"
                u.shortname = firstname
                u.webuser = None
                u.message = None
            transactions = td.s.query(models.Transaction).all()
            for t in transactions:
                t.notes = ""
            td.s.query(models.RefusalsLog).delete()
            # Log entries that reference a User may contain their real
            # name; log entries about setting transaction notes may
            # also contain real names. Delete them.
            td.s.query(models.LogEntry)\
                .filter(or_(
                    models.LogEntry.user != None,
                    models.LogEntry.description.like('Set the note on %')
                ))\
                .delete(synchronize_session=False)

            # Delete all payment metadata — contains (obscured) card details
            td.s.query(models.PaymentMeta).delete()

            # Delete all stocktype metadata — may contain copyright images
            td.s.query(models.StockTypeMeta).delete()
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
    database_required = False

    @staticmethod
    def add_arguments(parser):
        parser.add_argument(
            "--tempdb", type=str, dest="tempdb",
            help="name of temporary database",
            default="quicktill-test")
        parser.add_argument(
            "--nocreate", action="store_false", dest="createdb",
            help="assume temporary database exists",
            default=True)
        parser.add_argument(
            "--keep-tempfiles", action="store_true",
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
        if not tillconfig.database:
            print("No database specified")
            return 1
        url = sqlalchemy.engine.url.make_url(
            td.parse_database_name(tillconfig.database))
        try:
            current_schema = subprocess.check_output(
                ["pg_dump", "-s", "-O"] + checkdb.connection_options(url))
        except OSError as e:
            print("Couldn't run pg_dump on current database; "
                  "is pg_dump installed?")
            print(e)
            return 1
        if args.createdb:
            engine = sqlalchemy.create_engine("postgresql+psycopg2:///postgres")
            raw_connection = engine.raw_connection()
            with raw_connection.cursor() as cursor:
                cursor.execute('commit')
                cursor.execute(f'create database "{args.tempdb}"')
            raw_connection.close()
        try:
            engine = sqlalchemy.create_engine(
                f"postgresql+psycopg2:///{args.tempdb}")
            try:
                models.metadata.create_all(engine)
                pristine_schema = subprocess.check_output(
                    ["pg_dump", "-s", "-O", args.tempdb])
                models.metadata.drop_all(engine)
            finally:
                # If we don't explicitly close the connection to the
                # database here, we won't be able to drop it
                engine.dispose()
        finally:
            if args.createdb:
                engine = sqlalchemy.create_engine(
                    "postgresql+psycopg2:///postgres")
                raw_connection = engine.raw_connection()
                with raw_connection.cursor() as cursor:
                    cursor.execute('commit')
                    cursor.execute(f'drop database "{args.tempdb}"')
                raw_connection.close()
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
                print(f"Current database schema is in {current.name}")
                print(f"Pristine database schema is in {pristine.name}")
            else:
                os.unlink(current.name)
                os.unlink(pristine.name)


class totals(cmdline.command):
    """Display a table of session totals.

    """
    help = "display table of session totals"

    @staticmethod
    def add_arguments(parser):
        parser.add_argument("-d", "--days", type=int, dest="days",
                            help="number of days to display", default=40)

    @staticmethod
    def run(args):
        with td.orm_session():
            sessions = \
                td.s.query(Session)\
                    .filter(Session.endtime != None)\
                    .filter(cast(func.now(), Date) - Session.date <= args.days)\
                    .options(joinedload(Session.actual_totals))\
                    .order_by(Session.id)\
                    .all()
            businesses = td.s.query(Business).order_by(Business.id).all()
            paytypes = td.s.query(PayType)\
                           .order_by(PayType.order, PayType.paytype)\
                           .filter(PayType.paytype.in_({
                               st.paytype.paytype
                               for s in sessions
                               for st in s.actual_totals}))\
                           .all()
            f = "{s.id:>5} | {s.date} | "
            h = "  ID  |    Date    | "
            ptl = max([len(pt.description) for pt in paytypes] + [8])
            for x in paytypes:
                f = f + "{p[%s]:>%d} | " % (x.paytype, ptl)
                h = h + ("{x.description:^%s} | " % ptl).format(x=x)
            f = f + "{error:>7} | "
            h = h + " Error  | "
            for b in businesses:
                if b.show_vat_breakdown:
                    f = f + "{b[%s][1]:>10} | {b[%s][2]:>8} | " % (b.id, b.id)
                    h = h + "{:^10} | {:^8} | ".format(
                        b.abbrev + " ex-VAT", b.abbrev + " VAT")
                else:
                    f = f + "{b[%s][0]:>8} | " % b.id
                    h = h + "{:^8} | ".format(b.abbrev)
            f = f[:-2]
            h = h[:-2]
            print(h)
            for s in sessions:
                # Sessions with no total recorded will report actual_total
                # of None
                if s.actual_total is None:
                    continue
                vbt = s.vatband_totals
                p = {}
                for x in paytypes:
                    p[x.paytype] = ""
                for t in s.actual_totals:
                    p[t.paytype_id] = t.amount
                b = {}
                for x in businesses:
                    b[x.id] = (zero, zero, zero)
                for x in vbt:
                    o = b[x[0].businessid]
                    o = (o[0] + x[1], o[1] + x[2], o[2] + x[3])
                    b[x[0].businessid] = o
                print(f.format(s=s, p=p, error=s.actual_total - s.total, b=b))
