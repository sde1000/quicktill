# This module manages the display - the header line, clock, popup
# windows, and so on.

import curses,curses.ascii,time,math,sys,string,textwrap,traceback,locale
from . import keyboard,event

from mx.DateTime import now,strptime

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

# The page having the input focus - at top of stack
focus=None
# The page at the bottom of the stack
basepage=None

# Hotkeys for switching between pages.
hotkeys={}

# List of pages, in order
pagelist=[]

def wrap_addstr(win,y,x,str,attr=None):
    if attr is None:
        win.addstr(y,x,str.encode(c))
    else:
        win.addstr(y,x,str.encode(c),attr)

def gettime():
    return time.strftime("%a %d %b %Y %H:%M:%S %Z")

class clock(object):
    def __init__(self,win):
        self.stdwin=win
        self.alarm()
    def alarm(self):
        drawheader()
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

def savefocus():
    "Save the current panel stack down to the base panel"
    l=[]
    t=curses.panel.top_panel()
    while t.userptr()!=basepage:
        st=t
        l.append(t)
        t=t.below()
        st.hide()
    l.reverse()
    return l

header_pagename=""
header_summary=""
def drawheader():
    """
    The header line consists of the name of the page at the left, a
    number of "summary" sections from all the other pages separated by
    spaces in the center, and the clock at the right.  If we do not
    have enough space, we truncate the summary section until we do.
    If we still don't, we truncate the page name.

    """
    m=header_pagename
    s=header_summary
    t=gettime()
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
    stdwin.addstr(0,0,x.encode(c),curses.color_pair(colour_header))

def updateheader():
    global header_pagename,header_summary
    m=""
    s=""
    for i in pagelist:
        if i==basepage: m=i.pagename()+' '
        else:
            ps=i.pagesummary()
            if ps!="": s=s+i.pagesummary()+' '
    header_pagename=m
    header_summary=s
    drawheader()

# Switch to a VC
def selectpage(page):
    global focus,basepage
    if page==basepage: return # Nothing to do
    # Tell the current page we're switching away
    if basepage:
        basepage.deselected(focus,savefocus())
    focus=page
    basepage=page
    updateheader()
    page.selected()

def handle_keyboard_input(k):
    global focus
    log.debug("Keypress %s"%kb.keycap(k))
    if k in hotkeys:
        selectpage(hotkeys[k])
    else:
        focus.keypress(k)

class basicwin(object):
    """Container for all pages, popup windows and fields.

    It is required that the parent holds the input focus whenever a
    basicwin instance is created.  This should usually be true!
    
    """
    def __init__(self):
        global focus
        self.parent=focus
        log.debug("New %s with parent %s"%(self,self.parent))
    def addstr(self,y,x,s,attr=None):
        wrap_addstr(self.win,y,x,s,attr)
    def focus(self):
        """Called when we are being told to take the focus.

        """
        global focus
        if focus!=self:
            oldfocus=focus
            focus=self
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

class basicpage(basicwin):
    def __init__(self,pan):
        self.pan=pan
        self.win=pan.window()
        self.savedfocus=self
        self.stack=None
        (self.h,self.w)=self.win.getmaxyx()
        # Pages are only ever initialised during startup, when there
        # is no focus.  The page must hold the focus so that UI
        # elements can determine their parent correctly, for keypress
        # handling.
        global focus
        focus=self
        basicwin.__init__(self) # Sets self.parent to self - ok!
    def firstpageinit(self):
        # Startup code will call this function on the first page to be
        # initialised, after all other pages have been initialised and
        # the first page has been brought to the top.
        pass
    def pagename(self):
        return "Basic page"
    def pagesummary(self):
        return ""
    def deselected(self,focus,stack):
        # When we're deselected this function is called to let us save
        # our stack of panels, if we want to.  Then when selected we
        # can just restore the focus and panel stack.
        self.savedfocus=focus
        self.stack=stack
    def selected(self):
        global focus
        self.pan.show()
        focus=self.savedfocus
        if self.stack:
            for i in self.stack:
                i.show()
        self.savedfocus=self
        self.stack=None

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
        self.pan=popup(self,h,w)
        self.win=self.pan.window()
        self.win.bkgdset(ord(' '),curses.color_pair(colour))
        self.win.clear()
        self.win.border()
        if title: self.addstr(0,1,title)
        if cleartext: self.addstr(h-1,w-1-len(cleartext),cleartext)
        self.pan.show()
    def dismiss(self):
        self.pan.hide()
        del self.pan
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
                return "Press %s to dismiss"%kb.keycap(dismiss)
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
            promptwidth=len(kb.keycap(keycode))
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
            self.addstr(y,2,"%s."%kb.keycap(keycode))
            self.addstr(y,pw+4,desc)
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
                 colour=colour_input,w=None,keymap={}):
        dl=[x if isinstance(x,emptyline) else line(x) for x in linelist]
        hl=[x if isinstance(x,emptyline) else marginline(lrline(x),margin=1)
            for x in header] if header else []
        if w is None:
            w=max((x.idealwidth() for x in dl))+2 if len(linelist)>0 else 0
            w=max(25,w)
        if title is not None:
            w=max(len(title)+3,w)
        hh=sum([len(x.display(w-2)) for x in hl],0)
        h=len(linelist)+hh+2
        dismisspopup.__init__(self,h,w,title=title,colour=colour,keymap=keymap)
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
            self.s=scrollable(y,1,w-2,h-y-1,dl)
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
        listpopup.__init__(self,dl,default=default,
                           header=[blurb] if blurb else None,title=title,
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

class linepopup(dismisspopup):
    def __init__(self,lines=[],title=None,dismiss=keyboard.K_CLEAR,
                 cleartext=None,colour=colour_error,keymap={},
                 headerlines=0):
        (mh,mw)=stdwin.getmaxyx()
        w=max(len(i) for i in lines)
        w=min(w+4,mw)
        h=min(len(lines)+2,mh)
        dismisspopup.__init__(self,h,w,title,cleartext,colour,dismiss,
                              keymap)
        y=1
        while headerlines>0 and len(lines)>0:
            self.addstr(y,2,lines[0][:w-4])
            del lines[0]
            y=y+1
            h=h-1
            headerlines=headerlines-1
        dl=[line(i) for i in lines]
        self.s=scrollable(y,2,w-4,h-2,dl,show_cursor=False)
        self.s.focus()

class infopopup(linepopup):
    """A pop-up box that formats and displays text.  The text parameter is
    a list of paragraphs."""
    # Implementation note: we _could_ use a scrollable with a list of
    # lrlines; however, we have to work out how big to make the window
    # anyway, and once we've done that we already have a list of lines
    # suitable to pass to linepopup.__init__()
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
        # The first line of spaces is necessary because linepopup shrinks
        # the window to fit the longest line of text
        padding=" "*w
        t=[padding]+t+[""]
        linepopup.__init__(self,t,title,dismiss,cleartext,colour,keymap)

class alarmpopup(infopopup):
    """This is like an infopopup, but goes "beep" every second until
    it is dismissed.  It dismisses itself after 5 minutes, provided it
    still has the input focus.  (If it doesn't have the focus,
    dismissing would put the focus in the wrong place - potentially on
    a different page, which would be VERY confusing for the user!)

    """
    def __init__(self,*args,**kwargs):
        infopopup.__init__(self,*args,**kwargs)
        self.mainloopnexttime=0
        self.remaining=300
        event.eventlist.append(self)
        self.alarm()
    def alarm(self):
        global focus
        curses.beep()
        self.nexttime=math.ceil(time.time())
        self.remaining=self.remaining-1
        if self.remaining<1:
            self.remaining=10
            if self in focus.parents(): self.dismiss()
    def dismiss(self):
        del event.eventlist[event.eventlist.index(self)]
        infopopup.dismiss(self)

def validate_int(s,c):
    try:
        int(s)
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
        self.sethook=None
        # We _must_ copy the provided keymap; it is permissible for our
        # keymap to be modified after initialisation, and it would be
        # a Very Bad Thing (TM) for the default empty keymap to be
        # changed!
        self.keymap=keymap.copy()
        basicwin.__init__(self)
        self.win=self.parent.win
    def set(self):
        if self.sethook is not None: self.sethook()
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
        self.drawdl()
    def set(self,dl):
        self.dl=dl
        if self.cursor>=len(self.dl): self.cursor=max(0,len(self.dl)-1)
        self.redraw()
        field.set(self)
    def focus(self):
        # If we are obtaining the focus from the previous field, we should
        # move the cursor to the top.  If we are obtaining it from the next
        # field, we should move the cursor to the bottom.  Otherwise we
        # leave the cursor untouched.
        global focus
        if focus==self.prevfield: self.cursor=0
        elif focus==self.nextfield:
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
        global focus
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
            if focus==self and i==self.cursor and self.show_cursor:
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
            if self.prevfield is not None: return self.prevfield.focus()
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
            if self.nextfield is not None: return self.nextfield.focus()
        else:
            self.cursor=self.cursor+n
            if self.lastline:
                if self.cursor>len(self.dl): self.cursor=len(self.dl)
            else:
                if self.cursor>=len(self.dl): self.cursor=len(self.dl)-1
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
        self.colour=colour
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
    This class implements policy for formatting a table.
    
    """
    def __init__(self,format):
        self.f=format
        self.lines=[]
        self.colwidths=None
        # Remove formatting characters from format and see what's left
        f=format
        f=f.replace('l','')
        f=f.replace('c','')
        f=f.replace('r','')
        self.formatlen=len(f)
    def update(self,line):
        if self.colwidths is None:
            self.colwidths=[0]*len(line.fields)
        self.colwidths=[max(a,len(b))
                        for a,b in zip(self.colwidths,line.fields)]
    def idealwidth(self):
        return self.formatlen+sum(self.colwidths)
    def addline(self,line):
        self.lines.append(line)
        self.update(line)
    def format(self,line,width):
        r=[]
        n=0
        for i in self.f:
            if i=='l':
                r.append(line.fields[n].ljust(self.colwidths[n]))
                n=n+1
            elif i=='c':
                r.append(line.fields[n].center(self.colwidths[n]))
                n=n+1
            elif i=='r':
                r.append(line.fields[n].rjust(self.colwidths[n]))
                n=n+1
            else:
                r.append(i)
        return [''.join(r)[:width]]

class tableline(emptyline):
    def __init__(self,formatter,fields,colour=None,userdata=None):
        emptyline.__init__(self,colour,userdata)
        self.formatter=formatter
        self.fields=fields
        self.formatter.addline(self)
    def update(self):
        emptyline.update(self)
        self.formatter.update(self)
    def idealwidth(self):
        return self.formatter.idealwidth()
    def display(self,width):
        self.cursor=(0,0)
        return self.formatter.format(self,width)
    
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
        self.draw()
        field.set(self)
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
            self.draw()
        else:
            curses.beep()
    def backspace(self):
        "Delete the character to the left of the cursor"
        if self.c>0 and not self.readonly:
            self.f=self.f[:self.c-1]+self.f[self.c:]
            self.move_left()
            self.draw()
        else: curses.beep()
    def delete(self):
        "Delete the character under the cursor"
        if self.c<len(self.f) and not self.readonly:
            self.f=self.f[:self.c]+self.f[self.c+1:]
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
        self.draw()
    def killtoeol(self):
        if self.readonly:
            curses.beep()
            return
        self.f=self.f[:self.c]
        self.draw()
    def keypress(self,k):
        # Valid keys are numbers, point, any letter or number from the
        # normal keypad
        if k in keyboard.numberkeys:
            self.insert(kb.keycap(k))
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
            if k==keyboard.K_CASH:
                # Invoke the 'set' hook, and then do whatever Cash would
                # have done anyway
                field.set(self)
            field.keypress(self,k)

class datefield(editfield):
    def __init__(self,y,x,keymap={},f=None,flen=None,readonly=False):
        if f is not None:
            f=formatdate(f)
        editfield.__init__(self,y,x,10,keymap=keymap,f=f,flen=10,
                           readonly=readonly,validate=validate_date)
    def set(self,v):
        if isinstance(v,str):
            editfield.set(self,v)
        else:
            editfield.set(self,formatdate(v))
    def read(self):
        try:
            d=strptime(self.f,"%Y-%m-%d")
        except:
            d=None
        if d is None: editfield.set(self,"")
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
    """A field which has its value set using a popup dialog.  The
    values the field can take are unordered; there is no concept of
    "next" and "previous".  The field can also be null.

    popupfunc is a function that takes two arguments: the function to
    call when a value is chosen, and the current value of the field.
    
    valuefunc is a function that takes one argument: the current value
    of the field.  It returns a string to display.  It is never passed
    None as an argument.

    """
    def __init__(self,y,x,w,popupfunc,valuefunc,f=None,keymap={},
                 readonly=False):
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
        self.draw()
        field.set(self)
    def setf(self,value):
        self.set(value)
        if self.nextfield: self.nextfield.focus()
    def draw(self):
        if self.f is not None: s=self.valuefunc(self.f)
        else: s=""
        if len(s)>self.w: s=s[:self.w]
        self.addstr(self.y,self.x,' '*self.w,curses.A_REVERSE)
        self.addstr(self.y,self.x,s,curses.A_REVERSE)
        self.win.move(self.y,self.x)
    def popup(self):
        if not self.readonly: self.popupfunc(self.setf,self.f)
    def keypress(self,k):
        if k==keyboard.K_CLEAR and self.f is not None and not self.readonly:
            self.f=None
            self.draw()
        elif k==keyboard.K_CASH and not self.readonly:
            self.popup()
        else:
            field.keypress(self,k)

class listfield(popupfield):
    """A field which allows a value to be chosen from a list.  The
    list is ordered: for any particular value there is a concept of
    "next" and "previous".  self.f is an index into the list, or None;
    self.read() returns the value of the item in the list or None.

    A dictionary d can be provided; if it is, then values in l are looked
    up in d before being displayed.

    """
    def __init__(self,y,x,w,l,d=None,f=None,keymap={},readonly=False):
        self.l=l
        self.d=d
        popupfield.__init__(self,y,x,w,self.popuplist,
                            self.listval,f=f,keymap=keymap,readonly=readonly)
    def read(self):
        if self.f is None: return None
        return self.l[self.f]
    def listval(self,index):
        if self.d is not None:
            return self.d[self.l[index]]
        return unicode(self.l[index])
    def popuplist(self,func,default):
        m=[]
        for i in range(0,len(self.l)):
            m.append((self.listval(i),func,(i,)))
        menu(m,colour=colour_line,default=default)
    def next(self):
        if self.f is None: self.f=0
        else: self.f=self.f+1
        if self.f>=len(self.l): self.f=0
        self.draw()
    def prev(self):
        if self.f is None: self.f=len(self.l)-1
        else: self.f=self.f-1
        if self.f<0: self.f=len(self.l)-1
        self.draw()
    def keypress(self,k):
        if not self.readonly:
            if k==keyboard.K_RIGHT: return self.next()
            elif k==keyboard.K_LEFT: return self.prev()
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
        global focus
        if focus==self: s="[%s]"%self.t
        else: s=" %s "%self.t
        pos=self.win.getyx()
        self.addstr(self.y,self.x,s,curses.A_REVERSE)
        if focus==self: self.win.move(self.y,self.x)
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

class table(object):
    """A 2d table.  Can be turned into a list of strings of identical
    length, with the columns lined up and justified.

    """
    def __init__(self,rows=[]):
        self.rows=rows
    def append(self,row):
        self.rows.append(row)
    def format(self,cols):
        """cols is a format string; all characters are passed through except
        'l','c','r' which left-, center- or right-align a column.  This
        function returns a list of strings.

        """
        if len(self.rows)==0: return []
        numcols=len(self.rows[0])
        colw=[0]*numcols
        for i in self.rows:
            colw=[max(a,len(b)) for a,b in zip(colw,i)]
        def formatline(c):
            r=[]
            n=0
            for i in cols:
                if i=='l':
                    r.append(c[n].ljust(colw[n]))
                    n=n+1
                elif i=='c':
                    r.append(c[n].center(colw[n]))
                    n=n+1
                elif i=='r':
                    r.append(c[n].rjust(colw[n]))
                    n=n+1
                else:
                    r.append(i)
            return ''.join(r)
        return [ formatline(x) for x in self.rows ]
                
def popup_exception(title):
    e=traceback.format_exception(sys.exc_info()[0],sys.exc_info()[1],
                                 sys.exc_info()[2])
    infopopup(e,title=title)

def addpage(page,hotkey,args=()):
    (my,mx)=stdwin.getmaxyx()
    win=curses.newwin(my-1,mx,1,0)
    pan=curses.panel.new_panel(win)
    p=page(pan,*args)
    pan.set_userptr(p)
    hotkeys[hotkey]=p
    pagelist.append(p)
    return p

def popup(page,h=0,w=0,y=0,x=0):
    # Convenience function: returns a panel of suitable size
    (my,mx)=stdwin.getmaxyx()
    if h==0: h=my/2
    if w==0: w=mx/2
    if y==0: y=(my-h)/2
    if x==0: x=(mx-w)/2
    win=curses.newwin(h,w,y,x)
    pan=curses.panel.new_panel(win)
    pan.set_userptr(page)
    return pan

def init(w):
    global stdwin,kb
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
    stdwin.addstr(0,0," "*mx,curses.color_pair(1))
    event.eventlist.append(clock(stdwin))
    kb.initUI(handle_keyboard_input,stdwin)

beep=curses.beep
