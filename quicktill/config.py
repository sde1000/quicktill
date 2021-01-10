from .models import Config
from . import td
from .listen import listener
import datetime

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
        self.display_name = display_name
        self.description = description
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
    def preload(cls):
        td.s.query(Config).all()
        for ci in cls._keys.values():
            ci._read()

    def _read(self):
        if not self._listener:
            self._listener = listener.listen_for('config', self._config_changed)

        d = td.s.query(Config).get(self.key)
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

class IntConfigItem(ConfigItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, type="integer", **kwargs)

    @classmethod
    def from_db(cls, s):
        return int(s)

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
        parts = [ x.strip().split() for x in s.split(',') ]
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
