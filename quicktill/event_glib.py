from .event import *
import sys

try:
    import gi
    gi.require_version('GLib', '2.0')
    from gi.repository import GLib
except:
    GLib = None

class GLibMainLoop:
    def __init__(self):
        self.exit_code = None
        self._context = GLib.main_context_default()

    def shutdown(self, code):
        self.exit_code = code

    def iterate(self):
        self._exc_info = None
        self._context.iteration()
        if self._exc_info:
            raise self._exc_info[0].with_traceback(
                self._exc_info[1], self._exc_info[2])

    class _glib_fd_watch:
        def __init__(self, mainloop, fd, read, write, desc):
            self._mainloop = mainloop
            self.description = desc
            condition = GLib.IOCondition(0)
            if read:
                condition |= GLib.IOCondition.IN | GLib.IOCondition.HUP
            if write:
                condition |= GLib.IOCondition.OUT
            self._doread = read
            self._dowrite = write
            self._handle = GLib.unix_fd_add_full(
                0, fd, condition, self._call, None, None)

        def _call(self, fd, condition, user_data, unknown):
            try:
                if (condition & GLib.IOCondition.IN) or (condition & GLib.IOCondition.HUP):
                    self._doread()
                if condition & GLib.IOCondition.OUT:
                    self._dowrite()
            except Exception as e:
                self._mainloop._exc_info = sys.exc_info()
            return True

        def remove(self):
            GLib.source_remove(self._handle)
            del self._doread, self._dowrite
            
    def add_fd(self, fd, read=None, write=None, desc=None):
        return self._glib_fd_watch(self, fd, read, write, desc)

    class _glib_timeout:
        def __init__(self, mainloop, timeout, func, desc):
            self._mainloop = mainloop
            self._func = func
            self.description = desc
            self._source = GLib.timeout_add(
                int(timeout * 1000), self._call)

        def _call(self, *args):
            try:
                self._func()
            except Exception as e:
                self._mainloop._exc_info = sys.exc_info()
            return False

        def cancel(self):
            GLib.source_remove(self._source)
            del self._func
                                       
    def add_timeout(self, timeout, func, desc=None):
        return self._glib_timeout(self, timeout, func, desc)

if GLib is None:
    GLibMainLoop = None
