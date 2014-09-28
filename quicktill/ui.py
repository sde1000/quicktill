# This module manages the display - the header line, clock, popup
# windows, and so on.

from __future__ import unicode_literals
import curses,curses.ascii,time,math,sys,string,textwrap,traceback,locale
from . import keyboard,event,tillconfig,td

import datetime

import logging
log=logging.getLogger(__name__)

# curses requires unicode strings to be encoded before being passed
# to functions like addstr() and addch().  Very tedious!
c=locale.getpreferredencoding()

colour_header=1
colour_error=1 # white on red
colour_info=2  # black on green
colour_input=3 # white on blue
colour_line=4
colour_cashline=5
colour_changeline=6
colour_cancelline=7
colour_confirm=8 # black on cyan

class clockheader(object):
    """
    A single-line header at the top of the screen, with a clock at the
    right-hand side.  Can be passed text for the top-left and the
    middle.  Draws directly on the curses root window, not into a
    panel.

    """
    def __init__(self,win,left="Quicktill",middle=""):
        self.stdwin=win
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
        (my,mx)=stdwin.getmaxyx()
        def cat(m,s,t):
            w=len(m)+len(s)+len(t)
            pad1=(mx-w)/2
            pad2=pad1
            if w+pad1+pad2!=mx: pad1=pad1+1
            return "%s%s%s%s%s"%(m,' '*pad1,s,' '*pad2,t)
        x=cat(m,s,t)
        while len(x)>mx:
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
    integers from curses (eg. ord('t'))
    user tokens

    They don't always have a 'keycap' method - check the type first!

    """
    log.debug("Keypress %s",k)
    basicwin._focus.hotkeypress(k)

def current_user():
    """
    Look up the focus stack and return the first user information
    found, or None if there is none.

    """
    stack=basicwin._focus.parents()
    for i in stack:
        if hasattr(i,'user'): return i.user

class ignore_hotkeys(object):
    """
    Mixin class for UI elements that disables handling of hotkeys;
    they are passed to the input focus like all other keypresses.

    """
    def hotkeypress(self,k):
        basicwin._focus.keypress(k)

class autodismiss(object):
    """
    Mixin class for UI elements that dismiss themselves after a
    certain number of seconds if they still hold the input focus.

    """
    autodismisstime=10
    def __init__(self,*args,**kwargs):
        self.nexttime=time.time()+self.autodismisstime
        event.eventlist.append(self)
        super(autodismiss,self).__init__(*args,**kwargs)
    def alarm(self):
        if self in event.eventlist:
            del event.eventlist[event.eventlist.index(self)]
        if self in basicwin._focus.parents():
            # Changing the input focus may call code that accesses the
            # database.  When our alarm method is called there's no
            # database session active.  Make one!
            with td.orm_session():
                self.dismiss()
    def dismiss(self):
        if self in event.eventlist:
            del event.eventlist[event.eventlist.index(self)]
        super(autodismiss,self).dismiss()

class basicwin(object):
    """Container for all pages, popup windows and fields.

    It is required that the parent holds the input focus whenever a
    basicwin instance is created.  This should usually be true!
    
    """
    _focus=None
    def __init__(self):
        self.parent=basicwin._focus
        log.debug("New %s with parent %s",self,self.parent)
    def addstr(self,y,x,s,attr=None):
        try:
            if attr is None:
                self.win.addstr(y,x,s.encode(c))
            else:
                self.win.addstr(y,x,s.encode(c),attr)
        except curses.error:
            log.debug("addstr problem: len(s)=%d; s=%s",len(s),repr(s))
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
        if basicpage._basepage: basicpage._basepage.deselect()
        (my,mx)=stdwin.getmaxyx()
        self.win=curses.newwin(my-1,mx,1,0)
        self.pan=curses.panel.new_panel(self.win)
        self.pan.set_userptr(self)
        basicpage._pagelist.append(self)
        (self.h,self.w)=self.win.getmaxyx()
        self.savedfocus=self
        self.stack=None
        basicpage._basepage=self
        basicwin._focus=self
        basicwin.__init__(self) # Sets self.parent to self - ok!
    def pagename(self):
        return "Basic page"
    def pagesummary(self):
        return ""
    def select(self):
        if basicpage._basepage==self: return # Nothing to do
        # Tell the current page we're switching away
        if basicpage._basepage: basicpage._basepage.deselect()
        basicpage._basepage=self
        basicwin._focus=self.savedfocus
        self.pan.show()
        if self.stack:
            for i in self.stack:
                i.show()
        self.savedfocus=None
        self.stack=None
        self.updateheader()
    def deselect(self):
        """
        Deselect this page if it is currently selected.  Save the
        panel stack so we can restore it next time we are selected.

        """
        if basicpage._basepage!=self: return
        self.savedfocus=basicwin._focus
        l=[]
        t=curses.panel.top_panel()
        while t.userptr()!=self:
            st=t
            l.append(t)
            t=t.below()
            st.hide()
        l.reverse()
        self.stack=l
        self.pan.hide()
        basicpage._basepage=None
    def dismiss(self):
        """
        Remove this page.

        """
        if basicpage._basepage==self: self.deselect()
        del self.pan,self.win,self.stack
        del basicpage._pagelist[basicpage._pagelist.index(self)]
    @staticmethod
    def updateheader():
        global header
        m=""
        s=""
        for i in basicpage._pagelist:
            if i==basicpage._basepage: m=i.pagename()+' '
            else:
                ps=i.pagesummary()
                if ps: s=s+i.pagesummary()+' '
        header.update(m,s)
    @staticmethod
    def _ensure_page_exists():
        if basicpage._basepage==None:
            with td.orm_session():
                tillconfig.firstpage()
    def hotkeypress(self,k):
        """
        Since this is a page, it is always at the base of the stack of
        windows - it does not have a parent to pass keypresses on to.
        By default we look at the configured hotkeys and call if
        found; otherwise we pass the keypress on to the current input
        focus for regular keypress processing.

        """
        if k in tillconfig.hotkeys:
            tillconfig.hotkeys[k]()
        elif hasattr(k,'usertoken'):
            tillconfig.usertoken_handler(k)
        else:
            basicwin._focus.keypress(k)

class basicpopup(basicwin):
    def __init__(self,h,w,title=None,cleartext=None,colour=colour_error,
                 keymap={}):
        basicwin.__init__(self)
        # Grab the focus so that we hold it while we create any necessary
        # child UI elements
        self.focus()
        self.keymap=keymap
        (mh,mw)=stdwin.getmaxyx()
        if title: w=max(w,len(title)+3)
        if cleartext: w=max(w,len(cleartext)+3)
        w=min(w,mw)
        h=min(h,mh)
        y=(mh-h)/2
        x=(mw-w)/2
        self.win=curses.newwin(h,w,y,x)
        self.pan=curses.panel.new_panel(self.win)
        self.pan.set_userptr(self)
        self.win.bkgdset(ord(' '),curses.color_pair(colour))
        self.win.clear()
        self.win.border()
        if title: self.addstr(0,1,title)
        if cleartext: self.addstr(h-1,w-1-len(cleartext),cleartext)
        self.pan.show()
    def dismiss(self):
        self.pan.hide()
        del self.pan,self.win
        self.parent.focus()
    def keypress(self,k):
        # We never want to pass unhandled keypresses back to the parent
        # of the popup.
        if k in self.keymap:
            i=self.keymap[k]
            if i[2]: self.dismiss()
            if i[0] is not None:
                if i[1] is None: i[0]()
                else: i[0](*i[1])
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

# itemlist entries are (keycode,desc,func,args)
class keymenu(dismisspopup):
    def __init__(self,itemlist,title="Press a key",colour=colour_input):
        h=len(itemlist)+4
        pw=0 ; tw=0
        km={}
        for keycode,desc,func,args in itemlist:
            promptwidth=len(keycode.keycap)
            textwidth=len(desc)
            if promptwidth>pw: pw=promptwidth
            if textwidth>tw: tw=textwidth
            km[keycode]=(func,args)
        self.menukeys=km
        w=pw+tw+6
        dismisspopup.__init__(self,h,w,title=title,colour=colour)
        (h,w)=self.win.getmaxyx()
        y=2
        for keycode,desc,func,args in itemlist:
            line_colour=colour
            if hasattr(func,"allowed"):
                if not func.allowed(): line_colour=colour_error
            self.addstr(y,2,"%s."%keycode.keycap)
            self.addstr(y,pw+4,desc,curses.color_pair(line_colour))
            y=y+1
        self.win.move(h-1,w-1)
    def keypress(self,k):
        if k in self.menukeys:
            self.dismiss()
            if self.menukeys[k][1]:
                self.menukeys[k][0](*self.menukeys[k][1])
            else:
                self.menukeys[k][0]()
        else:
            dismisspopup.keypress(self,k)

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
        h=sum([len(x.display(w-2)) for x in hl+dl],0)+2
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

class menu(listpopup):
    """
    A popup menu with a list of selections. Selection can be made by
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
        (mh,mw)=stdwin.getmaxyx()
        maxw=mw-4
        maxh=mh-5
        # We want the window to end up as close to 2/3 the maximum width
        # as possible.  Try that first, and only let it go wider if the
        # maximum height is exceeded.
        w=(maxw*2)/3
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

def validate_int(s,c):
    try:
        int(s)
    except:
        return None
    return s
def validate_positive_int(s,c):
    try:
        x=int(s)
        if x<1: return None
    except:
        return None
    return s
def validate_float(s,c):
    if s=='-': return s
    try:
        float(s)
    except:
        return None
    return s
def validate_uppercase(s,c):
    return s.upper()
def validate_lowercase(s,c):
    return s.lower()
def validate_title(s,c):
    return s.title()
def validate_date(s,c):
    def checkdigit(i):
        a=s[i:i+1]
        if len(a)==0: return True
        return a.isdigit()
    def checkdash(i):
        a=s[i:i+1]
        if len(a)==0: return True
        return a=='-'
    if (checkdigit(0) and
        checkdigit(1) and
        checkdigit(2) and
        checkdigit(3) and
        checkdash(4) and
        checkdigit(5) and
        checkdigit(6) and
        checkdash(7) and
        checkdigit(8) and
        checkdigit(9)): return s
    return None

class field(basicwin):
    def __init__(self,keymap={}):
        self.nextfield=None
        self.prevfield=None
        self.sethook=lambda:None
        # We _must_ copy the provided keymap; it is permissible for our
        # keymap to be modified after initialisation, and it would be
        # a Very Bad Thing (TM) for the default empty keymap to be
        # changed!
        self.keymap=keymap.copy()
        basicwin.__init__(self)
        self.win=self.parent.win
    def set(self):
        self.sethook()
    def keypress(self,k):
        # All keypresses handled here are defaults; if they are present
        # in the keymap, we should not handle them ourselves.
        if k in self.keymap:
            i=self.keymap[k]
            if i[0] is not None:
                if i[1] is None: i[0]()
                else: i[0](*i[1])
        elif (k in (keyboard.K_DOWN,keyboard.K_CASH,curses.ascii.TAB)
              and self.nextfield):
            self.nextfield.focus()
        elif (k in (keyboard.K_UP,keyboard.K_CLEAR)
              and self.prevfield):
            self.prevfield.focus()
        else:
            self.parent.keypress(k)

class scrollable(field):
    """A rectangular field of a page or popup that contains a list of
    items that can be scrolled up and down.

    lastline is a special item that, if present, is drawn at the end of
    the list.  In the register this is the prompt/input buffer/total.
    Where the scrollable is being used for entry of a list of items,
    the last line may be blank/inverse as a prompt.

    """
    def __init__(self,y,x,width,height,dl,show_cursor=True,
                 lastline=None,default=0,keymap={}):
        field.__init__(self,keymap)
        self.y=y
        self.x=x
        self.w=width
        self.h=height
        self.dl=dl
        self.show_cursor=show_cursor
        self.lastline=lastline
        self.cursor=default
        self.top=0
        self.redraw()
    def set(self,dl):
        self.dl=dl
        if self.cursor>=len(self.dl): self.cursor=max(0,len(self.dl)-1)
        self.sethook()
        self.redraw()
    def focus(self):
        # If we are obtaining the focus from the previous field, we should
        # move the cursor to the top.  If we are obtaining it from the next
        # field, we should move the cursor to the bottom.  Otherwise we
        # leave the cursor untouched.
        if self.prevfield and self.prevfield.focused: self.cursor=0
        elif self.nextfield and self.nextfield.focused:
            self.cursor=len(self.dl) if self.lastline else len(self.dl)-1
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
        if self.cursor<self.top or self.show_cursor==False:
            self.top=self.cursor
        lastitem=self.drawdl()
        while self.cursor>lastitem:
            self.top=self.top+1
            lastitem=self.drawdl()
        end_of_displaylist=len(self.dl)+1 if self.lastline else len(self.dl)
        self.display_complete=(lastitem==end_of_displaylist-1)
    def cursor_up(self,n=1):
        if self.cursor==0:
            if self.prevfield is not None and self.focused:
                return self.prevfield.focus()
        else:
            self.cursor=self.cursor-n
            if self.cursor<0: self.cursor=0
        self.redraw()
    def cursor_at_end(self):
        if self.show_cursor:
            if self.lastline:
                return self.cursor>=len(self.dl)
            else:
                return self.cursor==len(self.dl)-1
        else:
            return self.display_complete
    def cursor_on_lastline(self):
        return self.cursor==len(self.dl)
    def cursor_down(self,n=1):
        if self.cursor_at_end():
            if self.nextfield is not None and self.focused:
                return self.nextfield.focus()
        else:
            self.cursor=self.cursor+n
            if self.lastline:
                if self.cursor>len(self.dl): self.cursor=len(self.dl)
            else:
                if self.cursor>=len(self.dl):
                    self.cursor=len(self.dl)-1 if len(self.dl)>0 else 0
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
    """
    A line for use in a scrollable.  Has a natural colour, a "cursor
    is here" colour, an optional "selected" colour, some left-aligned
    text (which will be wrapped if it is too long) and optionally some
    right-aligned text.

    """
    def __init__(self,ltext="",rtext="",colour=None,userdata=None):
        emptyline.__init__(self,colour)
        self.ltext=ltext
        self.rtext=rtext
    def idealwidth(self):
        return len(self.ltext)+(len(self.rtext)+1 if len(self.rtext)>0 else 0)
    def display(self,width):
        """
        Returns a list of lines, formatted to the specified maximum
        width.  If there is right-aligned text it is included along
        with the text on the last line if there is space; otherwise a
        new line is added with the text at the right.

        """
        # After display has been called, the caller can read 'cursor' to
        # find our preferred location for the cursor if we are selected.
        # It's a (x,y) tuple where y is 0 for the first line.
        self.cursor=(0,0)
        w=textwrap.wrap(self.ltext,width)
        if len(w)==0: w=[""]
        if len(w[-1])+len(self.rtext)>=width:
            w.append("")
        w[-1]=w[-1]+(' '*(width-len(w[-1])-len(self.rtext)))+self.rtext
        return w

class tableformatter(object):
    """
    This class implements policy for formatting a table.  The format
    string is used as-is with the following characters being replaced:

    l - left-aligned field
    c - centered field
    r - right-aligned string
    p - padding
    
    """
    def __init__(self,format):
        self._f=format
        self._rows=[] # Doesn't need to be kept in order
        self._formats={}
        self._colwidths=None
        # Remove the formatting characters from the format and see
        # what's left
        f=format
        f=f.replace('l','')
        f=f.replace('c','')
        f=f.replace('r','')
        f=f.replace('p','')
        self._formatlen=len(f)
    def __call__(self,*args,**kwargs):
        """Append a line to the table.  Positional arguments are used as table
        fields, and keyword arguments are passed to the underlying
        line object eg. for colour and userdata.

        """
        return tableline(self,args,**kwargs)
    def append(self,row):
        """
        Add a row to the table.

        """
        self._rows.append(row)
        self.update(row)
    def update(self,row):
        """
        Called when a row is changed.  Invalidate any cached widths
        and format strings.

        """
        self._formats={}
        self._colwidths=None
    @property
    def colwidths(self):
        """
        List of column widths.

        """
        if not self._colwidths:
            # Each row has a list of fields.  We want to rearrange
            # this so we have a list of columns.
            cols=zip(*(r.fields for r in self._rows))
            self._colwidths=[max(len(f) for f in c) for c in cols]
        return self._colwidths
    def idealwidth(self):
        return self._formatlen+sum(self.colwidths)
    def _formatstr(self,width):
        """
        Return a format template for the given width.

        """
        if width in self._formats: return self._formats[width]
        w=list(self.colwidths) # copy
        r=[]
        pads=self._f.count("p")
        if pads>0:
            total_to_pad=max(0,width-self.idealwidth())
            pw=total_to_pad/pads
            odd=total_to_pad%pads
            pads=[pw+1]*odd+[pw]*(pads-odd)
        else:
            pads=[]
        for i in self._f:
            if i=='l':
                r.append("{:<%d}"%w.pop(0))
            elif i=='c':
                r.append("{:^%d}"%w.pop(0))
            elif i=='r':
                r.append("{:>%d}"%w.pop(0))
            elif i=="p":
                r.append(" "*pads.pop(0))
            else:
                r.append(i)
        fs=''.join(r)
        self._formats[width]=fs
        return fs
    def format(self,row,width):
        return [self._formatstr(width).format(*row.fields)[:width]]

class tableline(emptyline):
    def __init__(self,formatter,fields,colour=None,userdata=None):
        emptyline.__init__(self,colour,userdata)
        self._formatter=formatter
        self.fields=[unicode(x) for x in fields]
        self._formatter.append(self)
    def update(self):
        emptyline.update(self)
        self._formatter.update(self)
    def idealwidth(self):
        return self._formatter.idealwidth()
    def display(self,width):
        self.cursor=(0,0)
        return self._formatter.format(self,width)

class booleanfield(field):
    """
    A field that can be either True or False, displayed as Yes or No.
    Also has an optional "blank" state which will be read back as
    None.

    """
    def __init__(self,y,x,keymap={},f=None,readonly=False,allow_blank=True):
        field.__init__(self,keymap)
        self.y=y
        self.x=x
        self.readonly=readonly
        self.allow_blank=allow_blank
        self.set(f)
    def focus(self):
        field.focus(self)
        self.draw()
    def set(self,l):
        self.f=l
        if not self.allow_blank: self.f=not not self.f
        self.sethook()
        self.draw()
    def draw(self):
        pos=self.win.getyx()
        if self.f is None: s="   "
        else: s="Yes" if self.f else "No "
        pos=self.win.getyx()
        self.addstr(self.y,self.x,s,curses.A_REVERSE)
        if self.focused: self.win.move(self.y,self.x)
        else: self.win.move(*pos)
    def keypress(self,k):
        if k in (ord('y'),ord('Y'),keyboard.K_ONE):
            self.set(True)
        elif k in (ord('n'),ord('N'),keyboard.K_ZERO,keyboard.K_ZEROZERO):
            self.set(False)
        elif k==keyboard.K_CLEAR and self.allow_blank and self.f is not None:
            self.set(None)
        else:
            field.keypress(self,k)
                
class editfield(field):
    """Accept input in a field.  Processes an implicit set of keycodes; when an
    unrecognised code is found processing moves to the standard keymap."""
    def __init__(self,y,x,w,keymap={},f=None,flen=None,validate=None,
                 readonly=False):
        """flen, if not None, is the maximum length of input allowed in the
        field.  If this is greater than w then the field will scroll
        if necessary.  If validate is not none it will be called on
        every insertion into the field; it should return either a
        (potentially updated) string or None if the input is not
        allowed.

        """
        self.y=y
        self.x=x
        self.w=w
        if flen is None: flen=w
        self.flen=flen
        self.validate=validate
        self.readonly=readonly
        field.__init__(self,keymap)
        self.set(f)
    def focus(self):
        field.focus(self)
        if self.c>len(self.f): self.c=len(self.f)
        self.draw()
    def set(self,l):
        if l is None: l=""
        l=str(l)
        if len(l)>self.flen: l=l[:self.flen]
        self.f=l
        self.c=len(self.f)
        self.i=0 # will be updated by draw() if necessary
        self.sethook()
        self.draw()
    def draw(self):
        if self.c-self.i>self.w:
            self.i=self.c-self.w
        if self.c<self.i: self.i=self.c
        self.addstr(self.y,self.x,' '*self.w,curses.A_REVERSE)
        self.addstr(self.y,self.x,self.f[self.i:self.i+self.w],
                        curses.A_REVERSE)
        self.win.move(self.y,self.x+self.c-self.i)
    def insert(self,s):
        if self.readonly:
            curses.beep()
            return
        trial=self.f[:self.c]+s+self.f[self.c:]
        if self.validate is not None: trial=self.validate(trial,self.c)
        if trial is not None and len(trial)>self.flen: trial=None
        if trial is not None:
            self.f=trial
            self.c=self.c+len(s)
            if self.c>len(self.f):
                self.c=len(self.f)
            self.sethook()
            self.draw()
        else:
            curses.beep()
    def backspace(self):
        "Delete the character to the left of the cursor"
        if self.c>0 and not self.readonly:
            self.f=self.f[:self.c-1]+self.f[self.c:]
            self.move_left()
            self.sethook()
            self.draw()
        else: curses.beep()
    def delete(self):
        "Delete the character under the cursor"
        if self.c<len(self.f) and not self.readonly:
            self.f=self.f[:self.c]+self.f[self.c+1:]
            self.sethook()
            self.draw()
        else: curses.beep()
    def move_left(self):
        if self.c==0: curses.beep()
        self.c=max(self.c-1,0)
        self.draw()
    def move_right(self):
        if self.c==len(self.f): curses.beep()
        self.c=min(self.c+1,len(self.f))
        self.draw()
    def home(self):
        self.c=0
        self.draw()
    def end(self):
        self.c=len(self.f)
        self.draw()
    def clear(self):
        self.f=""
        self.c=0
        self.sethook()
        self.draw()
    def killtoeol(self):
        if self.readonly:
            curses.beep()
            return
        self.f=self.f[:self.c]
        self.sethook()
        self.draw()
    def keypress(self,k):
        # Valid keys are numbers, point, any letter or number from the
        # normal keypad
        if k in keyboard.numberkeys:
            self.insert(k.keycap)
        elif curses.ascii.isprint(k):
            self.insert(chr(k))
        elif k==curses.KEY_BACKSPACE:
            self.backspace()
        elif k==curses.KEY_DC or k==4:
            self.delete()
        elif k==keyboard.K_LEFT:
            self.move_left()
        elif k==keyboard.K_RIGHT:
            self.move_right()
        elif k==curses.KEY_HOME or k==1:
            self.home()
        elif k==curses.KEY_END or k==5:
            self.end()
        elif k==curses.KEY_EOL or k==11:
            self.killtoeol()
        elif k==keyboard.K_CLEAR and self.f!="" and not self.readonly:
            self.clear()
        else:
            field.keypress(self,k)

class datefield(editfield):
    def __init__(self,y,x,keymap={},f=None,flen=None,readonly=False):
        if f is not None:
            f=formatdate(f)
        editfield.__init__(self,y,x,10,keymap=keymap,f=f,flen=10,
                           readonly=readonly,validate=validate_date)
    def set(self,v):
        if hasattr(v,'strftime'):
            editfield.set(self,formatdate(v))
        else:
            editfield.set(self,v)
    def read(self):
        try:
            d=datetime.datetime.strptime(self.f,"%Y-%m-%d")
        except:
            d=None
        return d
    def draw(self):
        self.addstr(self.y,self.x,'YYYY-MM-DD',curses.A_REVERSE)
        self.addstr(self.y,self.x,self.f,curses.A_REVERSE)
        self.win.move(self.y,self.x+self.c)
    def insert(self,s):
        editfield.insert(self,s)
        if len(self.f)==4 or len(self.f)==7:
            self.set(self.f+'-')

class popupfield(field):
    """
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
    def __init__(self,y,x,w,popupfunc,valuefunc,f=None,keymap={},
                 readonly=False):
        """
        f is the default value, and must be a database model.

        """
        self.y=y
        self.x=x
        self.w=w
        self.popupfunc=popupfunc
        self.valuefunc=valuefunc
        self.readonly=readonly
        field.__init__(self,keymap)
        self.f=f
        self.draw()
    def focus(self):
        field.focus(self)
        self.draw()
    def set(self,value):
        self.f=value
        self.sethook()
        self.draw()
    def read(self):
        if self.f is None: return None
        # We have to be careful here: self.f is very likely to be a
        # detached instance, and there's no guarantee that another
        # instance with the same primary key has not already been
        # loaded into the current session.  Get via primary key
        # instead of just doing td.s.add()
        self.f=td.s.merge(self.f)
        return self.f
    def setf(self,value):
        self.set(value)
        if self.nextfield: self.nextfield.focus()
    def draw(self):
        if self.f is not None:
            td.s.add(self.f)
            s=self.valuefunc(self.f)
        else: s=""
        if len(s)>self.w: s=s[:self.w]
        self.addstr(self.y,self.x,' '*self.w,curses.A_REVERSE)
        self.addstr(self.y,self.x,s,curses.A_REVERSE)
        self.win.move(self.y,self.x)
    def popup(self):
        if not self.readonly: self.popupfunc(self.setf,self.f)
    def keypress(self,k):
        if k==keyboard.K_CLEAR and self.f is not None and not self.readonly:
            self.set(None)
        elif k==keyboard.K_CASH and not self.readonly:
            self.popup()
        else:
            field.keypress(self,k)

class listfield(popupfield):
    """
    A field which allows a model to be chosen from a list of models.
    The list is ordered: for any particular value there is a concept
    of "next" and "previous".

    A function d can be provided; if it is, then d(model) is expected
    to return a suitable string for display.  If it is not then
    unicode(model) is called to obtain a string.

    """
    def __init__(self,y,x,w,l,d=unicode,f=None,keymap={},readonly=False):
        # We copy the list because we're going to modify it in-place
        # whenever we refresh from the database
        self.l=list(l)
        self.d=d
        popupfield.__init__(self,y,x,w,self._popuplist,d,
                            f=f,keymap=keymap,readonly=readonly)
    def _update_list(self):
        self.l=[td.s.merge(x) for x in self.l]
    def _popuplist(self,func,default):
        self._update_list()
        self.read()
        try:
            default=self.l.index(self.f)
        except ValueError:
            pass
        m=[(self.valuefunc(x),func,(x,)) for x in self.l]
        menu(m,colour=colour_line,default=default)
    def change_list(self,l):
        """
        Replace the current list of models with a new one.  If the
        currently chosen model is in the list, keep it; otherwise,
        select the first model from the new list.
        
        """
        self.l=l
        self.read()
        if self.f in l:
            return
        if len(l)>0:
            self.f=l[0]
        else:
            self.f=None
        self.sethook()
        self.draw()
    def nextitem(self):
        self._update_list()
        self.read()
        if self.f in self.l:
            ni=self.l.index(self.f)+1
            if ni>=len(self.l): ni=0
            self.f=self.l[ni]
        else:
            if len(self.l)>0: self.f=self.l[0]
        self.sethook()
        self.draw()
    def previtem(self):
        self._update_list()
        self.read()
        if self.f in self.l:
            pi=self.l.index(self.f)-1
            self.f=self.l[pi]
        else:
            if len(self.l)>0: self.f=self.l[-1]
        self.sethook()
        self.draw()
    def keypress(self,k):
        if not self.readonly:
            if k==keyboard.K_RIGHT: return self.nextitem()
            elif k==keyboard.K_LEFT: return self.previtem()
        popupfield.keypress(self,k)

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
    def __init__(self,description,title=None):
        self._description="There was a problem while {}.".format(description)
        self._title=title if title else "Error"
    def __enter__(self):
        return self
    def __exit__(self,type,value,tb):
        if tb is None: return
        exception_popup(self._description,self._title,type,value,tb)
        return True

def init(w):
    global stdwin,header
    stdwin=w
    (my,mx)=stdwin.getmaxyx()
    curses.init_pair(1,curses.COLOR_WHITE,curses.COLOR_RED)
    curses.init_pair(2,curses.COLOR_BLACK,curses.COLOR_GREEN)
    curses.init_pair(3,curses.COLOR_WHITE,curses.COLOR_BLUE)
    curses.init_pair(4,curses.COLOR_BLACK,curses.COLOR_YELLOW)
    curses.init_pair(5,curses.COLOR_GREEN,curses.COLOR_BLACK)
    curses.init_pair(6,curses.COLOR_YELLOW,curses.COLOR_BLACK)
    curses.init_pair(7,curses.COLOR_BLUE,curses.COLOR_BLACK)
    curses.init_pair(8,curses.COLOR_BLACK,curses.COLOR_CYAN)
    header=clockheader(stdwin)
    event.ticklist.append(basicpage._ensure_page_exists)

beep=curses.beep
