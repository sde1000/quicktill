"""Things that happen as the till is starting up.

These things are common to both application and server modes.
"""

import urllib.request
import logging
import logging.config
import warnings
import argparse
import tomllib
import json
import importlib
import os
import sys
from pathlib import Path
from types import ModuleType
from . import tillconfig, td
from .version import version

# The following imports are to ensure subcommands are loaded
from . import dbutils  # noqa: F401
from . import secretstore  # noqa: F401
from . import monitor  # noqa: F401
# End of subcommand imports


log = logging.getLogger(__name__)


# Legacy configuration file locations
configurlfile = Path("/etc/quicktill/configurl")
importsfile = Path("/etc/quicktill/default-imports")
importsdir = Path("/etc/quicktill/default-imports.d")

# Configuration to use when no site configuration file is specified
default_config = """
configurations = {
  'default': {
    'description': 'Built-in default configuration',
  }
}
"""


def _process_importsfile(path):
    with path.open() as f:
        for l in f.readlines():
            for i in l.partition('#')[0].split():
                yield i


def _process_etc_files():
    try:
        with configurlfile.open() as f:
            configurl = f.readline().strip()
    except FileNotFoundError:
        configurl = None

    imports = []

    if importsdir.is_dir():
        for path in importsdir.iterdir():
            if path.suffixes:
                continue
            if path.name[-1] == "~":
                continue
            if not path.is_file():
                continue
            imports.extend(_process_importsfile(path))

    if importsfile.is_file():
        imports.extend(_process_importsfile(importsfile))

    config = {}
    if configurl:
        config['client-defaults'] = {'configurl': configurl}
    if imports:
        config['imports'] = imports
    return config


def _config_locations():
    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    home = os.getenv("HOME")
    xdg_config_dirs = os.getenv("XDG_CONFIG_DIRS", default="/etc/xdg")

    if xdg_config_home:
        yield Path(xdg_config_home)
    elif home:
        yield Path(home) / ".config"

    for part in xdg_config_dirs.split(":"):
        yield Path(part)


def _find_initial_config():
    for loc in _config_locations():
        if loc.is_dir():
            cf = loc / "quicktill.toml"
            if cf.exists():
                try:
                    with open(cf, "rb") as f:
                        return (cf, tomllib.load(f))
                except tomllib.TOMLDecodeError as e:
                    print(f"{cf}: {e}", file=sys.stderr)
                    sys.exit(1)
            cf = loc / "quicktill.json"
            if cf.exists():
                try:
                    with open(cf, "r") as f:
                        return (cf, json.load(f))
                except json.JSONDecodeError as e:
                    print(f"{cf}: {e}", file=sys.stderr)
                    sys.exit(1)
    return (configurlfile, _process_etc_files())


def process_initial_config():
    configfile, config = _find_initial_config()

    if 'imports' in config:
        for i in config['imports']:
            try:
                importlib.import_module(i)
            except ModuleNotFoundError as e:
                print(f"{configfile}: {e} (mentioned in imports)",
                      file=sys.stderr)
                sys.exit(1)

    td.register_databases(configfile, config.get('database', {}))

    return configfile, config


def add_common_arguments(parser):
    parser.add_argument("--version", action="version", version=version)
    parser.add_argument("-u", "--config-url", action="store",
                        dest="configurl",
                        help="URL of site configuration file")
    parser.add_argument("-d", "--database", action="store",
                        dest="database",
                        help="Database name or connection string; overrides "
                        "database specified in site configuration file")
    loggroup = parser.add_mutually_exclusive_group()
    loggroup.add_argument("-y", "--log-config",
                          help="Logging configuration file "
                          "in TOML", type=argparse.FileType('rb'),
                          dest="logconfig")
    loggroup.add_argument("-l", "--logfile", type=argparse.FileType('a'),
                          dest="logfile", help="Simple logging output file")
    parser.add_argument("--debug", action=argparse.BooleanOptionalAction,
                        dest="debug", default=False,
                        help="Include debug output in log")
    parser.add_argument("--log-sql", action=argparse.BooleanOptionalAction,
                        dest="logsql", default=False,
                        help="Include SQL queries in logfile")


def configure_logging(args, stderr_level=logging.ERROR):
    # Logging configuration.  If we have a log configuration file,
    # read it and apply it.  This is done before the main
    # configuration file is imported so that log output from the
    # import can be directed appropriately.
    rootlog = logging.getLogger()
    if args.logconfig:
        logconfig = tomllib.load(args.logconfig)
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
        log.info("reading site configuration %s", args.configurl)
        tillconfig.configversion = args.configurl
        f = urllib.request.urlopen(args.configurl)
        globalconfig = f.read()
        f.close()
    else:
        log.warning("running with no site configuration file")
        globalconfig = default_config

    g = ModuleType("globalconfig")
    g.configname = getattr(args, "configname", None)
    exec(globalconfig, g.__dict__)

    # Take note of deprecation warnings from the config file
    warnings.filterwarnings("default", category=DeprecationWarning,
                            module=g.__name__)
    logging.captureWarnings(True)

    return g
