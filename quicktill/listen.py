import psycopg2
from sqlalchemy import text
import sqlalchemy.exc

import logging
log = logging.getLogger(__name__)

class db_listener:
    """Listen for notifictions delivered via the database

    Manages a list of channels and functions to be called when
    notifications are received on those channels.  Deals with
    disconnection from the database.  If unable to reconnect
    immediately, tries again later.
    """
    def __init__(self, mainloop, engine):
        self.connection = None
        self._mainloop = mainloop
        self._engine = engine
        self._fd_handle = None
        self._db_listening = set() # set up in the database
        self._listeners = {} # key is wrapper, value is channel

    class _listener:
        def __init__(self, db_listener, func, channel):
            self._db_listener = listener
            self._func = func
            self.channel = channel

        def cancel(self):
            del self._db_listener._listeners[self], self._func
            self._db_listener.update_listening_channels()

    def listen_for(self, channel, func):
        """Listen for a notification on a channel.

        Returns an object that can be used to cancel the listening.
        """
        wrapper = self._listener(self, func, channel)
        self._listeners[wrapper] = channel
        self.update_listening_channels()

    def update_listening_channels(self):
        wanted = set(self._listeners.values())
        if wanted and not self.connection:
            log.debug("connecting to database")
            try:
                self.connection = self._engine.connect()
            except sqlalchemy.exc.OperationalError:
                # Could not connect - database unreachable
                log.debug("could not connect")
                self._mainloop.add_timeout(
                    5, self.update_listening_channels,
                    "database listener connection retry")
                return
            self._db_listening = set()
            self._fd_handle = self._mainloop.add_fd(
                self.connection.connection.fileno(), self._data_available, None,
                "database notification listener")

        to_add = wanted - self._db_listening
        to_remove = self._db_listening - wanted
        for channel in to_add:
            log.debug("listen for %s", channel)
            self.connection.execute(
                text("LISTEN {};".format(channel))
                .execution_options(autocommit=True))
            self._db_listening.add(channel)
        for channel in to_remove:
            log.debug("stop listening for %s", channel)
            self.connection.execute(
                text("UNLISTEN {};".format(channel))
                .execution_options(autocommit=True))
            self._db_listening.discard(channel)
        if not self._db_listening:
            # We're not listening for anything any more - close the connection
            log.debug("close database connection")
            self._fd_handle.remove()
            self._fd_handle = None
            self.connection.close()
            self.connection = None

    def _data_available(self):
        try:
            self.connection.connection.poll()
        except psycopg2.OperationalError:
            log.debug("handling closed connection")
            # Unexpected close of connection - schedule retry
            self._fd_handle.remove()
            self._fd_handle = None
            self.connection = None
            self._mainloop.add_timeout(5, self.update_listening_channels,
                                       "database listener reopen closed")
            return
        while self.connection.connection.notifies:
            notify = self.connection.connection.notifies.pop()
            for listener, channel in self._listeners.items():
                if channel == notify.channel:
                    listener._func(notify.payload)

# listener is set to an instance of db_listener during quicktill
# initialisation but this ought to go somewhere else like
# tillconfig...
listener = None
