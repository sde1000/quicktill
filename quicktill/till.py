"""
Entry point for the till application.  In normal use the application
will be started by the "runtill" script calling main() from this
module.

"""

import urllib.request, urllib.parse, urllib.error
import sys, os, logging, logging.config, locale, argparse, yaml
import termios,fcntl,array
import socket
import time
from . import ui,event,td,printer,tillconfig,foodorder,user,pdrivers,cmdline,extras
from .version import version
from .models import Session,User,UserToken,Business,zero
from . import models

log=logging.getLogger(__name__)

configurlfile="/etc/quicktill/configurl"

class intropage(ui.basicpage):
    def __init__(self):
        ui.basicpage.__init__(self)
        self.addstr(1, 1, "This is quicktill version {}".format(version))
        if tillconfig.hotkeys:
            self.addstr(3, 1, "To continue, press one of these keys:")
            y = 5
            for k in tillconfig.hotkeys:
               self.addstr(y, 3, str(k))
               y = y + 1
        self.move(0, 0)

class ValidateExitOption(argparse.Action):
    def __call__(self, parser, args, values, option_string=None):
        code, text = values
        try:
            code = int(code)
        except ValueError:
            raise argparse.ArgumentError(
                self, "first argument to {} must be an integer".format(
                    self.dest))
        current = getattr(args, self.dest, None)
        if not current:
            current = []
        current.append((code, text))
        setattr(args, self.dest, current)

class runtill(cmdline.command):
    """
    Run the till interactively.

    """
    @staticmethod
    def add_arguments(subparsers):
        parser=subparsers.add_parser(
            'start',help="run the till interactively",
            description=runtill.__doc__)
        parser.add_argument("-n", "--nolisten", action="store_true",
                            dest="nolisten",
                            help="Disable listening socket for user tokens")
        parser.add_argument(
            "-e", "--exit-option", nargs=2,
            dest="exitoptions",
            action=ValidateExitOption,
            metavar=("EXITCODE","TEXT"),
            help="Add an option to the exit menu")
        parser.add_argument(
            "-i", "--exit-when-idle",
            dest="exit_when_idle", default=None,
            action="store", type=int, metavar="EXITCODE",
            help="Exit with EXITCODE when the till is idle")
        parser.add_argument(
            "-r", "--minimum-runtime",
            dest="minimum_run_time", default=86400,
            action="store", type=int, metavar="RUNTIME",
            help="Run for at least RUNTIME seconds before considering "
            "the till to be idle")
        parser.add_argument(
            "-s", "--minimum-lockscreen-time",
            dest="minimum_lock_screen_time", default=300,
            action="store", type=int, metavar="LOCKTIME",
            help="Display the lock screen for at least LOCKTIME seconds "
            "before considering the till to be idle")
        parser.set_defaults(command=runtill.run,nolisten=False)
    @staticmethod
    def run(args):
        log.info("Starting version %s"%version)
        try:
            if tillconfig.usertoken_listen and not args.nolisten:
                user.tokenlistener(tillconfig.usertoken_listen)
            if tillconfig.usertoken_listen_v6 and not args.nolisten:
                user.tokenlistener(tillconfig.usertoken_listen_v6,
                                   addressfamily=socket.AF_INET6)
            if args.exitoptions:
                tillconfig.exitoptions = args.exitoptions
            tillconfig.idle_exit_code = args.exit_when_idle
            tillconfig.minimum_run_time = args.minimum_run_time
            tillconfig.minimum_lock_screen_time = args.minimum_lock_screen_time
            tillconfig.start_time = time.time()
            td.init(tillconfig.database)
            ui.run()
        except:
            log.exception("Exception caught at top level")

        log.info("Shutting down")
        logging.shutdown()
        return event.shutdowncode

class dbshell(cmdline.command):
    """
    Provide an interactive python prompt with the 'td' module and
    'models.*' already imported, and a database session started.

    """
    @staticmethod
    def add_arguments(subparsers):
        parser=subparsers.add_parser(
            'dbshell',description=dbshell.__doc__,
            help="interactive python prompt with database initialised")
        parser.set_defaults(command=dbshell.run)
    @staticmethod
    def run(args):
        import code
        import readline
        td.init(tillconfig.database)
        console=code.InteractiveConsole()
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
    @staticmethod
    def add_arguments(subparsers):
        parser=subparsers.add_parser(
            'syncdb',help="create new database tables",
            description=syncdb.__doc__)
        parser.set_defaults(command=syncdb.run)
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
    @staticmethod
    def add_arguments(subparsers):
        parser=subparsers.add_parser(
            'flushdb',help="remove database tables",description=flushdb.__doc__)
        parser.set_defaults(command=flushdb.run)
        parser.add_argument("--really", action="store_true", dest="really",
                            help="confirm removal of data")
    @staticmethod
    def run(args):
        td.init(tillconfig.database)
        with td.orm_session():
            sessions=td.s.query(Session).count()
        if sessions>2 and not args.really:
            print("You have more than two sessions in the database!  Try again "
                  "as 'flushdb --really' if you definitely want to remove all "
                  "the data and tables from the database.")
            return 1
        if sessions>0:
            print("There is some data (%d sessions) in the database.  "
                  "Are you sure you want to remove all the data and tables?"%(
                    sessions,))
            ok=input("Sure? (y/n) ")
            if ok!='y': return 1
        td.remove_tables()
        print("Finished.")

class dbsetup(cmdline.command):
    """
    With no arguments, print a template database setup file.
    With one argument, import and process a database setup file.

    """
    @staticmethod
    def add_arguments(subparsers):
        parser=subparsers.add_parser(
            'dbsetup',help="add initial records to the database",
            description=dbsetup.__doc__)
        parser.set_defaults(command=dbsetup.run)
        parser.add_argument("dbfile", help="Initial records file "
                            "in YAML", type=argparse.FileType('r'),
                            nargs="?")
    @staticmethod
    def run(args):
        from .dbsetup import template,setup
        if not args.dbfile:
            print(template)
        else:
            td.init(tillconfig.database)
            with td.orm_session():
                setup(args.dbfile)

class checkdb(cmdline.command):
    """Check that the database schema matches the schema defined in the
    current version of the till software.  Output a series of SQL
    commands that will update the schema to match the current one.

    Do not pipe the output of this command directly to psql!  Always
    read and check it first.

    This command makes use of the external utilities pg_dump and
    apgdiff, and will fail if they are not installed.  It needs to
    create a temporary database and will fail if the current user does
    not have permission to do so.

    """
    @staticmethod
    def add_arguments(subparsers):
        parser=subparsers.add_parser(
            'checkdb',help="check database schema",
            description=checkdb.__doc__)
        parser.set_defaults(command=checkdb.run)
        parser.add_argument("--tempdb",type=str,dest="tempdb",
                            help="name of temporary database",
                            default="quicktill-test")
        parser.add_argument("--nocreate",action="store_false",dest="createdb",
                            help="assume temporary database exists",
                            default=True)
        parser.add_argument("--keep-tempfiles",action="store_true",dest="keeptmp",
                            help="don't delete the temporary schema dump files",
                            default=False)
    @staticmethod
    def connection_options(u):
        opts=[]
        if u.database:
            opts=opts+["-d",u.database]
        if u.host:
            opts=opts+["-h",u.host]
        if u.port:
            opts=opts+["-p",str(u.port)]
        if u.username:
            opts=opts+["U",u.username]
        return opts
    @staticmethod
    def run(args):
        import sqlalchemy.engine.url
        import sqlalchemy
        import tempfile
        import subprocess
        url=sqlalchemy.engine.url.make_url(
            td.parse_database_name(tillconfig.database))
        try:
            current_schema=subprocess.check_output(
                ["pg_dump","-s"]+checkdb.connection_options(url))
        except OSError as e:
            print("Couldn't run pg_dump on current database; "
                  "is pg_dump installed?")
            print(e)
            return 1
        if args.createdb:
            engine=sqlalchemy.create_engine("postgresql+psycopg2:///postgres")
            conn=engine.connect()
            conn.execute('commit')
            conn.execute('create database "{}"'.format(args.tempdb))
            conn.close()
        try:
            engine=sqlalchemy.create_engine(
                "postgresql+psycopg2:///{}".format(args.tempdb))
            models.metadata.bind=engine
            models.metadata.create_all()
            try:
                pristine_schema=subprocess.check_output(
                    ["pg_dump","-s",args.tempdb])
            finally:
                models.metadata.drop_all()
                # If we don't explicitly close the connection to the
                # database here, we won't be able to drop it
                engine.dispose()
        finally:
            if args.createdb:
                engine=sqlalchemy.create_engine("postgresql+psycopg2:///postgres")
                conn=engine.connect()
                conn.execute('commit')
                conn.execute('drop database "{}"'.format(args.tempdb))
                conn.close()
        current=tempfile.NamedTemporaryFile(delete=False)
        current.write(current_schema)
        current.close()
        pristine=tempfile.NamedTemporaryFile(delete=False)
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

class totals(cmdline.command):
    """
    Display a table of session totals.

    """
    @staticmethod
    def add_arguments(subparsers):
        parser=subparsers.add_parser(
            'totals',help="display table of session totals",
            description=totals.__doc__)
        parser.set_defaults(command=totals.run)
        parser.add_argument("-d","--days",type=int,dest="days",
                            help="number of days to display",default=40)
    @staticmethod
    def run(args):
        td.init(tillconfig.database)
        with td.orm_session():
            sessions=td.s.query(Session).\
                filter(Session.endtime!=None).\
                order_by(Session.id)[-args.days:]
            businesses=td.s.query(Business).order_by(Business.id).all()
            f="{s.id:>5} | {s.date} | "
            h="  ID  |    Date    | "
            for x in tillconfig.all_payment_methods:
                f=f+"{p[%s]:>8} | "%x.paytype
                h=h+"{:^8} | ".format(x.description)
            f=f+"{error:>7} | "
            h=h+" Error  | "
            for b in businesses:
                if b.show_vat_breakdown:
                    f=f+"{b[%s][1]:>10} | {b[%s][2]:>8} | "%(b.id,b.id)
                    h=h+"{:^10} | {:^8} | ".format(
                        b.abbrev+" ex-VAT",b.abbrev+" VAT")
                else:
                    f=f+"{b[%s][0]:>8} | "%b.id
                    h=h+"{:^8} | ".format(b.abbrev)
            f=f[:-2]
            h=h[:-2]
            print(h)
            for s in sessions:
                # Sessions with no total recorded will report actual_total
                # of None
                if s.actual_total is None: continue
                vbt=s.vatband_totals
                p={}
                for x in tillconfig.all_payment_methods:
                    p[x.paytype]=""
                for t in s.actual_totals:
                    p[t.paytype_id]=t.amount
                b={}
                for x in businesses:
                    b[x.id]=(zero,zero,zero)
                for x in vbt:
                    o=b[x[0].businessid]
                    o=(o[0]+x[1],o[1]+x[2],o[2]+x[3])
                    b[x[0].businessid]=o
                print(f.format(s=s,p=p,error=s.actual_total-s.total,b=b))

def _linux_unblank_screen():
    TIOCL_UNBLANKSCREEN=4
    buf=array.array(str('b'),[TIOCL_UNBLANKSCREEN])
    fcntl.ioctl(sys.stdin,termios.TIOCLINUX,buf)

def _x_unblank_screen():
    os.system("xset s reset")

class ToastHandler(logging.Handler):
    def emit(self,record):
        ui.toast(self.format(record))

def main():
    """Usual main entry point for the till software, unless you are doing
    something strange.  Reads the location of its global configuration,
    command line options, and the global configuration, and then starts
    the program.

    """
    
    try:
        with open(configurlfile) as f:
            configurl = f.readline()
    except FileNotFoundError:
        configurl = None
    parser=argparse.ArgumentParser(
        description="Figure out where all the money and stock went")
    parser.add_argument("--version", action="version", version=version)
    parser.add_argument("-u", "--config-url", action="store",
                        dest="configurl", default=configurl,
                        help="URL of global till configuration file; overrides "
                        "contents of %s"%configurlfile)
    parser.add_argument("-c", "--config-name", action="store",
                        dest="configname", default="default",
                        help="Till type to use from configuration file")
    parser.add_argument("-d", "--database", action="store",
                        dest="database",
                        help="Database connection string; overrides "
                        "database specified in configuration file")
    parser.add_argument("-f", "--user", action="store",
                        dest="user",type=int,default=None,
                        help="User ID to use when no other user information "
                        "is available (use 'listusers' command to check IDs)")
    loggroup=parser.add_mutually_exclusive_group()
    loggroup.add_argument("-y", "--log-config", help="Logging configuration file "
                          "in YAML", type=argparse.FileType('r'),
                          dest="logconfig")
    loggroup.add_argument("-l", "--logfile", type=argparse.FileType('a'),
                          dest="logfile", help="Simple logging output file")
    parser.add_argument("--debug", action="store_true", dest="debug",
                        help="Include debug output in log")
    parser.add_argument("--log-sql", action="store_true", dest="logsql",
                        help="Include SQL queries in logfile")
    parser.add_argument("--disable-printer", action="store_true",
                        dest="disable_printer",help="Use the null printer "
                        "instead of the configured printer")
    subparsers=parser.add_subparsers(title="commands")
    for c in cmdline.command._commands:
        c.add_arguments(subparsers)
    parser.set_defaults(configurl=configurl,configname="default",
                        database=None,logfile=None,debug=False,
                        interactive=False,disable_printer=False)
    args=parser.parse_args()

    if not hasattr(args, 'command'):
        parser.error("No command supplied")
    if not args.configurl:
        parser.error("No configuration URL provided in "
                     "%s or on command line"%configurlfile)
    tillconfig.configversion=args.configurl
    f=urllib.request.urlopen(args.configurl)
    globalconfig=f.read()
    f.close()

    # Logging configuration.  If we have a log configuration file,
    # read it and apply it.  This is done before the main
    # configuration file is imported so that log output from the
    # import can be directed appropriately.
    rootlog = logging.getLogger()
    if args.logconfig:
        logconfig = yaml.load(args.logconfig)
        args.logconfig.close()
        logging.config.dictConfig(logconfig)
    else:
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)s %(name)s\n  %(message)s')
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        handler.setLevel(logging.ERROR)
        rootlog.addHandler(handler)
    if args.logfile:
        loglevel = logging.DEBUG if args.debug else logging.INFO
        loghandler = logging.StreamHandler(args.logfile)
        loghandler.setFormatter(formatter)
        loghandler.setLevel(logging.DEBUG if args.debug else logging.INFO)
        rootlog.addHandler(loghandler)
        rootlog.setLevel(loglevel)
    if args.debug:
        rootlog.setLevel(logging.DEBUG)
    if args.logsql:
        logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
    # Set up handler to direct warnings to toaster UI
    toasthandler = ToastHandler()
    toastformatter = logging.Formatter('%(levelname)s: %(message)s')
    toasthandler.setFormatter(toastformatter)
    toasthandler.setLevel(logging.WARNING)
    rootlog.addHandler(toasthandler)

    import imp
    g=imp.new_module("globalconfig")
    g.configname=args.configname
    exec(globalconfig,g.__dict__)

    config=g.configurations.get(args.configname)
    if config is None:
        print(("Configuration \"%s\" does not exist.  "
               "Available configurations:"%args.configname))
        for i in list(g.configurations.keys()):
            print("%s: %s"%(i,g.configurations[i]['description']))
        sys.exit(1)

    if args.user:
        tillconfig.default_user=args.user
    if 'printer' in config:
        printer.driver=config['printer']
    else:
        log.info("no printer configured: using nullprinter()")
        printer.driver=pdrivers.nullprinter()
    if args.disable_printer:
        printer.driver=pdrivers.nullprinter(name="disabled-printer")
    if 'labelprinters' in config:
        printer.labelprinters=config['labelprinters']
    tillconfig.database=config.get('database')
    if args.database is not None: tillconfig.database=args.database
    if 'kitchenprinter' in config:
        foodorder.kitchenprinter=config['kitchenprinter']
    foodorder.menuurl=config.get('menuurl')
    tillconfig.pubname=config['pubname']
    tillconfig.pubnumber=config['pubnumber']
    tillconfig.pubaddr=config['pubaddr']
    tillconfig.currency=config['currency']
    tillconfig.all_payment_methods=config['all_payment_methods']
    tillconfig.payment_methods=config['payment_methods']
    if 'kbdriver' in config:
        # Perhaps we should support multiple filters...
        ui.keyboard_filter_stack.insert(0, config['kbdriver'])
    if 'pricepolicy' in config:
        log.warning("Obsolete 'pricepolicy' key present in configuration")
    if 'format_currency' in config:
        tillconfig.fc=config['format_currency']
    if 'priceguess' in config:
        # Config files should subclass stocktype.PriceGuessHook
        # instead of specifying this
        log.warning("Obsolete 'priceguess' key present in configuration")
    if 'deptkeycheck' in config:
        log.warning("Obsolete 'deptkeycheck' key present in configuration")
    if 'checkdigit_print' in config:
        tillconfig.checkdigit_print=config['checkdigit_print']
    if 'checkdigit_on_usestock' in config:
        tillconfig.checkdigit_on_usestock=config['checkdigit_on_usestock']
    if 'usestock_hook' in config:
        # Config files should subclass usestock.UseStockRegularHook
        # instead of specifying this
        log.warning("Obsolete 'usestock_hook' key present in configuration")
    if 'hotkeys' in config:
        tillconfig.hotkeys=config['hotkeys']
    if 'firstpage' in config:
        tillconfig.firstpage=config['firstpage']
    else:
        tillconfig.firstpage=intropage
    if 'usertoken_handler' in config:
        tillconfig.usertoken_handler=config['usertoken_handler']
    if 'usertoken_listen' in config:
        tillconfig.usertoken_listen=config['usertoken_listen']
    if 'usertoken_listen_v6' in config:
        tillconfig.usertoken_listen_v6=config['usertoken_listen_v6']

    if os.uname()[0]=='Linux':
        if os.getenv('TERM')=='linux':
            tillconfig.unblank_screen=_linux_unblank_screen
        elif os.getenv('TERM')=='xterm':
            os.putenv('TERM','linux')

    if os.getenv('DISPLAY'):
        tillconfig.unblank_screen=_x_unblank_screen

    locale.setlocale(locale.LC_ALL,'')

    sys.exit(args.command(args))
