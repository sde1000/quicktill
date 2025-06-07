"""Entry point for the till, when run as an application.

In normal use the application will be started by the "runtill" script
calling main() from this module.
"""

import sys
import logging
import argparse
import socket
import time
from . import startup
from . import ui
from . import td
from . import lockscreen
from . import tillconfig
from . import user
from . import pdrivers
from . import cmdline
from . import kbdrivers
from . import keyboard
from . import config
from . import listen
from . import barcode
from .version import version
from .models import Register
import subprocess

# The following imports are to ensure subcommands are loaded
from . import foodcheck  # noqa: F401
# End of subcommand imports

log = logging.getLogger(__name__)


class intropage(ui.basicpage):
    def __init__(self):
        super().__init__()
        h, w = self.win.size()
        self.win.drawstr(1, 1, w - 2,
                         f"This is quicktill version {version}")
        y = 5
        if tillconfig.hotkeys:
            self.win.drawstr(3, 1, w - 2,
                             "To continue, press one of these keys:")
            for k in tillconfig.hotkeys:
                self.win.drawstr(y, 3, w - 4, str(k))
                y = y + 1
        self.win.drawstr(y, 1, w - 2, "Press Q to quit.")
        self.win.move(0, 0)

    def keypress(self, k):
        if k == "q" or k == "Q":
            tillconfig.mainloop.shutdown(1)
        super().keypress(k)


class ValidateExitOption(argparse.Action):
    def __call__(self, parser, args, values, option_string=None):
        code, text = values
        try:
            code = int(code)
        except ValueError:
            raise argparse.ArgumentError(
                self, f"first argument to {self.dest} must be an integer")
        current = getattr(args, self.dest, None)
        if not current:
            current = []
        current.append((code, text))
        setattr(args, self.dest, current)


def window_geometry(value):
    parts = value.split('x')
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"'{value}' is not a valid window geometry")
    try:
        width = int(parts[0])
        height = int(parts[1])
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            str(e))
    return width, height


class runtill(cmdline.command):
    """
    Run the till interactively.

    """
    command = "start"
    help = "run the till interactively"

    @staticmethod
    def add_arguments(parser):
        parser.add_argument(
            "-e", "--exit-option", nargs=2,
            dest="exitoptions",
            action=ValidateExitOption,
            metavar=("EXITCODE", "TEXT"),
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
            dest="minimum_lock_screen_time", default=30,
            action="store", type=int, metavar="LOCKTIME",
            help="Display the lock screen for at least LOCKTIME seconds "
            "before considering the till to be idle")
        parser.add_argument(
            "-k", "--keyboard", dest="keyboard", default=False,
            action=argparse.BooleanOptionalAction,
            help="Show an on-screen keyboard if possible")
        parser.add_argument(
            "--hardware-keyboard", dest="hwkeyboard", default=True,
            action=argparse.BooleanOptionalAction,
            help="Enable or disable support for hardware keyboard")
        debugp = parser.add_argument_group(
            title="debug / development arguments",
            description="These arguments may be useful during development "
            "and testing")
        debugp.add_argument(
            "--nolisten", action=argparse.BooleanOptionalAction,
            default=False, dest="nolisten",
            help="Disable listening sockets for user tokens and barcodes")
        debugp.add_argument(
            "--glib-mainloop", action=argparse.BooleanOptionalAction,
            default=False, dest="glibmainloop",
            help="Use GLib mainloop")
        gtkp = parser.add_argument_group(
            title="display system arguments",
            description="The Gtk display system can be used instead of the "
            "default ncurses display system")
        gtkp.add_argument(
            "--gtk", dest="gtk", default=False,
            action=argparse.BooleanOptionalAction,
            help="Use Gtk display system")
        gtkp.add_argument(
            "--fullscreen", dest="fullscreen", default=False,
            action=argparse.BooleanOptionalAction,
            help="Use the full screen if possible")
        gtkp.add_argument(
            "--font", dest="font", default="sans 20",
            action="store", type=str, metavar="FONT_DESCRIPTION",
            help="Set the font to be used for proportional text")
        gtkp.add_argument(
            "--monospace-font", dest="monospace", default="monospace 20",
            action="store", type=str, metavar="FONT_DESCRIPTION",
            help="Set the font to be used for monospace text")
        gtkp.add_argument(
            "--pitch-adjust", dest="pitch_adjust", default=0,
            action="store", type=int, metavar="PIXELS",
            help="Adjust the row height for text")
        gtkp.add_argument(
            "--baseline-adjust", dest="baseline_adjust", default=0,
            action="store", type=int, metavar="PIXELS",
            help="Adjust the baseline for text")
        gtkp.add_argument(
            "--hide-pointer", dest="hide_pointer", default=False,
            action=argparse.BooleanOptionalAction,
            help="Hide the pointer when over the till window")
        gtkp.add_argument(
            "--geometry", dest="geometry", default=None,
            action="store", type=window_geometry, metavar="WIDTHxHEIGHT",
            help="Set the initial window size")

    class _dbg_kbd_input:
        """Process input from debug keyboard
        """
        def __init__(self, f):
            self.f = f
            self.handle = tillconfig.mainloop.add_fd(
                f.fileno(), self.doread, desc="debug keyboard")

        def doread(self):
            i = self.f.readline().strip().decode("utf-8")
            if not i:
                log.warning("Debug keyboard closed")
                self.handle.remove()
                self.f.close()
                return
            with td.orm_session():
                if i.startswith("usertoken:"):
                    ui.handle_keyboard_input(user.token(i[10:]))
                elif i.startswith("K_") and hasattr(keyboard, i):
                    ui.handle_keyboard_input(getattr(keyboard, i))
                else:
                    ui.handle_keyboard_input(i)

    @staticmethod
    def update_notified(payload):
        log.info("Update notification received via database; exiting")
        tillconfig.mainloop.shutdown(tillconfig.idle_exit_code)

    @staticmethod
    def run(args):
        log.info("Starting version %s", version)

        if tillconfig.keyboard and tillconfig.keyboard_driver \
           and args.hwkeyboard:
            ui.keyboard_filter_stack.insert(
                0, tillconfig.keyboard_driver(tillconfig.keyboard))

        # Initialise event loop
        if args.glibmainloop or args.gtk:
            from . import event_glib
            if event_glib.GLibMainLoop:
                tillconfig.mainloop = event_glib.GLibMainLoop()
            else:
                log.error("GLib not available")
                return 1
        else:
            from . import event
            tillconfig.mainloop = event.SelectorsMainLoop()

        # Initialise database notifications listener
        listen.listener = listen.db_listener(tillconfig.mainloop, td.engine)

        if tillconfig.usertoken_listen and not args.nolisten:
            user.tokenlistener(tillconfig.usertoken_listen)
        if tillconfig.usertoken_listen_v6 and not args.nolisten:
            user.tokenlistener(tillconfig.usertoken_listen_v6,
                               addressfamily=socket.AF_INET6)
        if tillconfig.barcode_listen and not args.nolisten:
            barcode.barcodelistener(tillconfig.barcode_listen)
        if tillconfig.barcode_listen_v6 and not args.nolisten:
            barcode.barcodelistener(tillconfig.barcode_listen_v6,
                                    addressfamily=socket.AF_INET6)
        if args.exitoptions:
            tillconfig.exitoptions = args.exitoptions
        tillconfig.idle_exit_code = args.exit_when_idle
        tillconfig.minimum_run_time = args.minimum_run_time
        tillconfig.minimum_lock_screen_time = args.minimum_lock_screen_time
        tillconfig.start_time = time.time()
        if args.exit_when_idle is not None:
            # We should also exit if the "update" notification is sent
            listen.listener.listen_for("update", runtill.update_notified)

        # Load config from database, update database with new config items,
        # initialise config change listener, and generate a new register ID
        with td.orm_session():
            config.ConfigItem.listen_for_changes(listen.listener)
            config.ConfigItem.preload()
            reg = Register(version=version,
                           config_name=tillconfig.configname,
                           terminal_name=tillconfig.terminal_name)
            td.s.add(reg)
            td.s.flush()
            tillconfig.register_id = reg.id

        dbg_kbd = None
        try:
            if args.keyboard and tillconfig.keyboard \
               and not args.gtk:
                dbg_kbd = subprocess.Popen(
                    [sys.argv[0],
                     "-u", tillconfig.configversion,
                     "-c", tillconfig.configname,
                     "on-screen-keyboard"],
                    bufsize=0,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE)
                runtill._dbg_kbd_input(dbg_kbd.stdout)

            if args.gtk:
                from . import ui_gtk
                ui_gtk.run(
                    fullscreen=args.fullscreen,
                    font=args.font,
                    monospace_font=args.monospace,
                    keyboard=args.keyboard,
                    geometry=args.geometry,
                    pitch_adjust=args.pitch_adjust,
                    baseline_adjust=args.baseline_adjust,
                    hide_pointer=args.hide_pointer)
            else:
                from . import ui_ncurses
                ui_ncurses.run()
        except Exception:
            log.exception("Exception caught at top level")
        finally:
            if dbg_kbd is not None:
                dbg_kbd.stdin.close()
                dbg_kbd.wait()

        log.info("Shutting down")
        logging.shutdown()
        return tillconfig.mainloop.exit_code


class on_screen_keyboard(cmdline.command):
    command = "on-screen-keyboard"
    help = "internal helper command for on-screen-keyboard"

    @staticmethod
    def run(args):
        if not tillconfig.keyboard:
            return
        from . import event_glib
        tillconfig.mainloop = event_glib.GLibMainLoop()
        from . import keyboard_gtk

        # Initialise database notifications listener
        listen.listener = listen.db_listener(tillconfig.mainloop, td.engine)

        def input_handler(keycode):
            if hasattr(keycode, "usertoken"):
                print("usertoken:" + keycode.usertoken)
            elif hasattr(keycode, "name"):
                print(keycode.name)
            else:
                print(keycode)
            sys.stdout.flush()

        window = keyboard_gtk.kbwindow(
            tillconfig.keyboard, input_handler)
        keyboard_gtk.run_standalone(window)


class ToastHandler(logging.Handler):
    def emit(self, record):
        ui.toast(self.format(record))


def main():
    """Usual main entry point for the till software.

    Reads the location of its global configuration, command line
    options (which may override that location), and then the global
    configuration, and starts the program.
    """

    configfile, config = startup.process_initial_config()

    parser = argparse.ArgumentParser(
        description="Figure out where all the money and stock went")

    startup.add_common_arguments(parser)

    parser.add_argument("-c", "--config-name", action="store",
                        dest="configname", default="default",
                        help="Till type to use from configuration file")
    parser.add_argument("-t", "--terminal-name", action="store",
                        dest="terminalname", default=None,
                        help="Terminal name to store for transaction lines "
                        "and payments created by this till instance")
    parser.add_argument("-f", "--user", action="store",
                        dest="user", type=int, default=None,
                        help="User ID to use when no other user information "
                        "is available (use 'listusers' command to check IDs)")
    parser.add_argument("--disable-printer",
                        action=argparse.BooleanOptionalAction,
                        default=False,
                        dest="disable_printer", help="Use the null printer "
                        "instead of the configured printer")

    cmdline.command.add_subparsers(
        parser, configfile, config.get("client-defaults", {}))

    parser.set_defaults(**config.get("client-defaults", {}))
    args = parser.parse_args()

    if not hasattr(args, 'command'):
        parser.error("No command supplied")

    if args.debug:
        tillconfig.debug = True

    rootlog = startup.configure_logging(args)

    # A postgresql restart causes sqlalchemy to log an error during
    # cleanup of the connection used by the "listen" module, which
    # ends up being displayed in a popup after the till has
    # exited. Hide this here.
    logging.getLogger('sqlalchemy.pool.impl.QueuePool').setLevel(logging.FATAL)

    # Set up handler to direct warnings to toaster UI
    toasthandler = ToastHandler()
    toastformatter = logging.Formatter('%(levelname)s: %(message)s')
    toasthandler.setFormatter(toastformatter)
    toasthandler.setLevel(logging.WARNING)
    rootlog.addHandler(toasthandler)

    tillconfig.configname = args.configname
    tillconfig.terminal_name = args.terminalname or args.configname

    g = startup.read_config(args)

    config = g.configurations.get(args.configname)
    if config is None:
        print(f'Configuration "{args.configname}" does not exist.  '
              'Available configurations:')
        for k, v in g.configurations.items():
            print(f"{k}: {v['description']}")
        sys.exit(1)

    if args.user:
        tillconfig.default_user = args.user

    # Defaults when options not specified in configuration
    tillconfig.keyboard_driver = kbdrivers.prehkeyboard
    tillconfig.firstpage = intropage

    # Process the configuration
    for opt, val in config.items():
        if opt == 'printer':
            if val and args.disable_printer:
                tillconfig.receipt_printer = pdrivers.nullprinter(
                    name="disabled-printer")
            else:
                tillconfig.receipt_printer = val
                if val:
                    lockscreen.CheckPrinter("Receipt printer", val)
        elif opt == "cash_drawer":
            if val and args.disable_printer:
                tillconfig.cash_drawer = pdrivers.nullprinter(
                    name="disabled-cash-drawer")
            else:
                tillconfig.cash_drawer = val
        elif opt == 'labelprinters':
            tillconfig.label_printers = val
        elif opt == 'database':
            tillconfig.database = val
        elif opt == 'keyboard_driver':
            tillconfig.keyboard_driver = val
        elif opt == 'keyboard':
            tillconfig.keyboard = val
        elif opt == 'keyboard_right':
            tillconfig.keyboard_right = val
        elif opt == 'format_currency':
            tillconfig.fc = val
        elif opt == 'hotkeys':
            tillconfig.hotkeys = val
        elif opt == 'firstpage':
            tillconfig.firstpage = val
        elif opt == 'barcode_listen':
            tillconfig.barcode_listen = val
        elif opt == 'barcode_listen_v6':
            tillconfig.barcode_listen_v6 = val
        elif opt == 'usertoken_handler':
            tillconfig.usertoken_handler = val
        elif opt == 'usertoken_listen':
            tillconfig.usertoken_listen = val
        elif opt == 'usertoken_listen_v6':
            tillconfig.usertoken_listen_v6 = val
        elif opt == 'description':
            tillconfig.configdescription = val
        elif opt == 'login_handler':
            tillconfig.login_handler = val
        else:
            log.warning("Unknown configuration option '%s'", opt)

    if tillconfig.receipt_printer:
        # Check that the receipt printer driver is of an appropriate type
        if tillconfig.receipt_printer.canvastype != "receipt":
            print("Invalid receipt printer configuration")
            sys.exit(1)

    if tillconfig.cash_drawer is None:
        tillconfig.cash_drawer = tillconfig.receipt_printer

    if args.database is not None:
        tillconfig.database = args.database

    if tillconfig.database:
        td.init(tillconfig.database)
    elif args.command.database_required:
        print("No database specified")
        sys.exit(1)

    sys.exit(args.command.run(args))
