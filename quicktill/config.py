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

# Should "None" be included as a valid value? This should be optional,
# defined per ConfigItem instance.

# How is "None" represented in the database? It is represented as a
# value that is invalid for the type of config item (eg. the empty
# string, for most types). Some types of config item (eg. "text")
# don't have an invalid value so can never take the value None.

# When the value in the database is invalid for the type and None
# isn't a valid value, we can't return None so return the default. If
# the default is None then this is a programmer error!


class ConfigItem:
    """A text configuration setting
    """
    _keys = {}
    _listener = None
    none_supported = False

    def __init__(self, key, default, type="text",
                 display_name=None, description=None, allow_none=False):
        # NB 'default' may be changed after init simply by setting the
        # attribute
        self.key = key
        self.default = default
        self.type = type
        self.display_name = display_name or key
        self.description = description or self.display_name
        self._allow_none = allow_none
        self._value = None
        self._current = False
        self._keys[self.key] = self
        self._notify = []

        if allow_none and not self.none_supported:
            raise Exception("ConfigItem has allow_none set, but None is not "
                            "a supported config value")

        rt = self.from_db(self.to_db(self.default))
        if rt is None and not allow_none:
            raise Exception("ConfigItem default round-trips to None, but "
                            "allow_none is not set")
        if rt != self.default:
            raise Exception("ConfigItem default does not survive db round-trip")

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

    def _test_set(self, dbvalue):
        """Used by tests to fake reading a value from the database
        """
        assert isinstance(dbvalue, str)
        self._value = self.from_db(dbvalue)
        self._current = True

    def __call__(self):
        if not self._current:
            self._read()
        if self._value is None:
            return None if self._allow_none else self.default
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
    none_supported = True

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


class PositiveIntConfigItem(ConfigItem):
    none_supported = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, type="positive integer", **kwargs)

    @classmethod
    def from_db(cls, s):
        try:
            r = int(s)
            if r < 0:
                raise ValueError("Unexpected negative integer")
            return r
        except Exception:
            return

    @classmethod
    def to_db(cls, v):
        return str(v)


class BooleanConfigItem(ConfigItem):
    none_supported = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, type="boolean", **kwargs)

    @classmethod
    def from_db(cls, s):
        if not s:
            return
        return s[0] in ('y', 'Y', 't', 'T')

    @classmethod
    def to_db(cls, v):
        return "Yes" if v else "" if v is None else "No"


class DateConfigItem(ConfigItem):
    none_supported = True

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


class TimeConfigItem(ConfigItem):
    none_supported = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, type="time", **kwargs)

    @classmethod
    def from_db(cls, s):
        try:
            return datetime.time(*(int(x) for x in s.split(':')))
        except Exception:
            return

    @classmethod
    def to_db(cls, v):
        if v is None:
            return ""
        return str(v)


class IntervalConfigItem(ConfigItem):
    none_supported = True
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
    none_supported = True

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
