"""
Entry point for the till application.  In normal use the application
will be started by the "runtill" script calling main() from this
module.

"""

from __future__ import print_function,unicode_literals
import sys,os,curses,logging,logging.config,locale,argparse,urllib,yaml
import termios,fcntl,array
from . import ui,event,td,printer,tillconfig,foodorder,user,pdrivers
from .version import version
from .models import Session,User,UserToken,Business,zero
log=logging.getLogger(__name__)

configurlfile="/etc/quicktill/configurl"

class intropage(ui.basicpage):
    def __init__(self):
        ui.basicpage.__init__(self)
        self.win.addstr(1,1,"This is quicktill version %s"%version)
        if tillconfig.hotkeys:
            self.win.addstr(3,1,"To continue, press one of these keys:")
            y=5
            for k in tillconfig.hotkeys:
               self.win.addstr(y,3,k.keycap)
               y=y+1
        self.win.move(0,0)

def start(stdwin):
    """
    ncurses has been initialised, and calls us with the root window.

    When we leave this function for whatever reason, ncurses will shut
    down and return the display to normal mode.  If we're leaving with
    an exception, ncurses will reraise it.

    """

    stdwin.nodelay(1) # Make getch() non-blocking

    tillconfig.kb.curses_init(stdwin)

    # Some of the init functions may make use of the database.
    with td.orm_session():
        ui.init(stdwin)

        if tillconfig.firstpage:
            tillconfig.firstpage()
        else:
            intropage()

    # Enter main event loop
    event.eventloop()

class CommandTracker(type):
    """
    Metaclass keeping track of all the types of command we understand.

    """
    def __init__(cls,name,bases,attrs):
        if not hasattr(cls,'_commands'):
            cls._commands=[]
        else:
            cls._commands.append(cls)

class command(object):
    __metaclass__=CommandTracker
    @staticmethod
    def add_arguments(parser):
        pass
    @staticmethod
    def run(args):
        pass

class runtill(command):
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
        parser.set_defaults(command=runtill.run,nolisten=False)
    @staticmethod
    def run(args):
        log.info("Starting version %s"%version)
        try:
            if tillconfig.usertoken_listen and not args.nolisten:
                user.tokenlistener(tillconfig.usertoken_listen)
            td.init(tillconfig.database)
            curses.wrapper(start)
        except:
            log.exception("Exception caught at top level")

        log.info("Shutting down")
        logging.shutdown()
        return event.shutdowncode

class dbshell(command):
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

class syncdb(command):
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

class flushdb(command):
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
            ok=raw_input("Sure? (y/n) ")
            if ok!='y': return 1
        td.remove_tables()
        print("Finished.")

class dbsetup(command):
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

class adduser(command):
    """
    Add a user.  This user will be a superuser.  This is necessary
    during setup.

    """
    @staticmethod
    def add_arguments(subparsers):
        parser=subparsers.add_parser(
            'adduser',help="add a superuser to the database",
            description=adduser.__doc__)
        parser.set_defaults(command=adduser.run)
        parser.add_argument("fullname", help="Full name of user")
        parser.add_argument("shortname", help="Short name of user")
        parser.add_argument("usertoken", help="User ID token")
    @staticmethod
    def run(args):
        td.init(tillconfig.database)
        with td.orm_session():
            u=User(fullname=args.fullname,shortname=args.shortname,
                   enabled=True,superuser=True)
            t=UserToken(token=args.usertoken,user=u,description=args.fullname)
            td.s.add(u)
            td.s.add(t)
            td.s.flush()
            print("User added.")

class totals(command):
    """
    Display a table of session totals.

    """
    @staticmethod
    def add_arguments(subparsers):
        parser=subparsers.add_parser(
            'totals',help="display table of session totals",
            description=adduser.__doc__)
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

def main():
    """Usual main entry point for the till software, unless you are doing
    something strange.  Reads the location of its global configuration,
    command line options, and the global configuration, and then starts
    the program.

    """
    
    try:
        f=file(configurlfile)
        configurl=f.readline()
        f.close()
    except:
        configurl=None
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
    for c in command._commands:
        c.add_arguments(subparsers)
    parser.set_defaults(configurl=configurl,configname="default",
                        database=None,logfile=None,debug=False,
                        interactive=False,disable_printer=False)
    args=parser.parse_args()

    if not args.configurl:
        parser.error("No configuration URL provided in "
                     "%s or on command line"%configurlfile)
    tillconfig.configversion=args.configurl
    f=urllib.urlopen(args.configurl)
    globalconfig=f.read()
    f.close()

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

    # Logging configuration.  If we have a log configuration file,
    # read it and apply it
    if args.logconfig:
        logconfig=yaml.load(args.logconfig)
        args.logconfig.close()
        logging.config.dictConfig(logconfig)
    else:
        log=logging.getLogger()
        formatter=logging.Formatter('%(asctime)s %(levelname)s %(name)s\n  %(message)s')
        handler=logging.StreamHandler()
        handler.setFormatter(formatter)
        handler.setLevel(logging.ERROR)
        log.addHandler(handler)
    if args.logfile:
        log=logging.getLogger()
        loglevel=logging.DEBUG if args.debug else logging.INFO
        loghandler=logging.StreamHandler(args.logfile)
        loghandler.setFormatter(formatter)
        loghandler.setLevel(logging.DEBUG if args.debug else logging.INFO)
        log.addHandler(loghandler)
        log.setLevel(loglevel)
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    if args.logsql:
        logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
    if 'printer' in config:
        pc=config['printer']
        # Deal with legacy printer configurations: a two-tuple of a callable
        # and its arguments
        if hasattr(pc,"__getitem__"):
            printer.driver=pc[0](*pc[1])
        else:
            printer.driver=pc
    else:
        log.info("no printer configured: using nullprinter()")
        printer.driver=pdrivers.nullprinter()
    if args.disable_printer:
        printer.driver=pdrivers.nullprinter(name="disabled-printer")
    if 'labelprinter' in config:
        printer.labeldriver=config['labelprinter'][0](
            *config['labelprinter'][1])
    tillconfig.database=config.get('database')
    if args.database is not None: tillconfig.database=args.database
    tillconfig.kb=config['kbdriver']
    if 'kitchenprinter' in config:
        foodorder.kitchenprinter=config['kitchenprinter']
    foodorder.menuurl=config.get('menuurl')
    tillconfig.pubname=config['pubname']
    tillconfig.pubnumber=config['pubnumber']
    tillconfig.pubaddr=config['pubaddr']
    tillconfig.currency=config['currency']
    tillconfig.all_payment_methods=config['all_payment_methods']
    tillconfig.payment_methods=config['payment_methods']
    if 'pricepolicy' in config:
        tillconfig.pricepolicy=config['pricepolicy']
    if 'format_currency' in config:
        tillconfig.fc=config['format_currency']
    if 'priceguess' in config:
        tillconfig.priceguess=config['priceguess']
    if 'deptkeycheck' in config:
        tillconfig.deptkeycheck=config['deptkeycheck']
    if 'checkdigit_print' in config:
        tillconfig.checkdigit_print=config['checkdigit_print']
    if 'checkdigit_on_usestock' in config:
        tillconfig.checkdigit_on_usestock=config['checkdigit_on_usestock']
    if 'allow_tabs' in config:
        tillconfig.allow_tabs=config['allow_tabs']
    if 'usestock_hook' in config:
        tillconfig.usestock_hook=config['usestock_hook']
    if 'hotkeys' in config:
        tillconfig.hotkeys=config['hotkeys']
    if 'firstpage' in config:
        tillconfig.firstpage=config['firstpage']
    if 'usertoken_handler' in config:
        tillconfig.usertoken_handler=config['usertoken_handler']
    if 'usertoken_listen' in config:
        tillconfig.usertoken_listen=config['usertoken_listen']

    if os.uname()[0]=='Linux':
        if os.getenv('TERM')=='linux':
            tillconfig.unblank_screen=_linux_unblank_screen
        elif os.getenv('TERM')=='xterm':
            os.putenv('TERM','linux')

    locale.setlocale(locale.LC_ALL,'')

    sys.exit(args.command(args))
