from .models import Config, penny
from . import td
from . import cmdline
from decimal import Decimal
import datetime
import sys

import logging
log = logging.getLogger(__name__)

# Do we want config items to be able to have no value?  No.  They
# should always have a valid value.

# What do we do when the value in the database is invalid for the
# type?  Read it as "None".  If we can't return None, return the
# default.

# What do we do when there's no database available?  Just use the defaults


class ConfigItem:
    """A configuration setting
    """
    _keys = {}
    _listener = None

    def __init__(self, key, default, type="text",
                 display_name=None, description=None):
        # NB 'default' may be changed after init simply by setting the
        # attribute
        self.key = key
        self.default = default
        self.type = type
        self.display_name = display_name or key
        self.description = description or self.display_name
        self._value = None
        self._current = False
        self._keys[self.key] = self
        self._notify = []

    @classmethod
    def from_db(cls, s):
        """Convert a string from the database to the appropriate python type
        """
        return s

    @classmethod
    def to_db(cls, v):
        """Convert a python value to a string for the database
        """
        if v is None:
            return ""
        return v

    def notify_on_change(self, func):
        self._notify.append(func)

    @classmethod
    def _config_changed(cls, configitem):
        ci = cls._keys.get(configitem)
        if ci:
            log.debug("config changed: %s, clearing cache", configitem)
            ci._value = None
            ci._current = False
            for func in ci._notify:
                func()
        else:
            log.debug("config changed: %s, no config found", configitem)

    @classmethod
    def listen_for_changes(cls, listener):
        if not cls._listener:
            cls._listener = listener.listen_for('config', cls._config_changed)

    @classmethod
    def preload(cls):
        td.s.query(Config).all()
        for ci in cls._keys.values():
            ci._read()

    def _read(self):
        d = td.s.get(Config, self.key)
        if d is None:
            # The config option doesn't exist in the database. Initialise it
            # with the default.
            td.s.add(Config(key=self.key,
                            value=self.to_db(self.default),
                            type=self.type,
                            display_name=self.display_name,
                            description=self.description))
            self._value = self.default
        else:
            self._value = self.from_db(d.value)
            if d.type != self.type:
                d.type = self.type
            if d.display_name != self.display_name:
                d.display_name = self.display_name
            if d.description != self.description:
                d.description = self.description
        self._current = True

    def __call__(self, allow_none=False):
        if not self._current:
            self._read()
        if self._value is None:
            return None if allow_none else self.default
        return self._value

    @property
    def value(self):
        return self()

    def __str__(self):
        return str(self())


class MultiLineConfigItem(ConfigItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, type="multiline text", **kwargs)


class IntConfigItem(ConfigItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, type="integer", **kwargs)

    @classmethod
    def from_db(cls, s):
        try:
            return int(s)
        except Exception:
            return

    @classmethod
    def to_db(cls, v):
        return str(v)


class BooleanConfigItem(ConfigItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, type="boolean", **kwargs)

    @classmethod
    def from_db(cls, s):
        if not s:
            # Empty, non-null string
            return False
        if s[0] in ('y', 'Y', 't', 'T'):
            return True
        return False

    @classmethod
    def to_db(cls, v):
        return "Yes" if v else "No"


class DateConfigItem(ConfigItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, type="date", **kwargs)

    @classmethod
    def from_db(cls, s):
        try:
            return datetime.date(*(int(x) for x in s.split('-')))
        except Exception:
            return

    @classmethod
    def to_db(cls, v):
        return str(v)


class IntervalConfigItem(ConfigItem):
    _units = {
        'w': 'weeks',
        'week': 'weeks',
        'weeks': 'weeks',
        'd': 'days',
        'day': 'days',
        'days': 'days',
        'h': 'hours',
        'hr': 'hours',
        'hour': 'hours',
        'hours': 'hours',
        'm': 'minutes',
        'min': 'minutes',
        'minute': 'minutes',
        'minutes': 'minutes',
        's': 'seconds',
        'sec': 'seconds',
        'second': 'seconds',
        'seconds': 'seconds',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, type="interval", **kwargs)

    @classmethod
    def from_db(cls, s):
        if not s:
            return
        kwargs = {}
        parts = [x.strip().split() for x in s.split(',')]
        try:
            for p in parts:
                num = int(p[0])
                kwargs[cls._units[p[1]]] = num
        except (ValueError, IndexError, KeyError):
            return
        return datetime.timedelta(**kwargs)

    @classmethod
    def to_db(cls, v):
        if v is None:
            return ""
        return f"{v.days} days, {v.seconds} seconds"


class MoneyConfigItem(ConfigItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, type="money", **kwargs)

    @classmethod
    def from_db(cls, s):
        try:
            return Decimal(s).quantize(penny)
        except Exception:
            return

    @classmethod
    def to_db(cls, v):
        return str(v)


class config_cmd(cmdline.command):
    command = "config"
    help = "view or modify till configuration"

    @staticmethod
    def add_arguments(parser):
        parser.add_argument(
            "-s", "--set", help="set a configuration key; if value is not "
            "provided on the command line, will read from stdin",
            action="store_true")
        parser.add_argument(
            "key", nargs="?", help="configuration key to view or modify")
        parser.add_argument(
            "value", nargs="?", help="value for configuration key")

    @staticmethod
    def run(args):
        if args.set and not args.key:
            print("The --set option requires a key to be specified")
            return 1

        with td.orm_session():
            if not args.key:
                for ci in td.s.query(Config).order_by(Config.key).all():
                    print(f"{ci.key}: {ci.display_name}: {ci.value}")
                return
            ci = td.s.get(Config, args.key)
            if not ci:
                print(f"Config key {args.key} does not exist")
                return 1
            if args.set or args.value:
                ci.value = args.value or sys.stdin.read().strip()
            print(f"Key: {ci.key}")
            if args.key in ConfigItem._keys:
                cf = ConfigItem._keys[args.key]
                print(f"Name: {cf.display_name}")
                print(f"Description: {cf.description}")
                print(f"Type: {cf.type}")
                print(f"Default value: {cf.to_db(cf.default)}")
            print(f"{'New' if args.set or args.value else 'Current'} "
                  f"value: {ci.value}")
