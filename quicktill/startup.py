"""Things that happen as the till is starting up.

These things are common to both application and server modes.
"""

import urllib.request
import logging
import logging.config
import warnings
import argparse
import tomli
import importlib
from pathlib import Path
from types import ModuleType
from . import tillconfig
from .version import version

# The following imports are to ensure subcommands are loaded
from . import dbsetup  # noqa: F401
from . import dbutils  # noqa: F401
from . import secretstore  # noqa: F401
from . import monitor  # noqa: F401
# End of subcommand imports


log = logging.getLogger(__name__)

configurlfile = Path("/etc/quicktill/configurl")

importsfile = Path("/etc/quicktill/default-imports")

importsdir = Path("/etc/quicktill/default-imports.d")

default_config = """
configurations = {
  'default': {
    'description': 'Built-in default configuration',
  }
}
"""


def _process_importsfile(path):
    try:
        with path.open() as f:
            for l in f.readlines():
                for i in l.partition('#')[0].split():
                    importlib.import_module(i)
    except Exception:
        print(f"Exception raised while working on {path}")
        raise


def process_etc_files():
    try:
        with configurlfile.open() as f:
            configurl = f.readline().strip()
    except FileNotFoundError:
        configurl = None

    if importsdir.is_dir():
        for path in importsdir.iterdir():
            if path.suffixes:
                continue
            if path.name[-1] == "~":
                continue
            if not path.is_file():
                continue
            _process_importsfile(path)

    if importsfile.is_file():
        _process_importsfile(importsfile)

    return configurl


def add_common_arguments(parser, configurl):
    parser.add_argument("--version", action="version", version=version)
    parser.add_argument("-u", "--config-url", action="store",
                        dest="configurl", default=configurl,
                        help="URL of global till configuration file; "
                        f"overrides contents of {configurlfile}")
    parser.add_argument("-d", "--database", action="store",
                        dest="database",
                        help="Database connection string; overrides "
                        "database specified in configuration file")
    loggroup = parser.add_mutually_exclusive_group()
    loggroup.add_argument("-y", "--log-config",
                          help="Logging configuration file "
                          "in TOML", type=argparse.FileType('rb'),
                          dest="logconfig")
    loggroup.add_argument("-l", "--logfile", type=argparse.FileType('a'),
                          dest="logfile", help="Simple logging output file")
    parser.add_argument("--debug", action="store_true", dest="debug",
                        help="Include debug output in log")
    parser.add_argument("--log-sql", action="store_true", dest="logsql",
                        help="Include SQL queries in logfile")


def configure_logging(args, stderr_level=logging.ERROR):
    # Logging configuration.  If we have a log configuration file,
    # read it and apply it.  This is done before the main
    # configuration file is imported so that log output from the
    # import can be directed appropriately.
    rootlog = logging.getLogger()
    if args.logconfig:
        logconfig = tomli.load(args.logconfig)
        args.logconfig.close()
        logging.config.dictConfig(logconfig)
    else:
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)s %(name)s\n  %(message)s')
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        handler.setLevel(stderr_level)
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

    return rootlog


def read_config(args):
    if args.configurl:
        log.info("reading configuration %s", args.configurl)
        tillconfig.configversion = args.configurl
        f = urllib.request.urlopen(args.configurl)
        globalconfig = f.read()
        f.close()
    else:
        log.warning("running with no configuration file")
        globalconfig = default_config

    g = ModuleType("globalconfig")
    g.configname = getattr(args, "configname", None)
    exec(globalconfig, g.__dict__)

    # Take note of deprecation warnings from the config file
    warnings.filterwarnings("default", category=DeprecationWarning,
                            module=g.__name__)
    logging.captureWarnings(True)

    return g
