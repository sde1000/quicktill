"""
Entry point for the till application.  In normal use the application
will be started by the "runtill" script calling main() from this
module.

"""

# As the main entry point, any modules that define their own
# subcommands must be imported here otherwise they will be ignored.

import urllib.request, urllib.parse, urllib.error
import sys, os, logging, logging.config, locale, argparse, yaml
import termios,fcntl,array
import socket
import time
from . import ui,event,td,printer,tillconfig,foodorder,user,pdrivers,cmdline,extras
from . import dbsetup
from . import dbutils
from . import kbdrivers
from . import keyboard
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
    command = "start"
    help = "run the till interactively"

    @staticmethod
    def add_arguments(parser):
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
        parser.set_defaults(command=runtill.run, nolisten=False)

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

class kbdiff(cmdline.command):
    """Show differences between kbconfig and altkbconfig.

    Concentrates on updating linekey numbers
    """
    help = "diff keyboard table"

    @staticmethod
    def run(args):
        # We want to go through all codes defined in the new (alt) driver
        # and compare them to the codes in the existing driver
        codes = sorted(tillconfig.altkbdriver.inputs.items())
        td.init(tillconfig.database)
        changes = []
        with td.orm_session():
            for k, newcode in codes:
                if k not in tillconfig.kbdriver.inputs:
                    print("Current driver does not map '{}'".format(k))
                else:
                    oldcode = tillconfig.kbdriver.inputs[k]
                    if oldcode != newcode:
                        if isinstance(oldcode, kbdrivers._magstripecode) \
                           and isinstance(newcode, kbdrivers._magstripecode):
                            continue
                        print("Difference: {} {} -> {}".format(
                            k, repr(oldcode), repr(newcode)))
                        if isinstance(oldcode, keyboard.linekey) \
                           and isinstance(newcode, keyboard.linekey):
                            changes.append((oldcode._line, newcode._line))
        if changes:
            print("Database update commands:")
            print("BEGIN;")
            for old, new in changes:
                print("UPDATE keycaps SET keycode='K_TMP{new}' "
                      "WHERE keycode='K_LINE{old}';".format(old=old, new=new))
                print("UPDATE keyboard SET keycode='K_TMP{new}' "
                      "WHERE keycode='K_LINE{old}';".format(old=old, new=new))
                print("UPDATE keyboard SET menukey='K_TMP{new}' "
                      "WHERE menukey='K_LINE{old}';".format(old=old, new=new))
            for old, new in changes:
                print("UPDATE keycaps SET keycode='K_LINE{}' "
                      "WHERE keycode='K_TMP{}';".format(new, new))
                print("UPDATE keyboard SET keycode='K_LINE{}' "
                      "WHERE keycode='K_TMP{}';".format(new, new))
                print("UPDATE keyboard SET menukey='K_LINE{}' "
                      "WHERE menukey='K_TMP{}';".format(new, new))
            print("COMMIT;")

class totals(cmdline.command):
    """
    Display a table of session totals.

    """
    help = "display table of session totals"

    @staticmethod
    def add_arguments(parser):
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
    cmdline.command.add_subparsers(parser)
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
    # XXX support kbdiff command temporarily
    if 'kbdriver' in config:
        tillconfig.kbdriver = config['kbdriver']
    # XXX support kbdiff command temporarily
    if 'altkbdriver' in config:
        tillconfig.altkbdriver = config['altkbdriver']
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
