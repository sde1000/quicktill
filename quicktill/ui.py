# This module is the API for the display - the header line, clock,
# popup windows, and so on.

import time
import datetime
import sys
import textwrap
import traceback
from . import keyboard, tillconfig, td
from .td import func
import sqlalchemy.inspection
from decimal import Decimal

import logging
log = logging.getLogger(__name__)

class colourpair:
    """A pair of colours to be used for rendering text
    """
    all_colourpairs = []
    def __init__(self, name, foreground, background):
        self.name = name
        self.foreground = foreground
        self.background = background
        self.all_colourpairs.append(self)

    @property
    def reversed(self):
        if hasattr(self, '_reversed'):
            return self._reversed
        self._reversed = colourpair(self.name + "_reversed", self.background,
                                    self.foreground)
        self._reversed._reversed = self
        return self._reversed

colour_default = colourpair("header", "white", "black")
colour_header = colourpair("header", "white", "red")
colour_error = colourpair("error", "white", "red")
colour_toast = colourpair("toast", "white", "red")
colour_info = colourpair("info", "black", "green")
colour_input = colourpair("input", "white", "blue")
colour_line = colourpair("line", "black", "yellow")
colour_cashline = colourpair("cashline", "green", "black")
colour_changeline = colourpair("changeline", "yellow", "black")
colour_cancelline = colourpair("cancelline", "blue", "black")
colour_confirm = colourpair("confirm", "black", "cyan")

# The display system root window, and access to the header/clock/title bar
rootwin = None

def formattime(ts):
    "Returns ts formatted as %Y-%m-%d %H:%M:%S"
    if ts is None:
        return ""
    return ts.strftime("%Y-%m-%d %H:%M:%S")

def formatdate(ts):
    "Returns ts formatted as %Y-%m-%d"
    if ts is None:
        return ""
    return ts.strftime("%Y-%m-%d")

def handle_keyboard_input(k):
    """Deal with input from the user

    We can be passed a variety of things as keyboard input:

    keycode objects from keyboard.py
    strings
    user tokens

    They don't always have a 'keycap' method - check the type first!

    This function must be called within an ORM session.  It's ok to
    call this function recursively (eg. to synthesise a keypress from
    an on-screen button).
    """
    log.debug("Keypress %s", k)
    basicwin._focus.hotkeypress(k)

# Keypresses are passed to each filter in this stack in order.
keyboard_filter_stack = []

def handle_raw_keyboard_input(k):
    """Deal with input from the user

    This input is passed through the keyboard filter stack before
    being passed on to the handle_keyboard_input() function.  The
    filter stack will typically recognise sequences (eg. "[A01]") and
    convert them into keycode objects.
    """
    input = [k]

    for f in keyboard_filter_stack:
        input = f(input)

    for k in input:
        with td.orm_session():
            handle_keyboard_input(k)

def current_user():
    """Return the current user

    Look up the focus stack and return the first user information
    found, or None if there is none.
    """
    stack = basicwin._focus.parents()
    for i in stack:
        if hasattr(i, 'user'):
            return i.user

class _toastmaster:
    """Display brief messages to the user

    Manages a queue of messages to be displayed to the user without
    affecting the input focus.  A single instance of this object is
    created during UI initialisation.
    """
    # How long to display messages for, in seconds
    toast_display_time = 3
    # Gap between messages, in seconds
    inter_toast_time = 0.5

    def __init__(self):
        self.messagequeue = []
        self.current_message = None
        self.display_initialised = False

    def toast(self, message):
        """Display the message to the user.

        If an identical message is already in the queue of messages,
        don't add it.  If an identical message is already being
        displayed, reset the timeout to the default so the message
        continues to be displayed.
        """
        if message in self.messagequeue:
            return
        if not self.display_initialised:
            self.messagequeue.append(message)
            return
        if message == self.current_message:
            # Cancel the current timeout and reset for the full
            # default message display time
            self.timeout_handle.cancel()
            self.timeout_handle = tillconfig.mainloop.add_timeout(
                self.toast_display_time, self.alarm)
            return
        if self.current_message or self.messagequeue:
            self.messagequeue.append(message)
        else:
            self.start_display(message)

    def notify_display_initialised(self):
        self.display_initialised = True
        if self.messagequeue:
            self.alarm()

    def start_display(self, message):
        # Ensure that we do not attempt to display a toast (for example, an
        # error log entry from an exception caught at the top level of the
        # application) if the display system has already been deinitialised.
        if rootwin.isendwin():
            return
        self.current_message = message
        # Schedule removing the message from the display
        self.timeout_handle = tillconfig.mainloop.add_timeout(
            self.toast_display_time, self.alarm)
        # Work out where to put the window.  We're aiming for about
        # 2/3 of the screen width, around 1/3 of the way up
        # vertically.  If a toast ends up particularly high, make sure
        # we always have at least one blank line at the bottom of the
        # screen.
        mh, mw = rootwin.size()
        w = min((mw * 2) // 3, len(message))
        lines = textwrap.wrap(message, w)
        w = max(len(l) for l in lines) + 4
        h = len(lines) + 2
        y = (mh * 2) // 3 - (h // 2)
        if y + h + 1 >= mh:
            y = mh - h - 1
        try:
            self.win = rootwin.new(
                h, w, y, "center",
                colour=colour_toast, always_on_top=True)
        except:
            return self.start_display("(toast too long)")
        y = 1
        for l in lines:
            self.win.addstr(y, 2, l)
            y = y + 1
        # Flush this to the display immediately; sometimes toasts are
        # added just before starting a lengthy / potentially blocking
        # operation, and if the timer expires before the operation
        # completes the toast will never be seen.
        rootwin.flush()

    def alarm(self):
        if self.current_message:
            # Stop display of message
            self.current_message = None
            self.win.destroy()
            del self.win
            # If there's another waiting, schedule its display
            if self.messagequeue:
                tillconfig.mainloop.add_timeout(
                    self.inter_toast_time, self.alarm)
        else:
            self.start_display(self.messagequeue.pop(0))

toaster = _toastmaster()

def toast(message):
    """Display a message briefly to the user

    Does not affect the input focus.
    """
    toaster.toast(message)

class ignore_hotkeys:
    """Mixin class for UI elements that disables handling of hotkeys

    Hotkeys are not ignored, they are passed to the input focus like
    all other keypresses.
    """
    def hotkeypress(self, k):
        basicwin._focus.keypress(k)

class basicwin:
    """Base class for all pages, popup windows and fields.

    It is required that the parent holds the input focus whenever a
    basicwin instance is created.
    """
    _focus = None

    def __init__(self):
        self.parent = basicwin._focus
        log.debug("New %s with parent %s", self, self.parent)

    @property
    def focused(self):
        """Do we hold the focus at the moment?
        """
        return basicwin._focus == self

    def focus(self):
        """Called when we are being told to take the focus.
        """
        if basicwin._focus != self:
            oldfocus = basicwin._focus
            basicwin._focus = self
            oldfocus.defocus()
            log.debug("Focus %s -> %s", oldfocus, self)

    def defocus(self):
        """Called after we have lost the input focus.
        """
        pass

    def parents(self):
        if self.parent == self:
            return [self]
        return [self] + self.parent.parents()

    def keypress(self, k):
        pass

    def hotkeypress(self, k):
        """High priority keypress handling

        We get to look at keypress events before anything else does.
        If we don't do anything with this keypress we are required to
        pass it on to our parent.
        """
        self.parent.hotkeypress(k)

class basicpage(basicwin):
    _pagelist = []
    _basepage = None

    def __init__(self):
        """Create a new page.

        Create a new page.  This function should be called at
        the start of the __init__ function of any subclass.

        Newly-created pages are always selected.
        """
        # We need to deselect any current page first.
        if basicpage._basepage:
            basicpage._basepage.deselect()
        self.win = rootwin.new("page", "max", "page", 0)
        # XXX In the past, self.win was a native ncurses window object
        # and we had to use a wrapper for addstr to deal with
        # character encodings.  Now self.win is a python object with
        # its own addstr method; copying it here is redundant and done
        # only for compatibility with code that hasn't been updated
        # yet
        self.addstr = self.win.addstr
        basicpage._pagelist.append(self)
        self.h, self.w = self.win.size()
        self.savedfocus = self
        self.stack = None
        basicpage._basepage = self
        basicwin._focus = self
        super().__init__() # Sets self.parent to self - ok!

    def pagename(self):
        return "Basic page"

    def pagesummary(self):
        return ""

    def select(self):
        if basicpage._basepage == self:
            return # Nothing to do
        # Tell the current page we're switching away
        if basicpage._basepage:
            basicpage._basepage.deselect()
        basicpage._basepage = self
        basicwin._focus = self.savedfocus
        self.savedfocus = None
        self.stack.restore()
        self.stack = None
        self.updateheader()

    def deselect(self):
        """Deselect this page.

        Deselect this page if it is currently selected.  Save the
        panel stack so we can restore it next time we are selected.
        """
        if basicpage._basepage != self:
            return
        self.savedfocus = basicwin._focus
        self.stack = self.win.save_stack()
        basicpage._basepage = None
        basicwin._focus = None

    def dismiss(self):
        """Remove this page."""
        if basicpage._basepage == self:
            self.deselect()
        self.win.destroy()
        del self.win, self.stack
        basicpage._pagelist.remove(self)

    @staticmethod
    def updateheader():
        m = ""
        s = ""
        for i in basicpage._pagelist:
            if i == basicpage._basepage:
                m = i.pagename() + ' '
            else:
                ps = i.pagesummary()
                if ps:
                    s = s + i.pagesummary() + ' '
        rootwin.update_header(m, s)

    @staticmethod
    def _ensure_page_exists():
        if basicpage._basepage == None:
            with td.orm_session():
                tillconfig.firstpage()

    def hotkeypress(self, k):
        """High priority keypress processing

        Since this is a page, it is always at the base of the stack of
        windows - it does not have a parent to pass keypresses on to.
        By default we look at the configured hotkeys and call if
        found; otherwise we pass the keypress on to the current input
        focus (if it exists) for regular keypress processing.

        If there is no current input focus then one will be set in
        _ensure_page_exists() the next time around the event loop.
        """
        if k in tillconfig.hotkeys:
            tillconfig.hotkeys[k]()
        elif hasattr(k, 'usertoken'):
            tillconfig.usertoken_handler(k)
        else:
            if basicwin._focus:
                basicwin._focus.keypress(k)

class basicpopup(basicwin):
    """A popup window

    Appears in the center of the screen.  Draws a title at the
    top-left of the window and optionally a "clear" prompt at the
    bottom-right.

    Accepts a dictionary of {keyboard input: action} for handling
    incoming keypresses.  Any unhandled keypresses result in a beep.
    """
    def __init__(self, h, w, title=None, cleartext=None, colour=colour_error,
                 keymap={}):
        super().__init__()
        # Grab the focus so that we hold it while we create any necessary
        # child UI elements
        self.focus()
        self.keymap = keymap
        mh, mw = rootwin.size()
        if title:
            w = max(w, len(title) + 3)
        if cleartext:
            w = max(w, len(cleartext) + 3)
        w = min(w, mw)
        h = min(h, mh)
        self.win = rootwin.new(h, w, "center", "center", colour=colour)
        # XXX In the past, self.win was a native ncurses window object
        # and we had to use a wrapper for addstr to deal with
        # character encodings.  Now self.win is a python object with
        # its own addstr method; copying it here is redundant and done
        # only for compatibility with code that hasn't been updated
        # yet
        self.addstr = self.win.addstr
        self.win.border(title, cleartext)

    def dismiss(self):
        self.parent.focus()
        self.win.destroy()
        del self.win

    def keypress(self, k):
        # We never want to pass unhandled keypresses back to the parent
        # of the popup.
        if k in self.keymap:
            i = self.keymap[k]
            if len(i) > 2 and i[2]:
                if i[2]:
                    self.dismiss()
            if i[0] is not None:
                if len(i) > 1 and i[1] is not None:
                    i[0](*i[1])
                else:
                    i[0]()
        else:
            beep()

class dismisspopup(basicpopup):
    """A popup window with implicit handling of a "dismiss" key

    Adds optional processing of an implicit 'Dismiss' key and
    generation of the cleartext prompt from the keycap.
    """
    def __init__(self, h, w, title=None, cleartext=None, colour=colour_error,
                 dismiss=keyboard.K_CLEAR, keymap={}):
        self.dismisskey = dismiss
        super().__init__(h, w, title=title,
                         cleartext=self.get_cleartext(cleartext, dismiss),
                         colour=colour, keymap=keymap)

    def get_cleartext(self, cleartext, dismiss):
        if cleartext is None:
            if dismiss == keyboard.K_CLEAR:
                return "Press Clear to go back"
            elif dismiss == keyboard.K_CASH:
                return "Press Cash/Enter to continue"
            elif dismiss is None:
                return None
            else:
                return "Press {} to dismiss".format(dismiss.keycap)
        return cleartext

    def keypress(self, k):
        if self.dismisskey and k == self.dismisskey:
            return self.dismiss()
        super().keypress(k)

class listpopup(dismisspopup):
    """A popup window with a scrollable list of items

    A popup window with an initial non-scrolling header, and then a
    scrollable list of selections.  Items in the list and header can
    be strings, or any subclass of emptyline().  The header is not
    used when deciding how wide the window will be.
    """
    def __init__(self, linelist, default=0, header=None, title=None,
                 show_cursor=True, dismiss=keyboard.K_CLEAR,
                 cleartext=None, colour=colour_input, w=None, keymap={}):
        dl = [x if isinstance(x, emptyline) else line(x, colour=colour)
              for x in linelist]
        hl = [x if isinstance(x, emptyline) else marginline(
            lrline(x, colour=colour), margin=1)
              for x in header] if header else []
        if w is None:
            w = max((x.idealwidth() for x in dl)) + 2 if len(dl) > 0 else 0
            w = max(25, w)
        if title is not None:
            w = max(len(title) + 3, w)
        # We know that the created window will not be wider than the
        # width of the screen.
        mh, mw = rootwin.size()
        w = min(w, mw)
        h = sum(len(x.display(w - 2)) for x in hl + dl) + 2
        super().__init__(h, w, title=title, colour=colour, keymap=keymap,
                         dismiss=dismiss, cleartext=cleartext)
        self.win.set_cursor(False)
        h, w = self.win.size()
        y = 1
        for hd in hl:
            l = hd.display(w - 2)
            for i in l:
                self.win.addstr(y, 1, i)
                y = y + 1
        # Note about keyboard handling: the scrollable will always have
        # the focus.  It will deal with cursor keys itself.  All other
        # keys will be passed through to our keypress() method, which
        # may well be overridden in a subclass.  We expect subclasses to
        # implement keypress() themselves, and access the methods of the
        # scrollable directly.  If there's no scrollable this will fail!
        if len(linelist) > 0:
            log.debug("listpopup scrollable %d %d %d %d",
                      y, 1, w - 2, h - y - 1)
            self.s = scrollable(y, 1, w - 2, h - y - 1, dl,
                                show_cursor=show_cursor)
            self.s.cursor = default if default is not None else 0
            self.s.focus()
        else:
            self.s = None

class infopopup(listpopup):
    """A pop-up box that formats and displays text.

    The text parameter is a list of paragraphs.
    """
    # Implementation note: we _could_ use a scrollable with a list of
    # lrlines; however, we have to work out how big to make the window
    # anyway, and once we've done that we already have a list of lines
    # suitable to pass to listpopup.__init__()
    def __init__(self, text=[], title=None, dismiss=keyboard.K_CLEAR,
                 cleartext=None, colour=colour_error, keymap={}):
        cleartext = self.get_cleartext(cleartext, dismiss)
        mh, mw = rootwin.size()
        maxw = mw - 4
        maxh = mh - 5
        # We want the window to end up as close to 2/3 the maximum width
        # as possible.  Try that first, and only let it go wider if the
        # maximum height is exceeded.
        w = (maxw * 2) // 3
        if cleartext:
            w = max(w, len(cleartext) - 1)
        def formatat(width):
            r = []
            for i in text:
                if i == "":
                    r.append("")
                else:
                    for j in textwrap.wrap(i, width):
                        r.append(j)
            return r
        t = formatat(w)
        while len(t) > maxh and w < maxw:
            w = w + 1
            t = formatat(w)
        t = [emptyline()] \
            + [marginline(line(x), margin=1) for x in t] \
            + [emptyline()]
        super().__init__(t, title=title, dismiss=dismiss,
                         cleartext=cleartext, colour=colour, keymap=keymap,
                         show_cursor=False, w=w + 4)

class alarmpopup(infopopup):
    """An annoying infopopup

    This is like an infopopup, but goes "beep" every second until it
    is dismissed.  It dismisses itself after 5 minutes, provided it
    still has the input focus.  (If it doesn't have the focus,
    dismissing would put the focus in the wrong place - potentially on
    a different page, which would be VERY confusing for the user!)
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dismiss_at = time.time() + 300
        self.alarm()

    def alarm(self):
        beep()
        if time.time() >= self.dismiss_at:
            if self in basicwin._focus.parents():
                self._alarmhandle = None
                self.dismiss()
        else:
            self._alarmhandle = tillconfig.mainloop.add_timeout(
                1, self.alarm, desc="alarmpopup")

    def dismiss(self):
        if self._alarmhandle:
            self._alarmhandle.cancel()
        super().dismiss()

def validate_int(s, c):
    if s == '-':
        return s
    try:
        int(s)
    except:
        return None
    return s

def validate_positive_nonzero_int(s, c):
    try:
        x = int(s)
        if x < 1:
            return None
    except:
        return None
    return s

def validate_float(s, c):
    if s == '-':
        return s
    try:
        float(s)
    except:
        return None
    return s

def validate_positive_float(s, c):
    try:
        x = float(s)
        if x < 0.0:
            return None
    except:
        return None
    return s

class label(basicwin):
    """An area of a window that has a value that can be changed.
    """
    def __init__(self, y, x, w, contents="", align="<", colour=None):
        super().__init__()
        self.win = self.parent.win
        self._y = y
        self._x = x
        self._format = "%s%d.%d" % (align, w, w)
        self.set(contents, colour=colour)

    def set(self, contents, colour=None):
        y, x = self.win.getyx()
        self.win.addstr(self._y, self._x,
                        format(str(contents), self._format), colour)
        self.win.move(y, x)

class field(basicwin):
    """A field inside a window.

    Able to receive the input focus, and knows how to pass it on to
    peer fields.
    """
    def __init__(self, keymap={}):
        self.nextfield = None
        self.prevfield = None
        # We _must_ copy the provided keymap; it is permissible for our
        # keymap to be modified after initialisation, and it would be
        # a Very Bad Thing (TM) for the default empty keymap to be
        # changed!
        self.keymap = keymap.copy()
        super().__init__()
        self.win = self.parent.win

    def keypress(self, k):
        # All keypresses handled here are defaults; if they are present
        # in the keymap, we should not handle them ourselves.
        if k in self.keymap:
            i = self.keymap[k]
            if i[0] is not None:
                if i[1] is None:
                    i[0]()
                else:
                    i[0](*i[1])
        elif (k in (keyboard.K_DOWN, keyboard.K_CASH, keyboard.K_TAB)
              and self.nextfield):
            self.nextfield.focus()
        elif (k in (keyboard.K_UP,keyboard.K_CLEAR)
              and self.prevfield):
            self.prevfield.focus()
        else:
            self.parent.keypress(k)

class valuefield(field):
    """A field that can have a variable value.

    Use the set() method to set the value and the read() method to
    read it.  Accessing the value as the "f" property may work for
    some fields, but is deprecated.  Some valuefields may support the
    value being changed directly by the user.

    Set the "sethook" attribute to receive a callback when the value
    is changed.
    """
    def __init__(self, keymap={}, f=None):
        super().__init__(keymap)
        self.sethook = lambda: None
        self.set(f)

    def set(self, value):
        """Set field value.

        If you completely override this method, remember to call
        sethook() after changing the value!
        """
        self._f = f
        self.sethook()

    def setf(self, value):
        """Set value and move to next field"""
        self.set(value)
        if self.nextfield:
            self.nextfield.focus()

    def read(self):
        return self._f

class scrollable(field):
    """A rectangular field of a page or popup that contains a list of
    items that can be scrolled up and down.

    lastline is a special item that, if present, is drawn at the end of
    the list.  In the register this is the prompt/input buffer/total.
    Where the scrollable is being used for entry of a list of items,
    the last line may be blank/inverse as a prompt.

    self.cursor is the index into dl that is highlighted as the
    current position.  If "lastline" is selected, self.cursor is at
    len(self.dl).  If dl is empty and lastline is not present,
    self.cursor is set to None.
    """
    def __init__(self, y, x, width, height, dl, show_cursor=True,
                 lastline=None, default=0, keymap={}):
        super().__init__(keymap)
        self.y = y
        self.x = x
        self.w = width
        self.h = height
        self.show_cursor = show_cursor
        self.lastline = lastline
        self.cursor = default
        self.top = 0
        self.set(dl)

    def set(self, dl):
        self.dl = dl
        # self.sethook()  - not used by anything, but should it work?
        self.redraw() # Does implicit set_cursor()

    def set_cursor(self, c):
        if len(self.dl) == 0 and not self.lastline:
            self.cursor = None
            return
        if c is None or c < 0:
            c = 0
        last_valid_cursor = len(self.dl) if self.lastline else len(self.dl) - 1
        if c > last_valid_cursor:
            c = last_valid_cursor
        self.cursor = c

    def focus(self):
        # If we are obtaining the focus from the previous field, we should
        # move the cursor to the top.  If we are obtaining it from the next
        # field, we should move the cursor to the bottom.  Otherwise we
        # leave the cursor untouched.
        if self.prevfield and self.prevfield.focused:
            self.set_cursor(0)
        elif self.nextfield and self.nextfield.focused:
            self.set_cursor(len(self.dl))
        super().focus()
        self.redraw()

    def defocus(self):
        super().defocus()
        self.drawdl() # We don't want to scroll

    def drawdl(self, display=True):
        """Draw the scrollable contents

        Redraw the area with the current scroll and cursor locations.
        Returns the index of the last complete item that fits on the
        screen.  (This is useful to compare against the cursor
        position to ensure the cursor is displayed.)

        If display is set to False, don't actually draw anything; just
        work out and return the index of the last complete item.
        """
        # First clear the drawing space
        if display:
            self.win.clear(self.y, self.x, self.h, self.w)

        # Special case: if top is 1 and cursor is 1 and the first item
        # in the list is exactly one line high, we can set top to zero
        # so that the first line is displayed.  Only worthwhile if we
        # are actually displaying a cursor.
        if self.top == 1 and self.cursor == 1 and self.show_cursor:
            if len(self.dl[0].display(self.w)) == 1:
                self.top = 0
        # self.dl may have shrunk since last time self.top was set;
        # make sure self.top is in bounds
        if self.top > len(self.dl):
            self.top = len(self.dl)
        y = self.y
        i = self.top
        lastcomplete = i
        if i > 0:
            if display:
                self.win.addstr(y, self.x, '...')
            y = y + 1
        cursor_y = None
        end_of_displaylist = len(self.dl) + 1 if self.lastline else len(self.dl)
        while i < end_of_displaylist:
            if i >= len(self.dl):
                item = self.lastline
            else:
                item = self.dl[i]
            if item is None:
                break
            l = item.display(self.w)
            colour = item.colour if item.colour else self.win.colour
            ccolour = item.cursor_colour if item.cursor_colour \
                      else self.win.colour.reversed
            if self.focused and i == self.cursor and self.show_cursor:
                colour = ccolour
                cursor_y = y + item.cursor[1]
                cursor_x = self.x + item.cursor[0]
            for j in l:
                if y < (self.y + self.h):
                    if display:
                        self.win.addstr(
                            y, self.x, "%s%s" % (
                                j, ' ' * (self.w - len(j))), colour)
                y = y + 1
            if y <= (self.y + self.h):
                lastcomplete = i
            else:
                break
            i = i + 1
        if end_of_displaylist > i:
            # Check whether we are about to overwrite any of the last item
            if y >= self.y + self.h + 1:
                lastcomplete = lastcomplete - 1
            if display:
                self.win.addstr(
                    self.y + self.h - 1, self.x, '...' + ' ' * (self.w - 3))
        if cursor_y is not None and cursor_y < (self.y + self.h):
            if display:
                self.win.move(cursor_y, cursor_x)
        return lastcomplete

    def redraw(self):
        """Draw the scrollable, ensuring the cursor is visible

        Updates the field, scrolling until the cursor is visible.  If we
        are not showing the cursor, the top line of the field is always
        the cursor line.
        """
        self.set_cursor(self.cursor)
        if self.cursor is None:
            self.top = 0
        elif self.cursor < self.top or self.show_cursor == False:
            self.top = self.cursor
        end_of_displaylist = len(self.dl) + 1 if self.lastline else len(self.dl)
        lastitem = self.drawdl(display=False)
        while self.cursor is not None and self.cursor > lastitem:
            self.top = self.top + 1
            lastitem = self.drawdl(display=False)
        lastitem = self.drawdl()
        self.display_complete = (lastitem == end_of_displaylist - 1)

    def cursor_at_start(self):
        if self.cursor is None:
            return True
        return self.cursor == 0

    def cursor_at_end(self):
        if self.cursor is None:
            return True
        if self.show_cursor:
            if self.lastline:
                return self.cursor >= len(self.dl)
            else:
                return self.cursor == len(self.dl) - 1 or len(self.dl) == 0
        else:
            return self.display_complete

    def cursor_on_lastline(self):
        return self.cursor == len(self.dl)

    def cursor_up(self, n=1):
        if self.cursor_at_start():
            if self.prevfield is not None and self.focused:
                return self.prevfield.focus()
        else:
            self.set_cursor(self.cursor - n)
        self.redraw()

    def cursor_down(self, n=1):
        if self.cursor_at_end():
            if self.nextfield is not None and self.focused:
                return self.nextfield.focus()
        else:
            self.set_cursor(self.cursor + n)
        self.redraw()

    def keypress(self, k):
        if k == keyboard.K_DOWN:
            self.cursor_down(1)
        elif k == keyboard.K_UP:
            self.cursor_up(1)
        elif k == keyboard.K_RIGHT:
            self.cursor_down(5)
        elif k == keyboard.K_LEFT:
            self.cursor_up(5)
        elif k == keyboard.K_PAGEDOWN:
            self.cursor_down(10)
        elif k == keyboard.K_PAGEUP:
            self.cursor_up(10)
        else:
            super().keypress(k)

class emptyline:
    """A line for use in a scrollable.

    Has a natural colour and a "cursor is here" colour.  This line has
    no text.
    """
    def __init__(self, colour=None, userdata=None):
        self.colour = colour
        self.cursor_colour = colour.reversed if colour else None
        self.userdata = userdata

    def update(self):
        pass

    def idealwidth(self):
        return 0

    def display(self, width):
        """Return the lines needed to display this line
        """
        # After display has been called, the caller can read 'cursor' to
        # find our preferred location for the cursor if we are selected.
        # It's a (x,y) tuple where y is 0 for the first line.
        self.cursor = (0, 0)
        return [""]

class emptylines(emptyline):
    def __init__(self, colour=None, lines=1, userdata=None):
        super().__init__(colour, userdata)
        self.lines = lines

    def display(self, width):
        self.cursor = (0, 0)
        return [""] * self.lines

class line(emptyline):
    """A line for use in a scrollable.

    Has a natural colour, a "cursor is here" colour, and some text.
    If either colour is None, the colour of the underlying window will
    be used instead.  If the text is too long it will be truncated;
    this line will never wrap.
    """
    def __init__(self, text="", colour=None, userdata=None):
        super().__init__(colour, userdata)
        self.text = text

    def idealwidth(self):
        return len(self.text)

    def display(self, width):
        """Return the lines needed to display this line at the specified width

        Returns a list of lines (of length 1), truncated to the
        specified maximum width.
        """
        # After display has been called, the caller can read 'cursor' to
        # find our preferred location for the cursor if we are selected.
        # It's a (x,y) tuple where y is 0 for the first line.
        self.cursor = (0, 0)
        return [self.text[:width]]

class marginline(emptyline):
    """Indent another line with a margin at the left and right.

    Colour is taken from the line to be indented.
    """
    def __init__(self, l, margin=0):
        super().__init__(l.colour, l.userdata)
        self.l = l
        self.margin = margin

    def idealwidth(self):
        return self.l.idealwidth() + (2 * self.margin)

    def display(self, width):
        m = ' ' * self.margin
        ll = [m + x + m for x in self.l.display(width - (2 * self.margin))]
        cursor = (self.l.cursor[0] + self.margin, self.l.cursor[1])
        return ll

class lrline(emptyline):
    """A line for use in a scrollable.

    Has a natural colour, a "cursor is here" colour, an optional
    "selected" colour, some left-aligned text (which will be wrapped
    if it is too long) and optionally some right-aligned text.
    """
    def __init__(self, ltext="", rtext="", colour=None, userdata=None):
        super().__init__(colour, userdata)
        self.ltext = ltext
        self.rtext = rtext
        self._outputs = {}

    def update(self):
        super().update()
        self._outputs = {}

    def idealwidth(self):
        return len(self.ltext) + (
            len(self.rtext) + 1 if len(self.rtext) > 0 else 0)

    def display(self, width):
        """Format for display at the specified width

        Returns a list of lines, formatted to the specified maximum
        width.  If there is right-aligned text it is included along
        with the text on the last line if there is space; otherwise a
        new line is added with the text at the right.
        """
        # After display has been called, the caller can read 'cursor' to
        # find our preferred location for the cursor if we are selected.
        # It's a (x, y) tuple where y is 0 for the first line.
        self.cursor = (0, 0)
        if width in self._outputs:
            return self._outputs[width]
        w = []
        for l in self.ltext.splitlines():
            if l:
                w = w + textwrap.wrap(l, width)
            else:
                w = w + [""]
        if len(w) == 0:
            w = [""]
        if len(w[-1]) + len(self.rtext) >= width:
            w.append("")
        w[-1] = w[-1] + (' ' * (width - len(w[-1]) - len(self.rtext))) \
                + self.rtext
        self._outputs[width] = w
        return w

class tableformatter:
    """Format a table.

    This class implements policy for formatting a table.  The format
    string is used as-is with the following characters being replaced:

    l - left-aligned field
    c - centered field
    r - right-aligned field
    p - padding
    upper-case L, C or R - field that may have its contents
      truncated so the other fields fit.
    """
    def __init__(self, format):
        self._f = format
        self._rows = [] # Doesn't need to be kept in order
        self._formats = {}
        self._colwidths = None
        # Remove the formatting characters from the format and see
        # what's left
        f = self._f
        f = f.replace('l', '')
        f = f.replace('L', '')
        f = f.replace('c', '')
        f = f.replace('C', '')
        f = f.replace('r', '')
        f = f.replace('R', '')
        f = f.replace('p', '')
        self._formatlen = len(f)

    def __call__(self, *args, **kwargs):
        """Append a row to the table.

        Positional arguments are used as table fields, and keyword
        arguments are passed to the underlying line object eg. for
        colour and userdata.
        """
        row = _tableline(self, args, **kwargs)
        self._rows.append(row)
        self._update(row)
        return row

    def _update(self, row):
        """Call when a row has been changed.

        Called when a row is changed.  Invalidate any cached widths
        and format strings.
        """
        self._formats = {}
        self._colwidths = None

    @property
    def colwidths(self):
        """List of column widths.
        """
        if not self._colwidths:
            # Each row has a list of fields.  We want to rearrange
            # this so we have a list of columns.
            cols = zip(*(r.fields for r in self._rows))
            self._colwidths = [max(len(f) for f in c) for c in cols]
        return self._colwidths

    def idealwidth(self):
        return self._formatlen + sum(self.colwidths)

    def _formatstr(self, width):
        """Return a format template for the given width.
        """
        if width in self._formats:
            return self._formats[width]
        w = list(self.colwidths) # copy
        r = []
        pads = self._f.count("p")
        if pads > 0:
            total_to_pad = max(0, width - self.idealwidth())
            pw = total_to_pad // pads
            odd = total_to_pad % pads
            pads = [pw + 1] * odd + [pw] * (pads - odd)
        else:
            pads = []
        excess_width = max(0, self.idealwidth() - width)
        log.debug("tableformatter idealwidth=%s, width=%s, excess_width=%s",
                  self.idealwidth(), width, excess_width)
        truncates = self._f.count('L') + self._f.count('C') + self._f.count('R')
        for i in self._f:
            if i in ('l', 'L', 'c', 'C', 'r', 'R'):
                if i in ('l', 'L'):
                    align = "<"
                elif i in ('c', 'C'):
                    align = "^"
                else:
                    align = ">"
                colwidth = w.pop(0)
                if i in ('L', 'C', 'R'):
                    if excess_width > 0:
                        reduce_by = min(excess_width // truncates, colwidth)
                        colwidth -= reduce_by
                        excess_width -= reduce_by
                        truncates -= 1
                r.append("{:%s%d.%d}" % (align, colwidth, colwidth))
            elif i == "p":
                r.append(" " * pads.pop(0))
            else:
                r.append(i)
        fs = ''.join(r)
        self._formats[width] = fs
        return fs

    def format(self, row, width):
        return [self._formatstr(width).format(*row.fields)[:width]]

class _tableline(emptyline):
    """A line for use in a tableformatter table.

    Create instances of this by calling tableformatter instances.
    """
    def __init__(self, formatter, fields, colour=None, userdata=None):
        super().__init__(colour, userdata)
        self._formatter = formatter
        self.fields = [str(x) for x in fields]

    def update(self):
        super().update()
        self._formatter._update(self)

    def idealwidth(self):
        return self._formatter.idealwidth()

    def display(self, width):
        self.cursor = (0, 0)
        return self._formatter.format(self, width)

class menu(listpopup):
    """A popup menu with a list of selections.

    Selection can be made by using cursor keys to move up and down,
    and pressing Cash/Enter to confirm.

    itemlist is a list of (desc, func, args) tuples.  If desc is a
    string it will be converted to a line(); otherwise it is assumed
    to be some subclass of emptyline().
    """
    def __init__(self, itemlist, default=0,
                 blurb="Select a line and press Cash/Enter",
                 title=None,
                 colour=colour_input, w=None, dismiss_on_select=True,
                 keymap={}):
        self.itemlist = itemlist
        self.dismiss_on_select = dismiss_on_select
        dl = [x[0] for x in itemlist]
        if not isinstance(blurb, list):
            blurb = [blurb]
        super().__init__(dl, default=default,
                         header=blurb, title=title,
                         colour=colour, w=w, keymap=keymap)

    def keypress(self, k):
        if k == keyboard.K_CASH:
            if len(self.itemlist) > 0:
                i = self.itemlist[self.s.cursor]
                if self.dismiss_on_select:
                    self.dismiss()
                if i[2] is None:
                    i[1]()
                else:
                    i[1](*i[2])
        else:
            super().keypress(k)

class _keymenuline(emptyline):
    """A line for use in a keymenu.

    Used internally by keymenu.
    """
    def __init__(self, keymenu, keycode, desc, func, args):
        self._keymenu = keymenu
        colour = keymenu._colour
        if hasattr(func, "allowed"):
            if not func.allowed():
                colour = keymenu._not_allowed_colour
        self.colour = colour
        self.cursor_colour = self.colour
        self.prompt = " " + str(keycode) + ". "
        self.desc = desc if isinstance(desc, emptyline) else line(desc)

    def idealwidth(self):
        return self._keymenu.promptwidth + self.desc.idealwidth() + 1

    def display(self, width):
        self.cursor = (0, 0)
        dl = list(self.desc.display(width - self._keymenu.promptwidth))
        # First line is the prompt padded to promptwidth followed by
        # the first line of the description
        ll = [" " * (self._keymenu.promptwidth - len(self.prompt)) +
              self.prompt +
              dl.pop(0)]
        # Subsequent lines are an indentation of the width of the
        # prompt followed by the line of the description
        ll = ll + [" " * self._keymenu.promptwidth + x for x in dl]
        return ll

class keymenu(listpopup):
    """A popup menu with a list of selections.

    Selections are made by pressing the key associated with the
    selection.

    itemlist is a list of (key, desc, func, args) tuples.  If desc is
    a string it will be converted to a line(); otherwise it is assumed
    to be some subclass of emptyline().
    """
    def __init__(self, itemlist, blurb=[], title="Press a key",
                 colour=colour_input, w=None, dismiss_on_select=True,
                 blank_line_between_items=False):
        if not isinstance(blurb, list):
            blurb = [blurb]
        km = {}
        self._colour = colour
        self._not_allowed_colour = colour_error
        lines = [_keymenuline(self, *x) for x in itemlist]
        self.promptwidth = max(len(l.prompt) for l in lines)
        for keycode, desc, func, args in itemlist:
            km[keycode] = (func, args, dismiss_on_select)
        self.menukeys = km
        if blank_line_between_items:
            def yl(lines):
                for l in lines:
                    yield l
                    yield emptyline()
            lines = [emptyline()] + list(yl(lines))
        else:
            lines = [emptyline()] + lines + [emptyline()]
        super().__init__(lines,
                         header=blurb, title=title,
                         colour=colour, w=w, keymap=km, show_cursor=False)

def automenu(itemlist, spill="menu", **kwargs):
    """A popup menu with a list of selections.

    Pops up a dialog to choose an item from the itemlist, which
    consists of (desc, func, args) tuples.  If desc is a string it
    will be converted to a lrline().

    If the list is short enough then a keymenu will be used.
    Otherwise, if spill="menu" then a menu will be used; if
    spill="keymenu" (or anything else) the last option on the menu
    will bring up another keymenu containing the remaining items.
    """
    possible_keys = [
        "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
    ]
    itemlist = [(lrline(desc) if not isinstance(desc, emptyline) else desc,
                 func, args) for desc, func, args in itemlist]
    if spill == "menu" and len(itemlist) > len(possible_keys):
        return menu(itemlist, **kwargs)
    if len(itemlist) > len(possible_keys):
        remainder = itemlist[len(possible_keys) - 1 :]
        itemlist = itemlist[: len(possible_keys) - 1] + [
            ("More...", (lambda: automenu(
                remainder, spill="keymenu", **kwargs)), None)]
    return keymenu([(possible_keys.pop(0), desc, func, args)
                    for desc, func, args in itemlist], **kwargs)

class booleanfield(valuefield):
    """A field with boolean value.

    A field that can be either True or False, displayed as Yes or No.
    Also has an optional "blank" state which will be read back as
    None.
    """
    def __init__(self, y, x,
                 keymap={}, f=None, readonly=False, allow_blank=True):
        self.y = y
        self.x = x
        self.readonly = readonly
        self.allow_blank = allow_blank
        super().__init__(keymap, f)

    def focus(self):
        super().focus()
        self.draw()

    def set(self, l):
        self._f = l
        if not self.allow_blank:
            self._f = not not self._f
        self.sethook()
        self.draw()

    def draw(self):
        if self._f is None:
            s = "   "
        else:
            s = "Yes" if self._f else "No "
        pos = self.win.getyx()
        self.win.addstr(self.y, self.x, s, self.win.colour.reversed)
        if self.focused:
            self.win.move(self.y, self.x)
        else:
            self.win.move(*pos)

    def keypress(self, k):
        if k in ('y', 'Y', '1'):
            self.set(True)
        elif k in ('n', 'N', '0', '00'):
            self.set(False)
        elif k in (keyboard.K_LEFT, keyboard.K_RIGHT, ' ') \
             and self._f is not None:
            self.set(not self._f)
        elif k == keyboard.K_CLEAR and self.allow_blank and self._f is not None:
            self.set(None)
        else:
            super().keypress(k)
                
class editfield(valuefield):
    """Accept typed-in input in a field.

    Processes an implicit set of keycodes; when an unrecognised code
    is found processing moves to the standard keymap.

    Special parameters:

    f: the default contents

    flen: maximum length of the field

    validate: a function called on every insertion into the field.  It
    is passed the proposed new contents and the cursor index, and
    should return either a (potentially updated) string or None if the
    input is not allowed
    """
    def __init__(self, y, x, w, keymap={}, f=None, flen=None, validate=None,
                 readonly=False):
        self.y = y
        self.x = x
        self.w = w
        if flen is None:
            # XXX this doesn't allow for unlimited length fields.  It
            # should be changed so that if unspecified the maximum
            # length is the width, and if zero the maximum length is
            # unlimited
            flen = w
        self.flen = flen
        self.validate = validate
        self.readonly = readonly
        super().__init__(keymap, f)

    # Internal attributes:
    # c - cursor position
    # i - amount by which contents have scrolled left to fit width
    # _f - current contents

    @property
    def f(self):
        return self.read()

    def focus(self):
        super().focus()
        if self.c > len(self._f):
            self.c = len(self._f)
        self.draw()

    def set(self, l):
        if l is None:
            l = ""
        l = str(l)
        if len(l) > self.flen:
            l = l[:self.flen]
        self._f = l
        self.c = len(self._f)
        self.i = 0 # will be updated by draw() if necessary
        self.sethook()
        self.draw()

    def draw(self):
        pos = self.win.getyx()
        if self.c - self.i > self.w:
            self.i = self.c - self.w
        if self.c < self.i:
            self.i = self.c
        self.win.addstr(self.y, self.x, ' ' * self.w,
                        self.win.colour.reversed)
        self.win.addstr(self.y, self.x, self._f[self.i : self.i + self.w],
                        self.win.colour.reversed)
        if self.focused:
            self.win.move(self.y, self.x + self.c - self.i)
        else:
            self.win.move(*pos)

    def insert(self, s):
        if self.readonly:
            beep()
            return
        trial = self._f[:self.c] + s + self._f[self.c:]
        if self.validate:
            trial = self.validate(trial, self.c)
        if trial is not None and len(trial) > self.flen:
            trial = None
        if trial is not None:
            self._f = trial
            self.c = self.c + len(s)
            if self.c > len(self._f):
                self.c = len(self._f)
            self.sethook()
            self.draw()
        else:
            beep()

    def backspace(self):
        "Delete the character to the left of the cursor"
        if self.c > 0 and not self.readonly:
            self._f = self._f[:self.c - 1] + self._f[self.c:]
            self.move_left()
            self.sethook()
            self.draw()
        else:
            beep()

    def delete(self):
        "Delete the character under the cursor"
        if self.c < len(self._f) and not self.readonly:
            self._f = self._f[:self.c] + self._f[self.c + 1:]
            self.sethook()
            self.draw()
        else:
            beep()

    def move_left(self):
        if self.c == 0:
            beep()
        self.c = max(self.c - 1, 0)
        self.draw()

    def move_right(self):
        if self.c == len(self._f):
            beep()
        self.c = min(self.c + 1, len(self._f))
        self.draw()

    def home(self):
        self.c = 0
        self.draw()

    def end(self):
        self.c = len(self._f)
        self.draw()

    def clear(self):
        editfield.set(self, "")

    def killtoeol(self):
        if self.readonly:
            beep()
            return
        self._f = self._f[:self.c]
        self.sethook()
        self.draw()

    def keypress(self, k):
        if isinstance(k, str):
            self.insert(k)
        elif k == keyboard.K_BACKSPACE:
            self.backspace()
        elif k == keyboard.K_DEL:
            self.delete()
        elif k == keyboard.K_LEFT:
            self.move_left()
        elif k == keyboard.K_RIGHT:
            self.move_right()
        elif k == keyboard.K_HOME:
            self.home()
        elif k == keyboard.K_END:
            self.end()
        elif k == keyboard.K_EOL:
            self.killtoeol()
        elif k == keyboard.K_CLEAR and self._f != "" and not self.readonly:
            self.clear()
        else:
            super().keypress(k)

class datefield(editfield):
    """A field for entry of dates

    The f attribute is a valid date or None
    """
    def __init__(self, y, x, keymap={}, f=None, readonly=False):
        if f is not None:
            f = formatdate(f)
        super().__init__(y, x, 10, keymap=keymap, f=f, flen=10,
                         readonly=readonly, validate=self.validate_date)

    @staticmethod
    def validate_date(s, c):
        def checkdigit(i):
            a = s[i : i + 1]
            if len(a) == 0:
                return True
            return a.isdigit()
        def checkdash(i):
            a = s[i : i + 1]
            if len(a) == 0:
                return True
            return a == '-'
        if (checkdigit(0) and
            checkdigit(1) and
            checkdigit(2) and
            checkdigit(3) and
            checkdash(4) and
            checkdigit(5) and
            checkdigit(6) and
            checkdash(7) and
            checkdigit(8) and
            checkdigit(9)):
            return s
        return None

    def set(self, v):
        if hasattr(v, 'strftime'):
            super().set(formatdate(v))
        else:
            super().set(v)

    def read(self):
        try:
            d = datetime.datetime.strptime(self._f,"%Y-%m-%d")
        except:
            d = None
        return d

    def draw(self):
        self.win.addstr(self.y, self.x, 'YYYY-MM-DD',
                        self.win.colour.reversed)
        self.win.addstr(self.y, self.x, self._f,
                        self.win.colour.reversed)
        self.win.move(self.y, self.x + self.c)

    def insert(self, s):
        super().insert(s)
        if len(self._f) == 4 or len(self._f) == 7:
            self.set(self._f + '-')

class moneyfield(editfield):
    """A field that allows an amount of money to be entered

    The amount is in whole currency units, i.e. in the UK it will be
    pounds.pence rather than pounds*100+pence

    If a "note value" key is pressed, this auto-fills that amount into
    the field.
    """
    def __init__(self, y, x, w=6, default=""):
        super().__init__(y, x, w, validate=validate_float)
        self.set(default)

    def keypress(self, k):
        if hasattr(k, "notevalue"):
            self.set(str(k.notevalue))
            super().keypress(keyboard.K_CASH)
        else:
            super().keypress(k)

    def set(self, a):
        super().set(str(a))

    def read(self):
        try:
            a = Decimal(self._f)
        except:
            a = Decimal(0)
        return a

class modelfield(editfield):
    """A field that allows a model instance to be chosen

    The instance is chosen based on a string field.  The user types
    into the field; what they type is autocompleted.  If there's an
    ambiguity when they press Enter, a popup is used to finalise their
    selection.

    model: the database model for the table

    field: the model attribute to search on, which must be a String type

    default: a model instance to use as the default value

    create: a function to call to create a new row; it is called with
    the modelfield instance and current field contents as parameters
    """
    def __init__(self, y, x, w, model, field, filter=None, default=None,
                 create=None, keymap={}, readonly=False):
        self._model = model
        self._attr = field
        self._field = getattr(self._model, self._attr)
        self._create = create
        super().__init__(
            y, x, w, keymap=keymap,
            f=default,
            flen=self._field.type.length,
            validate=self._validate_autocomplete,
            readonly=readonly)

    def _complete(self, m):
        q = td.s.query(self._field)
        q = q.filter(self._field.ilike("{}%".format(m)))
        q = q.order_by(func.length(self._field), self._field)
        return [x[0] for x in q.all()]

    @staticmethod
    def _commonprefix(l):
        """Case-insensitive common prefix of a list of strings

        This is surprisingly difficult to think about!

        When there is a match, the string returned will have the case
        of the first list member.
        """
        if not l:
            return
        s1 = min((x.lower() for x in l))
        s2 = max((x.lower() for x in l))
        for i, c in enumerate(s1):
            if c != s2[i]:
                return l[0][:i]
        return l[0]

    def _validate_autocomplete(self, s, c):
        t = s[:c + 1]
        l = self._complete(t)
        if l:
            # l is in order of length, shortest first, so
            # _commonprefix will return a string with the case of the
            # shortest match.
            return self._commonprefix(l)
        # If we can't create new entries, don't allow the user to continue
        # typing if there are no matches
        if not self._create:
            return None
        # If a string one character shorter matches then we know we
        # filled it in last time, so we should return the string with
        # the rest chopped off rather than just returning the whole
        # thing unedited.
        if self._complete(t[:-1]):
            return t
        return s

    def set(self, value):
        if value:
            super().set(getattr(value, self._attr))
        else:
            super().set(None)

    def read(self):
        i = td.s.query(self._model)\
                .filter(self._field == self._f)\
                .all()
        if len(i) == 1:
            return i[0]

    def defocus(self):
        i = self.read()
        if self._f and not i:
            # Find candidate matches and pop up a list of them
            m = td.s.query(self._field)\
                    .filter(self._field.ilike("{}%".format(self._f)))\
                    .order_by(self._field)\
                    .all()
            ml = [ (x[0], super(modelfield, self).set, (x[0],)) for x in m ]
            if self._create:
                ml.append(("Create new...", self._create, (self, self._f,)))
            self.set(None)
            menu(ml, title="Choose...")

class modelpopupfield(valuefield):
    """A field that allows a model instance to be chosen using a popup dialog

    A field which has its value set using a popup dialog.  The values
    the field can take are unordered; there is no concept of "next"
    and "previous".  The field can also be null.

    popupfunc is a function that takes two arguments: the function to
    call when a value is chosen, and the current value of the field.
    
    valuefunc is a function that takes one argument: the current value
    of the field.  It returns a string to display.  It is never passed
    None as an argument.

    The current value of the field, if not-None, is always a database
    model.  It is not necessarily a model previously supplied via
    set() or through popupfunc().
    """
    def __init__(self, y, x, w, model, popupfunc, valuefunc, f=None, keymap={},
                 readonly=False):
        # f must be a database model or None
        self.y = y
        self.x = x
        self.w = w
        self.model = model
        self.popupfunc = popupfunc
        self.valuefunc = valuefunc
        self.readonly = readonly
        super().__init__(keymap, f)

    def focus(self):
        super().focus()
        self.draw()

    def set(self, value):
        self._f = sqlalchemy.inspection.inspect(value).identity \
                  if value else None
        self.sethook()
        self.draw()

    def read(self):
        if self._f is None:
            return None
        return td.s.query(self.model).get(self._f)

    def draw(self):
        pos = self.win.getyx()
        i = self.read()
        if i:
            s = self.valuefunc(i)
        else:
            s = ""
        if len(s) > self.w:
            s = s[:self.w]
        self.win.addstr(self.y, self.x, ' ' * self.w, self.win.colour.reversed)
        self.win.addstr(self.y, self.x, s, self.win.colour.reversed)
        if self.focused:
            self.win.move(self.y, self.x)
        else:
            self.win.move(*pos)

    def popup(self):
        if not self.readonly:
            self.popupfunc(self.setf, self.read())

    def keypress(self, k):
        if k == keyboard.K_CLEAR and self._f is not None and not self.readonly:
            self.set(None)
        elif k == keyboard.K_CASH and not self.readonly:
            self.popup()
        elif k and isinstance(k, str) and self.read() is None \
             and not self.readonly:
            # If the field is blank and the user starts typing into it,
            # pop up the dialog and send the keypress to it.
            self.popup()
            handle_keyboard_input(k)
        else:
            super().keypress(k)

class modellistfield(modelpopupfield):
    """A field that allows a model instance to be chosen from a list

    A field which allows a model instance to be chosen from a list.
    The list is ordered: for any particular value there is a concept
    of "next" and "previous".

    l is a function which, given a Query object for the model filters
    it such that the desired list of instances will be obtained, and
    returns it.

    A function d can be provided; if it is, then d(model) is expected
    to return a suitable string for display.  If it is not then
    str(model) is called to obtain a string.

    This should only be used where the list of model instances is
    expected to be small: the entire list is loaded from the database
    on every user interaction.  Where the list may be large, it is
    likely to be better to use a modelfield() instead.
    """

    def __init__(self, y, x, w, model, l, d=str, f=None, keymap={},
                 readonly=False):
        self._query = l
        super().__init__(
            y, x, w, model, self._popuplist, d,
            f=f, keymap=keymap, readonly=readonly)

    def _popuplist(self, func, default):
        l = self._query(td.s.query(self.model)).all()
        current = self.read()
        default = None
        try:
            default = l.index(current)
        except ValueError:
            pass
        m = [(self.valuefunc(x), func, (x,)) for x in l]
        menu(m, colour=colour_line, default=default)

    def change_query(self, l):
        """Change the query

        Replace the current list of models with a new one.  If the
        currently chosen model is in the list, keep it; otherwise,
        select the first model from the new list.
        """
        self._query = l
        l = self._query(td.s.query(self.model)).all()
        current = self.read()
        if current in l:
            return
        if len(l) > 0:
            self.set(l[0])
        else:
            self.set(None)

    def nextitem(self):
        l = self._query(td.s.query(self.model)).all()
        current = self.read()
        if current in l:
            ni = l.index(current) + 1
            if ni >= len(l):
                ni = 0
            self.set(l[ni])
        else:
            if len(l) > 0:
                self.set(l[0])
            else:
                self.set(None)

    def previtem(self):
        l = self._query(td.s.query(self.model)).all()
        current = self.read()
        if current in l:
            pi = l.index(current) - 1
            self.set(l[pi])
        else:
            if len(l) > 0:
                self.set(l[-1])
            else:
                self.set(None)

    def prefixitem(self, prefix):
        l = self._query(td.s.query(self.model)).all()
        current = self.read()
        if current in l:
            idx = l.index(current) + 1
            l = l[idx:] + l[:idx]
        for i in l:
            if self.valuefunc(i).lower().startswith(prefix.lower()):
                self.set(i)
                return

    def keypress(self, k):
        if not self.readonly:
            if k == keyboard.K_RIGHT:
                return self.nextitem()
            elif k == keyboard.K_LEFT:
                return self.previtem()
            elif isinstance(k, str):
                return self.prefixitem(k)
        super().keypress(k)

class buttonfield(field):
    def __init__(self, y, x, w, text, keymap={}):
        self.y = y
        self.x = x
        self.t = text.center(w - 2)
        super().__init__(keymap)
        self.draw()

    def focus(self):
        super().focus()
        self.draw()

    def defocus(self):
        super().defocus()
        self.draw()

    @property
    def f(self):
        # XXX does anything actually use this?
        return self.focused

    def read(self):
        return self.focused

    def draw(self):
        if self.focused:
            s = "[%s]" % self.t
        else:
            s = " %s " % self.t
        pos = self.win.getyx()
        self.win.addstr(self.y, self.x, s, self.win.colour.reversed)
        if self.focused:
            self.win.move(self.y, self.x)
        else:
            self.win.move(*pos)

def map_fieldlist(fl):
    """Set up navigation between fields

    Update the nextfield and prevfield attributes of each field in fl
    to enable movement between fields.
    """
    for i in range(0, len(fl)):
        next = i + 1
        if next >= len(fl):
            next = 0
        next = fl[next]
        prev = i - 1
        if prev < 0:
            prev = len(fl) - 1
        prev = fl[prev]
        fl[i].nextfield = next
        fl[i].prevfield = prev

def popup_exception(title):
    e = traceback.format_exception(*sys.exc_info())
    infopopup(e, title=title)

class exception_popup:
    """Pop up a window describing a caught exception.

    Provide the user with the option to see the full traceback if they
    want to.
    """
    def __init__(self, description, title, type, value, tb):
        self._description = description
        self._title = title
        self._type = type
        self._value = value
        self._tb = tb
        infopopup(
            [description, "", str(value), "",
             "Press {} to see more details.".format(keyboard.K_CASH.keycap)],
            title=title, keymap={keyboard.K_CASH: (self.show_all, None, True)})

    def show_all(self):
        e = traceback.format_exception(self._type, self._value, self._tb)
        infopopup(
            [self._description, ""] + e, title=self._title)

class exception_guard:
    """Context manager for code that may fail

    Context manager for running code that may raise an exception that
    should be reported to the user.
    """
    def __init__(self, description, title=None, suppress_exception=True):
        self._description = "There was a problem while {}.".format(description)
        self._title = title if title else "Error"
        self._suppress_exception = suppress_exception

    def __enter__(self):
        return self

    def __exit__(self, type, value, tb):
        if tb is None:
            return
        exception_popup(self._description, self._title, type, value, tb)
        return self._suppress_exception

# Functions to be called after the ui and main loop are initialised
run_after_init = []

# Functions to be called after the screen is resized
run_after_resize = []

def beep():
    """Make the terminal go beep
    """
    # display system patches this to work
    log.warning("ui.beep() called before display system init")
