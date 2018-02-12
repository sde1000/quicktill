import selectors
import time
import logging

log = logging.getLogger(__name__)

class time_guard:
    def __init__(self, name, max_time):
        self._name = name
        self._max_time = max_time

    def __enter__(self):
        self._start_time = time.time()

    def __exit__(self, type, value, traceback):
        t = time.time()
        time_taken = t - self._start_time
        if time_taken > self._max_time:
            log.info("time_guard: %s took %f seconds", self._name, time_taken)

doread_time_guard = time_guard("doread", 0.5)
dowrite_time_guard = time_guard("dowrite", 0.5)
timeout_time_guard = time_guard("timeout", 0.5)

class SelectorsMainLoop:
    """Event loop based on selectors module

    selectors was introduced in python 3.4
    """
    def __init__(self):
        self._sel = selectors.DefaultSelector()
        self.exit_code = None
        # Future events: key is wrapper object, value is time
        self._timeouts = {}

    def shutdown(self, code):
        self.exit_code = code

    class _selectors_fd_watch:
        def __init__(self, mainloop, fd, read, write, desc):
            self._mainloop = mainloop
            self._fd = fd
            self._doread = read
            self._dowrite = write
            self.description = desc
            events = 0
            if read:
                events |= selectors.EVENT_READ
            if write:
                events |= selectors.EVENT_WRITE
            self._mainloop._sel.register(fd, events, self._ready)

        def remove(self):
            self._mainloop._sel.unregister(self._fd)

        def _ready(self, mask):
            if self._doread and (mask & selectors.EVENT_READ):
                with doread_time_guard:
                    self._doread()
            if self._dowrite and (mask & selectors.EVENT_WRITE):
                with dowrite_time_guard:
                    self._dowrite()

    def add_fd(self, fd, read=None, write=None, desc=None):
        """Start watching a fd

        Call read or write as appropriate when the fd is ready

        Returns an object with a "remove" method that can be used to
        cancel the watch.
        """
        return self._selectors_fd_watch(self, fd, read, write, desc)

    class _selectors_timeout:
        def __init__(self, mainloop, func, desc):
            self._mainloop = mainloop
            self._func = func
            self.description = desc

        def cancel(self):
            del self._mainloop._timeouts[self], self._func

    def add_timeout(self, timeout, func, desc=None):
        """Add a callback for an amount of time in the future

        Returns an object that can be used to cancel the callback.
        """
        now = time.time()
        call_at = now + timeout
        wrapper = self._selectors_timeout(self, func, desc)
        self._timeouts[wrapper] = call_at
        return wrapper

    def iterate(self):
        # Work out what the earliest timeout is
        timeout = None
        if self._timeouts:
            t = time.time()
            earliest = min(self._timeouts.values())
            timeout = earliest - t
        for key, mask in self._sel.select(timeout):
            key.data(mask)
        # Process any events whose time has come
        t = time.time()
        todo = [wrapper for wrapper, call_at in self._timeouts.items()
                if call_at <= t]
        for i in todo:
            with timeout_time_guard:
                del self._timeouts[i]
                i._func()
