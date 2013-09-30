"""
Entry point for the till application.  In normal use the application
will be started by the "runtill" script calling main() from this
module.

"""

from __future__ import print_function
import sys,os,curses,logging,locale
from . import ui,keyboard,event,td,printer,tillconfig,event,foodorder
from .version import version
from .models import KeyCap,Session
log=logging.getLogger(__name__)

def start(stdwin):
    """
    ncurses has been initialised, and calls us with the root window.

    When we leave this function for whatever reason, ncurses will shut
    down and return the display to normal mode.  If we're leaving with
    an exception, ncurses will reraise it.

    """

    stdwin.nodelay(1) # Make getch() non-blocking

    # Some of the init functions may make use of the database.
    td.start_session()
    ui.init(stdwin)

    # Create pages for various functions
    fp=None
    for pagedef,hotkey,args in tillconfig.pages:
        p=ui.addpage(pagedef,hotkey,args)
        if fp is None: fp=p
    ui.selectpage(fp)
    fp.firstpageinit()

    td.end_session()

    # Enter main event loop
    event.eventloop()

def runtill(args):
    """
    Run the till interactively.

    """
    if len(args)>0:
        print("runtill takes no arguments.")
        return 1
    log.info("Starting version %s"%version)
    try:
        td.init(tillconfig.database)
        td.start_session()
        # Copy keycaps from database to keyboard driver
        caps=td.s.query(KeyCap).filter(KeyCap.layout==tillconfig.kbtype).all()
        for key in caps:
            if ui.kb.setkeycap(keyboard.keycodes[key.keycode],key.keycap)==False:
                log.info("Deleting stale keycap for layout %d keycode %s"%(
                    tillconfig.kbtype,key.keycode))
                td.s.delete(key)
        td.s.flush()
        td.end_session()
        curses.wrapper(start)
    except:
        log.exception("Exception caught at top level")

    log.info("Shutting down")
    logging.shutdown()
    return event.shutdowncode

def dbshell(args):
    """
    Provide an interactive python prompt with the 'td' module and
    'models.*' already imported, and a database session started.

    """
    import code
    import readline
    td.init(tillconfig.database)
    td.start_session()
    console=code.InteractiveConsole()
    console.push("import quicktill.td as td")
    console.push("from quicktill.models import *")
    console.interact()
    td.end_session()

def syncdb(args):
    """
    Create database tables that have not already been created.

    """
    td.init(tillconfig.database)
    td.create_tables()

def flushdb(args):
    """
    Remove database tables.  This command will refuse to run without
    an additional "really" option if your database contains more than
    two sessions of data, because it will delete it all!  It's
    intended for use during testing and setup.

    """
    really=len(args)>0 and args[0]=="really"
    td.init(tillconfig.database)
    td.start_session()
    sessions=td.s.query(Session).count()
    td.end_session()
    if sessions>2 and not really:
        print("You have more than two sessions in the database!  Try again "
              "as 'flushdb really' if you definitely want to remove all "
              "the data and tables from the database.")
        return 1
    if sessions>0:
        print("There is some data in the database.  Are you sure you want "
              "to remove all the data and tables?")
        ok=raw_input("Sure? (y/n) ")
        if ok!='y': return 1
    td.remove_tables()
    print("Finished.")

def dbsetup(args):
    """
    With no arguments, print a template database setup file.
    With one argument, import and process a database setup file.

    """
    from .dbsetup import template,setup
    if len(args)==0:
        print(template)
    elif len(args)==1:
        td.init(tillconfig.database)
        td.start_session()
        setup(file(args[0]))
        td.end_session()
    else:
        print("Usage: dbsetup [filename]")
        return 1

def helpcmd(args):
    """
    Provide help on available commands.

    """
    if len(args)==0:
        print("Available commands:")
        for c in commands.keys():
            print("  %s"%c)
    elif len(args)==1:
        if args[0] in commands:
            print("Help on %s:"%args[0])
            print(commands[args[0]].__doc__)
        else:
            print("Unknown command '%s'."%args[0])
            return 1
    else:
        print("Usage: help [command]")
        return 1
        
commands={
    'dbshell':dbshell,
    'runtill':runtill,
    'syncdb':syncdb,
    'flushdb':flushdb,
    'dbsetup':dbsetup,
    'help':helpcmd,
    }

def main():
    """Usual main entry point for the till software, unless you are doing
    something strange.  Reads the location of its global configuration,
    command line options, and the global configuration, and then starts
    the program.

    """
    
    try:
        f=file("/etc/quicktill/configurl")
        configurl=f.readline()
        f.close()
    except:
        configurl=None
    from optparse import OptionParser
    import urllib
    usage="usage: %prog [options] [command]"
    parser=OptionParser(usage,version=version)
    parser.add_option("-u", "--config-url", action="store",
                      type="string", dest="configurl",
                      help="URL of global till configuration file")
    parser.add_option("-c", "--config-name", action="store",
                      type="string", dest="configname",
                      help="Till type to use from configuration file")
    parser.add_option("-d", "--database", action="store",
                      type="string", dest="database",
                      help="Database connection string; overrides "
                      "configuration file")
    parser.add_option("-l", "--logfile", action="store",
                      type="string", dest="logfile",
                      help="Log filename")
    parser.add_option("--debug", action="store_true", dest="debug",
                      help="Include debug output in logfile")
    parser.add_option("--log-sql", action="store_true", dest="logsql",
                      help="Include SQL queries in logfile")
    parser.set_defaults(configurl=configurl,configname="default",
                        database=None,logfile=None,debug=False,
                        interactive=False)
    (options,args)=parser.parse_args()
    if len(args)==0:
        command="runtill"
    elif len(args)>0:
        command=args[0]
    if options.configurl==None:
        parser.error("No configuration URL provided in "
                     "/etc/quicktill/configurl or on command line")
    tillconfig.configversion=options.configurl
    f=urllib.urlopen(options.configurl)
    globalconfig=f.read()
    f.close()

    import imp
    g=imp.new_module("globalconfig")
    g.configname=options.configname
    exec globalconfig in g.__dict__

    config=g.configurations.get(options.configname)
    if config is None:
        print(("Configuration \"%s\" does not exist.  "
               "Available configurations:"%options.configname))
        for i in list(g.configurations.keys()):
            print("%s: %s"%(i,g.configurations[i]['description']))
        sys.exit(1)

    if options.debug and options.logfile is None:
        print("You must specify a log file to enable debugging output.")
        sys.exit(1)

    log=logging.getLogger()
    formatter=logging.Formatter('%(asctime)s %(levelname)s %(name)s\n  %(message)s')
    handler=logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(logging.ERROR)
    log.addHandler(handler)
    if options.logfile:
        loglevel=logging.DEBUG if options.debug else logging.INFO
        loghandler=logging.FileHandler(options.logfile)
        loghandler.setFormatter(formatter)
        loghandler.setLevel(logging.DEBUG if options.debug else logging.INFO)
        log.addHandler(loghandler)
        log.setLevel(loglevel)
        if options.logsql:
            logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

    if 'printer' in config:
        printer.driver=config['printer'][0](*config['printer'][1])
    else:
        printer.driver=pdrivers.nullprinter()
    printer.kickout=printer.driver.kickout
    if 'labelprinter' in config:
        printer.labeldriver=config['labelprinter'][0](
            *config['labelprinter'][1])
    tillconfig.pages=config['pages']
    tillconfig.database=config.get('database')
    if options.database is not None: tillconfig.database=options.database
    ui.kb=config['kbdriver']
    tillconfig.kbtype=config['kbtype']
    foodorder.kitchenprinter=config.get('kitchenprinter')
    foodorder.menuurl=config.get('menuurl')
    tillconfig.pubname=config['pubname']
    tillconfig.pubnumber=config['pubnumber']
    tillconfig.pubaddr=config['pubaddr']
    tillconfig.currency=config['currency']
    tillconfig.cashback_limit=config['cashback_limit']
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
    if 'modkeyinfo' in config:
        tillconfig.modkeyinfo=config['modkeyinfo']
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
    if 'btcmerch' in config:
        tillconfig.btcmerch_api=config['btcmerch']

    if os.uname()[0]=='Linux':
        if os.getenv('TERM')=='xterm': os.putenv('TERM','linux')

    locale.setlocale(locale.LC_ALL,'')

    if command in commands:
        sys.exit(commands[command](args[1:]))
    else:
        print("Unknown command '%s'.")
        # XXX print out list of commands
        sys.exit(1)
