# This module manages the display - the header line, clock, popup
# windows, and so on.

import time
import datetime
import math
import sys
import textwrap
import traceback
import locale
import curses, curses.ascii, curses.panel
import os.path
from . import keyboard, event, tillconfig, td
from .td import func
import sqlalchemy.inspection

import logging
log = logging.getLogger(__name__)

c = locale.getpreferredencoding()

colour_header=1
colour_error=1 # white on red
colour_info=2  # black on green
colour_input=3 # white on blue
colour_line=4
colour_cashline=5
colour_changeline=6
colour_cancelline=7
colour_confirm=8 # black on cyan

def attr(colour):
    """Convert a colour number to a value suitable to be passed as attr
    """
    return curses.color_pair(colour)

def attr_reverse(attr=0):
    return attr | curses.A_REVERSE

def maxwinsize():
    """Maximum window height and width, in characters
    """
    return stdwin.getmaxyx()

class clockheader(object):
    """
    A single-line header at the top of the screen, with a clock at the
    right-hand side.  Can be passed text for the top-left and the
    middle.  Draws directly on the curses root window, not into a
    panel.

    """
    def __init__(self,win,left="Quicktill",middle=""):
        self.stdwin=win
        my, self.mx = maxwinsize()
        self.left=left
        self.middle=middle
        self.alarm()
        event.eventlist.append(self)
    def redraw(self):
        """
        The header line consists of the title of the page at the left,
        optionally a summary of what's on other pages in the middle,
        and the clock at the right.  If we do not have enough space,
        we truncate the summary section until we do.  If we still
        don't, we truncate the page name.
        
        """
        m=self.left
        s=self.middle
        t=time.strftime("%a %d %b %Y %H:%M:%S %Z")
        def cat(m,s,t):
            w=len(m)+len(s)+len(t)
            pad1 = (self.mx-w) // 2
            pad2 = pad1
            if w + pad1 + pad2 != self.mx:
                pad1 = pad1 + 1
            return ''.join([m,' '*pad1,s,' '*pad2,t])
        x=cat(m,s,t)
        while len(x) > self.mx:
            if len(s)>0: s=s[:-1]
            elif len(m)>0: m=m[:-1]
            else: t=t[1:]
            x=cat(m,s,t)
        self.stdwin.addstr(0,0,x.encode(c),curses.color_pair(colour_header))
    def update(self,left=None,middle=None):
        if left is not None: self.left=left
        if middle is not None: self.middle=middle
        self.redraw()
    def alarm(self):
        self.redraw()
        now=time.time()
        self.nexttime=math.ceil(now)+0.01

def formattime(ts):
    "Returns ts formatted as %Y-%m-%d %H:%M:%S"
    if ts is None: return ""
    return ts.strftime("%Y-%m-%d %H:%M:%S")

def formatdate(ts):
    "Returns ts formatted as %Y-%m-%d"
    if ts is None: return ""
    return ts.strftime("%Y-%m-%d")

def handle_keyboard_input(k):
    """
    We can be passed a variety of things as keyboard input:

    keycode objects from keyboard.py
    strings
    user tokens

    They don't always have a 'keycap' method - check the type first!

    """
    log.debug("Keypress %s", k)
    basicwin._focus.hotkeypress(k)

# Keypresses are passed to each filter in this stack in order.
keyboard_filter_stack = []

def handle_raw_keyboard_input(k):
    global keyboard_filter_stack

    input = [k]

    for f in keyboard_filter_stack:
        input = f(input)

    for k in input:
        with td.orm_session():
            handle_keyboard_input(k)

def current_user():
    """
    Look up the focus stack and return the first user information
    found, or None if there is none.

    """
    stack=basicwin._focus.parents()
    for i in stack:
        if hasattr(i,'user'): return i.user

class winobject(object):
    """Any class that has win and pan attributes.  Not instantiated
    directly.

    """
    def addstr(self,y,x,s,attr=None):
        try:
            if attr is None:
                self.win.addstr(y,x,s.encode(c))
            else:
                self.win.addstr(y,x,s.encode(c),attr)
        except curses.error:
            log.debug("addstr problem: len(s)=%d; s=%s",len(s),repr(s))

    def wrapstr(self, y, x, width, s, attr=None):
        """Display a string wrapped to specified width.

        Returns the number of lines that the string was wrapped over.
        """
        lines = 0
        for line in s.splitlines():
            if line:
                for wrappedline in textwrap.wrap(line, width):
                    self.addstr(y + lines, x, wrappedline, attr)
                    lines += 1
            else:
                lines += 1
        return lines

    def getyx(self):
        return self.win.getyx()
    def move(self, y, x):
        return self.win.move(y, x)
    def erase(self):
        return self.win.erase()

class _toastmaster(winobject):
    """Manages a queue of messages to be displayed to the user without
    affecting the input focus.  A single instance of this object is
    created during UI initialisation.

    """
    # How long to display messages for, in seconds
    toast_display_time=3
    # Gap between messages, in seconds
    inter_toast_time=0.5

    def __init__(self):
        self.messagequeue=[]
        self.current_message=None
        self.nexttime=None
        event.eventlist.append(self)
        self.curses_initialised=False
    def toast(self,message):
        """Display the message to the user.

        If an identical message is already in the queue of messages,
        don't add it.  If an identical message is already being
        displayed, reset the timeout to the default so the message
        continues to be displayed.

        """
        if message in self.messagequeue: return
        if not self.curses_initialised:
            self.messagequeue.append(message)
            return
        if message==self.current_message:
            self.nexttime=time.time()+self.toast_display_time
            return
        if self.current_message or self.messagequeue:
            self.messagequeue.append(message)
        else:
            self.start_display(message)
    def notify_curses_initialised(self):
        self.curses_initialised=True
        if self.messagequeue: self.alarm()
    def start_display(self,message):
        # Ensure that we do not attempt to display a toast (for example, an
        # error log entry from an exception caught at the top level of the
        # application) if curses has already been deinitialised.
        if curses.isendwin(): return
        self.current_message=message
        self.nexttime=time.time()+self.toast_display_time
        # Work out where to put the window.  We're aiming for about
        # 2/3 of the screen width, around 1/3 of the way up
        # vertically.  If a toast ends up particularly high, make sure
        # we always have at least one blank line at the bottom of the
        # screen.
        mh, mw = maxwinsize()
        w = min((mw * 2) // 3, len(message))
        lines=textwrap.wrap(message,w)
        w=max(len(l) for l in lines)+4
        h=len(lines)+2
        y=(mh * 2) // 3 - (h // 2)
        if y+h+1>=mh: y=mh-h-1
        try:
            self.win=curses.newwin(h, w, y, (mw - w) // 2)
        except curses.error:
            return self.start_display("(toast too long)")
        self.pan=curses.panel.new_panel(self.win)
        self.pan.set_userptr(self)
        self.win.bkgdset(ord(' '),curses.color_pair(colour_error))
        self.win.clear()
        y=1
        for l in lines:
            self.win.addstr(y,2,l)
            y=y+1
        # Flush this to the display immediately; sometimes toasts are
        # added just before starting a lengthy / potentially blocking
        # operation, and if the timer expires before the operation
        # completes the toast will never be seen.
        curses.panel.update_panels()
        curses.doupdate()
    def to_top(self):
        if hasattr(self,"pan"):
            self.pan.top()
    def alarm(self):
        if self.current_message:
            # Stop display of message
            self.current_message=None
            self.pan.hide()
            del self.pan,self.win
            self.nexttime=(
                time.time()+self.inter_toast_time if self.messagequeue else None)
        else:
            self.start_display(self.messagequeue.pop(0))

toaster=_toastmaster()

def toast(message):
    """Display a message briefly to the user without affecting the input
    focus.

    """
    global toaster
    toaster.toast(message)

class ignore_hotkeys(object):
    """
    Mixin class for UI elements that disables handling of hotkeys;
    they are passed to the input focus like all other keypresses.

    """
    def hotkeypress(self,k):
        basicwin._focus.keypress(k)

class basicwin(winobject):
    """Container for all pages, popup windows and fields.

    It is required that the parent holds the input focus whenever a
    basicwin instance is created.  This should usually be true!
    
    """
    _focus=None
    def __init__(self):
        self.parent=basicwin._focus
        log.debug("New %s with parent %s",self,self.parent)
    @property
    def focused(self):
        """
        Do we hold the focus at the moment?

        """
        return basicwin._focus==self
    def focus(self):
        """Called when we are being told to take the focus.

        """
        if basicwin._focus!=self:
            oldfocus=basicwin._focus
            basicwin._focus=self
            oldfocus.defocus()
            log.debug("Focus %s -> %s"%(oldfocus,self))
    def defocus(self):
        """Called when we are being informed that we have (already) lost the
        focus.

        """
        pass
    def parents(self):
        if self.parent==self:
            return [self]
        return [self]+self.parent.parents()
    def keypress(self,k):
        pass
    def hotkeypress(self,k):
        """
        We get to look at keypress events before anything else does.
        If we don't do anything with this keypress we are required to
        pass it on to our parent.

        """
        self.parent.hotkeypress(k)

class basicpage(basicwin):
    _pagelist=[]
    _basepage=None
    def __init__(self):
        """
        Create a new page.  This function should be called at
        the start of the __init__ function of any subclass.

        Newly-created pages are always selected.
        """
        # We need to deselect any current page before creating our
        # panel, because creating a panel implicitly puts it on top of
        # the panel stack.
        if basicpage._basepage:
            basicpage._basepage.deselect()
        (my, mx) = stdwin.getmaxyx()
        self.win = curses.newwin(my - 1, mx, 1, 0)
        self.pan = curses.panel.new_panel(self.win)
        self.pan.set_userptr(self)
        basicpage._pagelist.append(self)
        (self.h, self.w) = self.win.getmaxyx()
        self.savedfocus = self
        self.stack = None
        basicpage._basepage = self
        basicwin._focus = self
        basicwin.__init__(self) # Sets self.parent to self - ok!
        toaster.to_top()
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
        self.pan.show()
        if self.stack:
            for i in self.stack:
                i.show()
        self.savedfocus = None
        self.stack = None
        self.updateheader()
        toaster.to_top()
    def deselect(self):
        """Deselect this page.

        Deselect this page if it is currently selected.  Save the
        panel stack so we can restore it next time we are selected.
        """
        if basicpage._basepage != self:
            return
        self.savedfocus = basicwin._focus
        l = []
        t = curses.panel.top_panel()
        while t.userptr() != self:
            if t.userptr() == toaster:
                t = t.below()
                continue # Ignore any toast
            st = t
            l.append(t)
            t = t.below()
            st.hide()
        l.reverse()
        self.stack = l
        self.pan.hide()
        basicpage._basepage=None
        basicwin._focus=None

    def dismiss(self):
        """Remove this page."""
        if basicpage._basepage == self:
            self.deselect()
        del self.pan, self.win, self.stack
        del basicpage._pagelist[basicpage._pagelist.index(self)]

    @staticmethod
    def updateheader():
        global header
        m = ""
        s = ""
        for i in basicpage._pagelist:
            if i == basicpage._basepage:
                m = i.pagename() + ' '
            else:
                ps = i.pagesummary()
                if ps:
                    s = s + i.pagesummary() + ' '
        header.update(m, s)

    @staticmethod
    def _ensure_page_exists():
        if basicpage._basepage == None:
            with td.orm_session():
                tillconfig.firstpage()

    def hotkeypress(self, k):
        """Since this is a page, it is always at the base of the stack of
        windows - it does not have a parent to pass keypresses on to.
        By default we look at the configured hotkeys and call if
        found; otherwise we pass the keypress on to the current input
        focus (if it exists) for regular keypress processing.

        If there is no current input focus then one will be set in
        _ensurepage_exists() the next time around the event loop.
        """
        if k in tillconfig.hotkeys:
            tillconfig.hotkeys[k]()
        elif hasattr(k, 'usertoken'):
            tillconfig.usertoken_handler(k)
        else:
            if basicwin._focus:
                basicwin._focus.keypress(k)

class basicpopup(basicwin):
    def __init__(self,h,w,title=None,cleartext=None,colour=colour_error,
                 keymap={}):
        basicwin.__init__(self)
        # Grab the focus so that we hold it while we create any necessary
        # child UI elements
        self.focus()
        self.keymap=keymap
        mh, mw = maxwinsize()
        if title: w=max(w,len(title)+3)
        if cleartext: w=max(w,len(cleartext)+3)
        w=min(w,mw)
        h=min(h,mh)
        y=(mh - h) // 2
        x=(mw - w) // 2
        self.win=curses.newwin(h,w,y,x)
        self.pan=curses.panel.new_panel(self.win)
        self.pan.set_userptr(self)
        self.win.bkgdset(ord(' '),curses.color_pair(colour))
        self.win.clear()
        self.win.border()
        if title: self.addstr(0,1,title)
        if cleartext: self.addstr(h-1,w-1-len(cleartext),cleartext)
        self.pan.show()
        toaster.to_top()
    def dismiss(self):
        self.pan.hide()
        del self.pan,self.win
        self.parent.focus()
    def keypress(self,k):
        # We never want to pass unhandled keypresses back to the parent
        # of the popup.
        if k in self.keymap:
            i=self.keymap[k]
            if len(i) > 2 and i[2]:
                if i[2]: self.dismiss()
            if i[0] is not None:
                if len(i) > 1 and i[1] is not None:
                    i[0](*i[1])
                else:
                    i[0]()
        else:
            curses.beep()

class dismisspopup(basicpopup):
    """Adds optional processing of an implicit 'Dismiss' key and
    generation of the cleartext prompt"""
    def __init__(self,h,w,title=None,cleartext=None,colour=colour_error,
                 dismiss=keyboard.K_CLEAR,keymap={}):
        self.dismisskey=dismiss
        basicpopup.__init__(self,h,w,title=title,
                            cleartext=self.get_cleartext(cleartext,dismiss),
                            colour=colour,keymap=keymap)
    def get_cleartext(self,cleartext,dismiss):
        if cleartext is None:
            if dismiss==keyboard.K_CLEAR:
                return "Press Clear to go back"
            elif dismiss==keyboard.K_CASH:
                return "Press Cash/Enter to continue"
            elif dismiss is None:
                return None
            else:
                return "Press %s to dismiss"%dismiss.keycap
        return cleartext
    def keypress(self,k):
        if self.dismisskey is not None and k==self.dismisskey:
            return self.dismiss()
        basicpopup.keypress(self,k)

class listpopup(dismisspopup):
    """
    A popup window with an initial non-scrolling header, and then a
    scrollable list of selections.  Items in the list and header can
    be strings, or any subclass of emptyline().  The header is not
    used when deciding how wide the window will be.

    """
    def __init__(self,linelist,default=0,header=None,title=None,
                 show_cursor=True,dismiss=keyboard.K_CLEAR,
                 cleartext=None,colour=colour_input,w=None,keymap={}):
        dl=[x if isinstance(x,emptyline) else line(x) for x in linelist]
        hl=[x if isinstance(x,emptyline) else marginline(lrline(x),margin=1)
            for x in header] if header else []
        if w is None:
            w=max((x.idealwidth() for x in dl))+2 if len(dl)>0 else 0
            w=max(25,w)
        if title is not None:
            w=max(len(title)+3,w)
        # We know that the created window will not be wider than the
        # width of the screen.
        mh, mw = maxwinsize()
        w=min(w,mw)
        h=sum(len(x.display(w-2)) for x in hl+dl)+2
        dismisspopup.__init__(self,h,w,title=title,colour=colour,keymap=keymap,
                              dismiss=dismiss,cleartext=cleartext)
        (h,w)=self.win.getmaxyx()
        y=1
        for hd in hl:
            l=hd.display(w-2)
            for i in l:
                self.addstr(y,1,i)
                y=y+1
        # Note about keyboard handling: the scrollable will always have
        # the focus.  It will deal with cursor keys itself.  All other
        # keys will be passed through to our keypress() method, which
        # may well be overridden in a subclass.  We expect subclasses to
        # implement keypress() themselves, and access the methods of the
        # scrollable directly.  If there's no scrollable this will fail!
        if len(linelist)>0:
            log.debug("listpopup scrollable %d %d %d %d",y,1,w-2,h-y-1)
            self.s=scrollable(y,1,w-2,h-y-1,dl,show_cursor=show_cursor)
            self.s.cursor=default if default is not None else 0
            self.s.focus()
        else:
            self.s=None

class infopopup(listpopup):
    """
    A pop-up box that formats and displays text.  The text parameter is
    a list of paragraphs.

    """
    # Implementation note: we _could_ use a scrollable with a list of
    # lrlines; however, we have to work out how big to make the window
    # anyway, and once we've done that we already have a list of lines
    # suitable to pass to listpopup.__init__()
    def __init__(self,text=[],title=None,dismiss=keyboard.K_CLEAR,
                 cleartext=None,colour=colour_error,keymap={}):
        cleartext=self.get_cleartext(cleartext,dismiss)
        mh, mw = maxwinsize()
        maxw=mw-4
        maxh=mh-5
        # We want the window to end up as close to 2/3 the maximum width
        # as possible.  Try that first, and only let it go wider if the
        # maximum height is exceeded.
        w = (maxw * 2) // 3
        if cleartext: w=max(w,len(cleartext)-1)
        def formatat(width):
            r=[]
            for i in text:
                if i=="": r.append("")
                else:
                    for j in textwrap.wrap(i,width):
                        r.append(j)
            return r
        t=formatat(w)
        while len(t)>maxh and w<maxw:
            w=w+1
            t=formatat(w)
        t=[emptyline()]+[marginline(line(x),margin=1) for x in t]+[emptyline()]
        listpopup.__init__(self,t,title=title,dismiss=dismiss,
                           cleartext=cleartext,colour=colour,keymap=keymap,
                           show_cursor=False,w=w+4)

class alarmpopup(infopopup):
    """This is like an infopopup, but goes "beep" every second until
    it is dismissed.  It dismisses itself after 5 minutes, provided it
    still has the input focus.  (If it doesn't have the focus,
    dismissing would put the focus in the wrong place - potentially on
    a different page, which would be VERY confusing for the user!)

    """
    def __init__(self,*args,**kwargs):
        infopopup.__init__(self,*args,**kwargs)
        self.remaining=300
        event.eventlist.append(self)
        self.alarm()
    def alarm(self):
        curses.beep()
        self.nexttime=math.ceil(time.time())
        self.remaining=self.remaining-1
        if self.remaining<1:
            if self in basicwin._focus.parents(): self.dismiss()
            else: del event.eventlist[event.eventlist.index(self)]
    def dismiss(self):
        if self in event.eventlist:
            del event.eventlist[event.eventlist.index(self)]
        infopopup.dismiss(self)

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
    """An area of a window that has a value that can be changed."""
    def __init__(self, y, x, w, contents="", align="<", attr=None):
        super(label, self).__init__()
        self.win = self.parent.win
        self._y = y
        self._x = x
        self._format = "%s%d.%d" % (align, w, w)
        self.set(contents, attr=attr)

    def set(self, contents, attr=None):
        y, x = self.win.getyx()
        self.addstr(self._y, self._x, format(str(contents), self._format), attr)
        self.win.move(y, x)

class field(basicwin):
    """A field inside a window.

    Able to receive the input focus, and knows how to pass it on to
    peer fields.
    """
    def __init__(self, keymap={}):
        self.nextfield=None
        self.prevfield=None
        # We _must_ copy the provided keymap; it is permissible for our
        # keymap to be modified after initialisation, and it would be
        # a Very Bad Thing (TM) for the default empty keymap to be
        # changed!
        self.keymap=keymap.copy()
        basicwin.__init__(self)
        self.win=self.parent.win

    def keypress(self,k):
        # All keypresses handled here are defaults; if they are present
        # in the keymap, we should not handle them ourselves.
        if k in self.keymap:
            i=self.keymap[k]
            if i[0] is not None:
                if i[1] is None: i[0]()
                else: i[0](*i[1])
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
        super(valuefield, self).__init__(keymap)
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
    def __init__(self,y,x,width,height,dl,show_cursor=True,
                 lastline=None,default=0,keymap={}):
        field.__init__(self,keymap)
        self.y=y
        self.x=x
        self.w=width
        self.h=height
        self.show_cursor=show_cursor
        self.lastline=lastline
        self.cursor=default
        self.top=0
        self.set(dl)
    def set(self,dl):
        self.dl=dl
        self.redraw() # Does implicit set_cursor()
    def set_cursor(self,c):
        if len(self.dl)==0 and not self.lastline:
            self.cursor=None
            return
        if c is None or c<0: c=0
        last_valid_cursor=len(self.dl) if self.lastline else len(self.dl)-1
        if c>last_valid_cursor: c=last_valid_cursor
        self.cursor=c
    def focus(self):
        # If we are obtaining the focus from the previous field, we should
        # move the cursor to the top.  If we are obtaining it from the next
        # field, we should move the cursor to the bottom.  Otherwise we
        # leave the cursor untouched.
        if self.prevfield and self.prevfield.focused: self.set_cursor(0)
        elif self.nextfield and self.nextfield.focused:
            self.set_cursor(len(self.dl))
        field.focus(self)
        self.redraw()
    def defocus(self):
        field.defocus(self)
        self.drawdl() # We don't want to scroll
    def drawdl(self):
        """
        Redraw the area with the current scroll and cursor locations.
        Returns the index of the last complete item that fits on the
        screen.  (This is useful to compare against the cursor
        position to ensure the cursor is displayed.)

        """
        # First clear the drawing space
        for y in range(self.y,self.y+self.h):
            self.addstr(y,self.x,' '*self.w)
        # Special case: if top is 1 and cursor is 1 and the first item
        # in the list is exactly one line high, we can set top to zero
        # so that the first line is displayed.  Only worthwhile if we
        # are actually displaying a cursor.
        if self.top==1 and self.cursor==1 and self.show_cursor:
            if len(self.dl[0].display(self.w))==1: self.top=0
        # self.dl may have shrunk since last time self.top was set;
        # make sure self.top is in bounds
        if self.top>len(self.dl): self.top=len(self.dl)
        y=self.y
        i=self.top
        lastcomplete=i
        if i>0:
            self.addstr(y,self.x,'...')
            y=y+1
        cursor_y=None
        end_of_displaylist=len(self.dl)+1 if self.lastline else len(self.dl)
        while i<end_of_displaylist:
            if i>=len(self.dl):
                item=self.lastline
            else:
                item=self.dl[i]
            if item is None: break
            l=item.display(self.w)
            colour=item.colour
            ccolour=item.cursor_colour
            if self.focused and i==self.cursor and self.show_cursor:
                colour=ccolour
                cursor_y=y+item.cursor[1]
                cursor_x=self.x+item.cursor[0]
            for j in l:
                if y<(self.y+self.h):
                    self.addstr(y,self.x,"%s%s"%(j,' '*(self.w-len(j))),colour)
                y=y+1
            if y<=(self.y+self.h):
                lastcomplete=i
            else:
                break
            i=i+1
        if end_of_displaylist>i:
            # Check whether we are about to overwrite any of the last item
            if y>=self.y+self.h+1: lastcomplete=lastcomplete-1
            self.addstr(self.y+self.h-1,self.x,'...'+' '*(self.w-3))
        if cursor_y is not None and cursor_y<(self.y+self.h):
            self.win.move(cursor_y,cursor_x)
        return lastcomplete
    def redraw(self):
        """
        Updates the field, scrolling until the cursor is visible.  If we
        are not showing the cursor, the top line of the field is always
        the cursor line.

        """
        self.set_cursor(self.cursor)
        if self.cursor is None:
            self.top=0
        elif self.cursor<self.top or self.show_cursor==False:
            self.top=self.cursor
        end_of_displaylist=len(self.dl)+1 if self.lastline else len(self.dl)
        lastitem=self.drawdl()
        while self.cursor is not None and self.cursor>lastitem:
            self.top=self.top+1
            lastitem=self.drawdl()
        self.display_complete=(lastitem==end_of_displaylist-1)
    def cursor_at_start(self):
        if self.cursor is None: return True
        return self.cursor==0
    def cursor_at_end(self):
        if self.cursor is None: return True
        if self.show_cursor:
            if self.lastline:
                return self.cursor>=len(self.dl)
            else:
                return self.cursor==len(self.dl)-1 or len(self.dl)==0
        else:
            return self.display_complete
    def cursor_on_lastline(self):
        return self.cursor==len(self.dl)
    def cursor_up(self,n=1):
        if self.cursor_at_start():
            if self.prevfield is not None and self.focused:
                return self.prevfield.focus()
        else:
            self.set_cursor(self.cursor-n)
        self.redraw()
    def cursor_down(self,n=1):
        if self.cursor_at_end():
            if self.nextfield is not None and self.focused:
                return self.nextfield.focus()
        else:
            self.set_cursor(self.cursor+n)
        self.redraw()
    def keypress(self,k):
        if k==keyboard.K_DOWN: self.cursor_down(1)
        elif k==keyboard.K_UP: self.cursor_up(1)
        elif k==keyboard.K_RIGHT: self.cursor_down(5)
        elif k==keyboard.K_LEFT: self.cursor_up(5)
        elif k==curses.KEY_NPAGE: self.cursor_down(10)
        elif k==curses.KEY_PPAGE: self.cursor_up(10)
        else: field.keypress(self,k)

class emptyline(object):
    """
    A line for use in a scrollable.  Has a natural colour, a "cursor
    is here" colour, and an optional "selected" colour.  This line has
    no text.

    """
    def __init__(self,colour=None,userdata=None):
        if colour is None: colour=curses.color_pair(0)
        self.colour=curses.color_pair(colour)
        self.cursor_colour=self.colour|curses.A_REVERSE
        self.userdata=userdata
    def update(self):
        pass
    def idealwidth(self):
        return 0
    def display(self,width):
        """
        Returns a list of lines (of length 1), with one empty line.

        """
        # After display has been called, the caller can read 'cursor' to
        # find our preferred location for the cursor if we are selected.
        # It's a (x,y) tuple where y is 0 for the first line.
        self.cursor=(0,0)
        return [""]

class emptylines(emptyline):
    def __init__(self,colour=None,lines=1,userdata=None):
        emptyline.__init__(self,colour,userdata)
        self.lines=lines
    def display(self,width):
        self.cursor=(0,0)
        return [""]*self.lines

class line(emptyline):
    """
    A line for use in a scrollable.  Has a natural colour, a "cursor
    is here" colour, and some text.  If the text is too long it will
    be truncated; this line will never wrap.

    """
    def __init__(self,text="",colour=None,userdata=None):
        emptyline.__init__(self,colour,userdata)
        self.text=text
    def idealwidth(self):
        return len(self.text)
    def display(self,width):
        """
        Returns a list of lines (of length 1), truncated to the
        specified maximum width.

        """
        # After display has been called, the caller can read 'cursor' to
        # find our preferred location for the cursor if we are selected.
        # It's a (x,y) tuple where y is 0 for the first line.
        self.cursor=(0,0)
        return [self.text[:width]]

class marginline(emptyline):
    """
    Indent another line with a margin at the left and right.

    """
    def __init__(self,l,margin=0,colour=None,userdata=None):
        emptyline.__init__(self,colour,userdata)
        self.l=l
        self.margin=margin
    def idealwidth(self):
        return self.l.idealwidth()+(2*self.margin)
    def display(self,width):
        m=' '*self.margin
        ll=[m+x+m for x in self.l.display(width-(2*self.margin))]
        cursor=(self.l.cursor[0]+self.margin,self.l.cursor[1])
        return ll

class lrline(emptyline):
    """A line for use in a scrollable.

    Has a natural colour, a "cursor is here" colour, an optional
    "selected" colour, some left-aligned text (which will be wrapped
    if it is too long) and optionally some right-aligned text.
    """
    def __init__(self, ltext="", rtext="", colour=None, userdata=None):
        emptyline.__init__(self, colour)
        self.ltext = ltext
        self.rtext = rtext
    def idealwidth(self):
        return len(self.ltext) + (len(self.rtext) + 1 \
                                  if len(self.rtext) > 0 else 0)
    def display(self, width):
        """Format for display.

        Returns a list of lines, formatted to the specified maximum
        width.  If there is right-aligned text it is included along
        with the text on the last line if there is space; otherwise a
        new line is added with the text at the right.
        """
        # After display has been called, the caller can read 'cursor' to
        # find our preferred location for the cursor if we are selected.
        # It's a (x, y) tuple where y is 0 for the first line.
        self.cursor = (0, 0)
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
        emptyline.__init__(self, colour, userdata)
        self._formatter = formatter
        self.fields = [str(x) for x in fields]

    def update(self):
        emptyline.update(self)
        self._formatter._update(self)

    def idealwidth(self):
        return self._formatter.idealwidth()

    def display(self, width):
        self.cursor = (0, 0)
        return self._formatter.format(self, width)

class menu(listpopup):
    """A popup menu with a list of selections. Selection can be made by
    using cursor keys to move up and down, and pressing Cash/Enter to
    confirm.

    itemlist is a list of (desc,func,args) tuples.  If desc is a
    string it will be converted to a line(); otherwise it is assumed
    to be some subclass of emptyline().

    """
    def __init__(self,itemlist,default=0,
                 blurb="Select a line and press Cash/Enter",
                 title=None,
                 colour=colour_input,w=None,dismiss_on_select=True,
                 keymap={}):
        self.itemlist=itemlist
        self.dismiss_on_select=dismiss_on_select
        dl=[x[0] for x in itemlist]
        if not isinstance(blurb,list): blurb=[blurb]
        listpopup.__init__(self,dl,default=default,
                           header=blurb,title=title,
                           colour=colour,w=w,keymap=keymap)
    def keypress(self,k):
        if k==keyboard.K_CASH:
            if len(self.itemlist)>0:
                i=self.itemlist[self.s.cursor]
                if self.dismiss_on_select: self.dismiss()
                if i[2] is None:
                    i[1]()
                else:
                    i[1](*i[2])
        else:
            listpopup.keypress(self,k)

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
        self.colour = curses.color_pair(colour)
        self.cursor_colour = self.colour
        self.prompt = " " + str(keycode) + ". "
        self.desc = desc if isinstance(desc, emptyline) else line(desc)
    def update(self):
        pass
    def idealwidth(self):
        return self._keymenu.promptwidth + self.desc.idealwidth() + 1
    def display(self, width):
        self.cursor = (0, 0)
        dl = self.desc.display(width - self._keymenu.promptwidth)
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
    """A popup menu with a list of selections.  Selections are made by
    pressing the key associated with the selection.

    itemlist is a list of (key,desc,func,args) tuples.  If desc is a
    string it will be converted to a line(); otherwise it is assumed
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
        listpopup.__init__(self, lines,
                           header=blurb, title=title,
                           colour=colour, w=w, keymap=km, show_cursor=False)

def automenu(itemlist,spill="menu",**kwargs):
    """Pop up a dialog to choose an item from the itemlist, which consists
    of (desc,func,args) tuples.  If desc is a string it will be
    converted to a lrline().

    If the list is short enough then a keymenu will be used.  If
    spill="menu" then a menu will be used; otherwise if
    spill="keymenu" (or anything else) the last option on the menu
    will bring up another menu containing the remaining items.

    """
    possible_keys=[
        "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
        ]
    itemlist=[(lrline(desc) if not isinstance(desc,emptyline) else desc,
               func,args) for desc,func,args in itemlist]
    if spill=="menu" and len(itemlist)>len(possible_keys):
        return menu(itemlist,**kwargs)
    if len(itemlist)>len(possible_keys):
        remainder=itemlist[len(possible_keys)-1:]
        itemlist=itemlist[:len(possible_keys)-1]+[
            ("More...",(lambda:automenu(remainder,spill="keymenu",**kwargs)),
             None)]
    return keymenu([(possible_keys.pop(0),desc,func,args)
                    for desc,func,args in itemlist],**kwargs)

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
        super(booleanfield, self).__init__(keymap, f)

    def focus(self):
        super(booleanfield, self).focus()
        self.draw()

    def set(self, l):
        self._f = l
        if not self.allow_blank:
            self._f = not not self._f
        self.sethook()
        self.draw()

    def draw(self):
        pos = self.win.getyx()
        if self._f is None:
            s = "   "
        else:
            s = "Yes" if self._f else "No "
        pos = self.win.getyx()
        self.addstr(self.y, self.x, s, curses.A_REVERSE)
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
            super(booleanfield, self).keypress(k)
                
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
        super(editfield, self).__init__(keymap, f)
    # Internal attributes:
    # c - cursor position
    # i - amount by which contents have scrolled left to fit width
    # _f - current contents
    @property
    def f(self):
        return self.read()

    def focus(self):
        super(editfield, self).focus()
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
        self.addstr(self.y, self.x, ' ' * self.w, curses.A_REVERSE)
        self.addstr(self.y, self.x, self._f[self.i : self.i + self.w],
                    curses.A_REVERSE)
        if self.focused:
            self.win.move(self.y, self.x + self.c - self.i)
        else:
            self.win.move(*pos)

    def insert(self, s):
        if self.readonly:
            curses.beep()
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
            curses.beep()

    def backspace(self):
        "Delete the character to the left of the cursor"
        if self.c > 0 and not self.readonly:
            self._f = self._f[:self.c - 1] + self._f[self.c:]
            self.move_left()
            self.sethook()
            self.draw()
        else:
            curses.beep()

    def delete(self):
        "Delete the character under the cursor"
        if self.c < len(self._f) and not self.readonly:
            self._f = self._f[:self.c] + self._f[self.c + 1:]
            self.sethook()
            self.draw()
        else:
            curses.beep()

    def move_left(self):
        if self.c == 0:
            curses.beep()
        self.c = max(self.c - 1, 0)
        self.draw()

    def move_right(self):
        if self.c == len(self._f):
            curses.beep()
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
            curses.beep()
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
            super(editfield, self).keypress(k)

class datefield(editfield):
    """A field for entry of dates

    The f attribute is a valid date or None
    """
    def __init__(self, y, x, keymap={}, f=None, readonly=False):
        if f is not None:
            f = formatdate(f)
        editfield.__init__(self, y, x, 10, keymap=keymap, f=f, flen=10,
                           readonly=readonly, validate=self.validate_date)
    @staticmethod
    def validate_date(s, c):
        def checkdigit(i):
            a=s[i : i + 1]
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
            super(datefield, self).set(formatdate(v))
        else:
            super(datefield, self).set(v)

    def read(self):
        try:
            d = datetime.datetime.strptime(self._f,"%Y-%m-%d")
        except:
            d = None
        return d

    def draw(self):
        self.addstr(self.y, self.x, 'YYYY-MM-DD', curses.A_REVERSE)
        self.addstr(self.y, self.x, self._f, curses.A_REVERSE)
        self.win.move(self.y, self.x + self.c)

    def insert(self, s):
        super(datefield, self).insert(s)
        if len(self._f) == 4 or len(self._f) == 7:
            self.set(self._f + '-')

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
        super(modelfield, self).__init__(
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
            super(modelfield, self).set(getattr(value, self._attr))
        else:
            super(modelfield, self).set(None)

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
        super(modelpopupfield, self).__init__(keymap, f)

    def focus(self):
        super(modelpopupfield, self).focus()
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
        self.addstr(self.y, self.x, ' ' * self.w, curses.A_REVERSE)
        self.addstr(self.y, self.x, s, curses.A_REVERSE)
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
            super(modelpopupfield, self).keypress(k)

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
        super(modellistfield, self).__init__(
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
        super(modellistfield, self).keypress(k)

class buttonfield(field):
    def __init__(self,y,x,w,text,keymap={}):
        self.y=y
        self.x=x
        self.t=text.center(w-2)
        field.__init__(self,keymap)
        self.draw()
    def focus(self):
        field.focus(self)
        self.draw()
    def defocus(self):
        field.defocus(self)
        self.draw()

    @property
    def f(self):
        # XXX does anything actually use this?
        return self.focused

    def read(self):
        return self.focused

    def draw(self):
        if self.focused: s="[%s]"%self.t
        else: s=" %s "%self.t
        pos=self.win.getyx()
        self.addstr(self.y,self.x,s,curses.A_REVERSE)
        if self.focused: self.win.move(self.y,self.x)
        else: self.win.move(*pos)

def map_fieldlist(fl):
    """Update the nextfield and prevfield attributes of each field in
    fl to enable movement between fields."""
    for i in range(0,len(fl)):
        next=i+1
        if next>=len(fl): next=0
        next=fl[next]
        prev=i-1
        if prev<0: prev=len(fl)-1
        prev=fl[prev]
        fl[i].nextfield=next
        fl[i].prevfield=prev

def popup_exception(title):
    e=traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                 sys.exc_info()[2])
    infopopup(e,title=title)

class exception_popup(object):
    """
    Pop up a window describing a caught exception.  Provide the user
    with the option to see the full traceback if they want to.

    """
    def __init__(self,description,title,type,value,tb):
        self._description=description
        self._title=title
        self._type=type
        self._value=value
        self._tb=tb
        infopopup(
            [description,"",str(value),"",
             "Press {} to see more details.".format(keyboard.K_CASH.keycap)],
            title=title,keymap={keyboard.K_CASH:(self.show_all,None,True)})
    def show_all(self):
        e=traceback.format_exception(self._type,self._value,self._tb)
        infopopup(
            [self._description,""]+e,title=self._title)

class exception_guard(object):
    """
    Context manager for running code that may raise an exception that
    should be reported to the user.

    """
    def __init__(self, description, title=None, suppress_exception=True):
        self._description="There was a problem while {}.".format(description)
        self._title=title if title else "Error"
        self._suppress_exception = suppress_exception
    def __enter__(self):
        return self
    def __exit__(self,type,value,tb):
        if tb is None: return
        exception_popup(self._description,self._title,type,value,tb)
        return self._suppress_exception

def _doupdate():
    curses.panel.update_panels()
    curses.doupdate()

class curseskeyboard:
    def fileno(self):
        return sys.stdin.fileno()
    def doread(self):
        global stdwin
        i = stdwin.getch()
        if i == -1:
            return
        handle_raw_keyboard_input(i)

class cursesfilter:
    """Keyboard input filter that converts curses keycodes to internal
    keycodes"""
    # curses codes and their till keycode equivalents
    kbcodes = {
        curses.KEY_LEFT: keyboard.K_LEFT,
        curses.KEY_RIGHT: keyboard.K_RIGHT,
        curses.KEY_UP: keyboard.K_UP,
        curses.KEY_DOWN: keyboard.K_DOWN,
        curses.KEY_ENTER: keyboard.K_CASH,
        curses.KEY_BACKSPACE: keyboard.K_BACKSPACE,
        curses.KEY_DC: keyboard.K_DEL,
        curses.KEY_HOME: keyboard.K_HOME,
        curses.KEY_END: keyboard.K_END,
        curses.KEY_EOL: keyboard.K_EOL,
        curses.ascii.TAB: keyboard.K_TAB,
        1: keyboard.K_HOME, # Ctrl-A
        4: keyboard.K_DEL, # Ctrl-D
        5: keyboard.K_END, # Ctrl-E
        10: keyboard.K_CASH,
        11: keyboard.K_EOL, # Ctrl-K
        15: keyboard.K_QUANTITY, # Ctrl-O
        16: keyboard.K_PRINT, # Ctrl-P
        20: keyboard.K_MANAGETRANS, # Ctrl-T
        24: keyboard.K_CLEAR, # Ctrl-X
        25: keyboard.K_CANCEL, # Ctrl-Y
        }
    def _curses_to_internal(self, i):
        if i in self.kbcodes:
            return self.kbcodes[i]
        elif curses.ascii.isprint(i):
            return chr(i)
    def __call__(self, keys):
        return [self._curses_to_internal(key) for key in keys]

def _init(w):
    """ncurses has been initialised, and calls us with the root window.

    When we leave this function for whatever reason, ncurses will shut
    down and return the display to normal mode.  If we're leaving with
    an exception, ncurses will reraise it.
    """
    global stdwin, header
    stdwin = w
    stdwin.nodelay(1)
    curses.init_pair(1,curses.COLOR_WHITE,curses.COLOR_RED)
    curses.init_pair(2,curses.COLOR_BLACK,curses.COLOR_GREEN)
    curses.init_pair(3,curses.COLOR_WHITE,curses.COLOR_BLUE)
    curses.init_pair(4,curses.COLOR_BLACK,curses.COLOR_YELLOW)
    curses.init_pair(5,curses.COLOR_GREEN,curses.COLOR_BLACK)
    curses.init_pair(6,curses.COLOR_YELLOW,curses.COLOR_BLACK)
    curses.init_pair(7,curses.COLOR_BLUE,curses.COLOR_BLACK)
    curses.init_pair(8,curses.COLOR_BLACK,curses.COLOR_CYAN)
    header = clockheader(stdwin)
    event.ticklist.append(basicpage._ensure_page_exists)
    event.preselectlist.append(_doupdate)
    keyboard_filter_stack.insert(0, cursesfilter())
    event.rdlist.append(curseskeyboard())
    toaster.notify_curses_initialised()
    event.eventloop()

def run():
    curses.wrapper(_init)

beep = curses.beep
