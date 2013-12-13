"""
Entry point for the till application.  In normal use the application
will be started by the "runtill" script calling main() from this
module.

"""

from __future__ import print_function
import sys,os,curses,logging,logging.config,locale,argparse,urllib,yaml
from . import ui,keyboard,event,td,printer,tillconfig,event,foodorder
from .version import version
from .models import KeyCap,Session
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
        parser.set_defaults(command=runtill.run)
    @staticmethod
    def run(args):
        log.info("Starting version %s"%version)
        try:
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
    usage="usage: %prog [options] [command]"
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
    subparsers=parser.add_subparsers(title="commands")
    for c in command._commands:
        c.add_arguments(subparsers)
    parser.set_defaults(configurl=configurl,configname="default",
                        database=None,logfile=None,debug=False,
                        interactive=False)
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
        printer.driver=config['printer'][0](*config['printer'][1])
    else:
        printer.driver=pdrivers.nullprinter()
    printer.kickout=printer.driver.kickout
    if 'labelprinter' in config:
        printer.labeldriver=config['labelprinter'][0](
            *config['labelprinter'][1])
    tillconfig.database=config.get('database')
    if args.database is not None: tillconfig.database=args.database
    tillconfig.kb=config['kbdriver']
    foodorder.kitchenprinter=config.get('kitchenprinter')
    foodorder.menuurl=config.get('menuurl')
    tillconfig.pubname=config['pubname']
    tillconfig.pubnumber=config['pubnumber']
    tillconfig.pubaddr=config['pubaddr']
    tillconfig.currency=config['currency']
    tillconfig.cashback_limit=config['cashback_limit']
    tillconfig.payment_methods=config['payment_methods']
    if 'cashback_first' in config:
        tillconfig.cashback_first=config['cashback_first']
    if 'pricepolicy' in config:
        tillconfig.pricepolicy=config['pricepolicy']
    if 'format_currency' in config:
        tillconfig.fc=config['format_currency']
    if 'priceguess' in config:
        tillconfig.priceguess=config['priceguess']
    if 'deptkeycheck' in config:
        tillconfig.deptkeycheck=config['deptkeycheck']
    if 'nosale' in config:
        tillconfig.nosale=config['nosale']
    if 'checkdigit_print' in config:
        tillconfig.checkdigit_print=config['checkdigit_print']
    if 'checkdigit_on_usestock' in config:
        tillconfig.checkdigit_on_usestock=config['checkdigit_on_usestock']
    if 'allow_tabs' in config:
        tillconfig.allow_tabs=config['allow_tabs']
    if 'transaction_notes' in config:
        tillconfig.transaction_notes=config['transaction_notes']
    if 'usestock_hook' in config:
        tillconfig.usestock_hook=config['usestock_hook']
    if 'hotkeys' in config:
        tillconfig.hotkeys=config['hotkeys']
    if 'firstpage' in config:
        tillconfig.firstpage=config['firstpage']

    if os.uname()[0]=='Linux':
        if os.getenv('TERM')=='xterm': os.putenv('TERM','linux')

    locale.setlocale(locale.LC_ALL,'')

    sys.exit(args.command(args))
