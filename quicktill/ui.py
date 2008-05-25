# This module manages the display - the header line, clock, popup
# windows, and so on.

import curses,curses.ascii,time,math,keyboard,sys,string,textwrap
import event,locale

from mx.DateTime import now,strptime

import logging
log=logging.getLogger()

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

class clock:
    def __init__(self,win):
        self.stdwin=win
    def nexttime(self):
        now=time.time()
        return math.ceil(now)
    def alarm(self):
        drawheader()

def formattime(ts):
    "Returns ts formatted as %Y/%m/%d %H:%M:%S"
    if ts is None: return ""
    return ts.strftime("%Y/%m/%d %H:%M:%S")

def formatdate(ts):
    "Returns ts formatted as %Y/%m/%d"
    if ts is None: return ""
    return ts.strftime("%Y/%m/%d")

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

class basicpage:
    def __init__(self,pan):
        self.pan=pan
        self.win=pan.window()
        self.focus=self
        self.stack=[]
        (self.h,self.w)=self.win.getmaxyx()
    def addstr(self,y,x,s,attr=None):
        wrap_addstr(self.win,y,x,s,attr)
    def pagename(self):
        return "Basic page"
    def pagesummary(self):
        return ""
    def deselected(self,focus,stack):
        # When we're deselected this function is called to let us save
        # our stack of panels, if we want to.  Then when selected we
        # can just restore the focus and panel stack.
        self.focus=focus
        self.stack=stack
    def selected(self):
        global focus
        self.pan.show()
        focus=self.focus
        if self.stack:
            for i in self.stack:
                i.show()
        self.focus=self
        self.stack=None
    def keypress(self,k):
        pass

class basicwin:
    def __init__(self,keymap={},takefocus=True):
        self.keymap=keymap.copy()
        if takefocus: self.focus()
    def addstr(self,y,x,s,attr=None):
        wrap_addstr(self.win,y,x,s,attr)
    def focus(self):
        global focus
        self.parent=focus
        focus=self
    def dismiss(self):
        global focus
        focus=self.parent
    def keypress(self,k):
        if k in self.keymap:
            i=self.keymap[k]
            if i[2]: self.dismiss()
            if i[0] is not None:
                if i[1] is None: i[0]()
                else: i[0](*i[1])
        else:
            curses.beep()

class basicpopup(basicwin):
    def __init__(self,h,w,title=None,cleartext=None,colour=colour_error,
                 keymap={}):
        basicwin.__init__(self,keymap)
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
        basicwin.dismiss(self)

class dismisspopup(basicpopup):
    """Adds processing of an implicit 'Dismiss' key and generation of
    the cleartext prompt"""
    def __init__(self,h,w,title=None,cleartext=None,colour=colour_error,
                 dismiss=keyboard.K_CLEAR,keymap={}):
        km=keymap.copy()
        km[dismiss]=(None,None,True)
        basicpopup.__init__(self,h,w,title=title,
                            cleartext=self.get_cleartext(cleartext,dismiss),
                            colour=colour,keymap=km)
    def get_cleartext(self,cleartext,dismiss):
        if cleartext is None:
            if dismiss==keyboard.K_CLEAR:
                return "Press Clear to go back"
            elif dismiss==keyboard.K_CASH:
                return "Press Cash/Enter to continue"
            else:
                return "Press %s to dismiss"%kb.keycap(dismiss)
        return cleartext

# itemlist entries are (keycode,desc,func,args)
class keymenu(basicpopup):
    def __init__(self,itemlist,title="Press a key",clear=True,
                 colour=colour_input):
        h=len(itemlist)+4
        pw=0 ; tw=0
        km={}
        for keycode,desc,func,args in itemlist:
            promptwidth=len(kb.keycap(keycode))
            textwidth=len(desc)
            if promptwidth>pw: pw=promptwidth
            if textwidth>tw: tw=textwidth
            km[keycode]=(func,args,True)
        if clear:
            cleartext="Press Clear to go back"
            km[keyboard.K_CLEAR]=(None,None,True)
        else:
            cleartext=None
        w=pw+tw+6
        basicpopup.__init__(self,h,w,title=title,colour=colour,
                            cleartext=cleartext,keymap=km)
        (h,w)=self.win.getmaxyx()
        y=2
        for keycode,desc,func,args in itemlist:
            self.addstr(y,2,"%s."%kb.keycap(keycode))
            self.addstr(y,pw+4,desc)
            y=y+1
        self.win.move(h-1,w-1)

class menu(basicpopup):
    """
    A popup menu with a list of selections. Selection can be made by
    using cursor keys to move up and down, and pressing Cash/Enter to
    confirm.

    itemlist entries are (desc,func,args)

    """
    def __init__(self,itemlist,default=0,
                 blurb="Select a line and press Cash/Enter",
                 title=None,clear=True,
                 colour=colour_input,w=None,dismiss_on_select=True,
                 keymap={}):
        self.itemlist=itemlist
        self.dismiss_on_select=dismiss_on_select
        if w is None:
            w=max(23,max(len(x[0]) for x in itemlist))+2
        if title is not None:
            w=max(len(title)+3,w)
        if blurb:
            blurbl=textwrap.wrap(blurb,w-4)
        else:
            blurbl=[]
        h=len(itemlist)+len(blurbl)+2
        if len(itemlist)>0:
            km={keyboard.K_CASH: (self.select,None,False)}
        else:
            km={}
        km.update(keymap)
        if clear:
            cleartext="Press Clear to go back"
            km[keyboard.K_CLEAR]=(self.dismiss,None,False)
        else:
            cleartext=None
        basicpopup.__init__(self,h,w,title=title,cleartext=cleartext,
                            colour=colour,keymap=km)
        (h,w)=self.win.getmaxyx()
        y=1
        for i in blurbl:
            self.addstr(y,2,i)
            y=y+1
        dl=[line(x[0]) for x in itemlist]
        self.s=scrollable(self.win,y,1,w-2,h-y-1,dl,keymap=km)
        self.s.focus()
    def select(self):
        i=self.itemlist[self.s.cursor]
        if self.dismiss_on_select: self.dismiss()
        if i[2] is None:
            i[1]()
        else:
            i[1](*i[2])

class linepopup(dismisspopup):
    def __init__(self,lines=[],title=None,dismiss=keyboard.K_CLEAR,
                 cleartext=None,colour=colour_error,keymap={}):
        (mh,mw)=stdwin.getmaxyx()
        w=max(len(i) for i in lines)
        w=min(w+4,mw)
        h=min(len(lines)+2,mh)
        dismisspopup.__init__(self,h,w,title,cleartext,colour,dismiss,
                              keymap)
        dl=[line(i) for i in lines]
        # The scrollable is going to have the focus all the time XXX
        # This is a nasty hack and I really need to revisit how the
        # keymap is handled.
        keymap.update({dismiss: (self.dismiss,None,False)})
        self.s=scrollable(self.win,1,2,w-4,h-2,dl,keymap=keymap,
                          show_cursor=False)
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
        w=max(w,len(cleartext)-1)
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
    def checkslash(i):
        a=s[i:i+1]
        if len(a)==0: return True
        return a=='/'
    if (checkdigit(0) and
        checkdigit(1) and
        checkdigit(2) and
        checkdigit(3) and
        checkslash(4) and
        checkdigit(5) and
        checkdigit(6) and
        checkslash(7) and
        checkdigit(8) and
        checkdigit(9)): return s
    return None

class field(basicwin):
    def __init__(self,keymap={}):
        self.nextfield=self
        self.prevfield=self
        self.focushook=None
        self.sethook=None
        # Default keyboard actions, overridden if in supplied keymap
        next=(lambda:self.nextfield.focus(),None,True)
        prev=(lambda:self.prevfield.focus(),None,True)
        basicwin.__init__(self,keymap,takefocus=False)
        self.keymap.update({
                keyboard.K_DOWN: next,
                keyboard.K_CASH: next,
                curses.ascii.TAB: next,
                keyboard.K_UP: prev,
                keyboard.K_CLEAR: prev})
        self.keymap.update(keymap)
    def set(self):
        if self.sethook is not None: self.sethook()
    def focus(self):
        basicwin.focus(self)
        if self.focushook is not None: self.focushook()

class scrollable(field):
    """A rectangular field of a page or popup that contains a list of
    items that can be scrolled up and down.

    lastline is a special item that, if present, is drawn at the end of
    the list.  In the register this is the prompt/input buffer/total.
    Where the scrollable is being used for entry of a list of items,
    the last line may be blank/inverse as a prompt.

    """
    def __init__(self,win,y,x,width,height,dl,show_cursor=True,
                 lastline=None,default=0,keymap={}):
        field.__init__(self,keymap)
        self.win=win
        self.y=y
        self.x=x
        self.w=width
        self.h=height
        self.dl=dl
        self.show_cursor=show_cursor
        self.lastline=lastline
        self.cursor=default
        self.top=0
        self.keymap.update(
            {keyboard.K_DOWN: (self.cursor_down,(1,),False),
             keyboard.K_UP: (self.cursor_up,(1,),False),
             keyboard.K_RIGHT: (self.cursor_down,(5,),False),
             keyboard.K_LEFT: (self.cursor_up,(5,),False),
             curses.KEY_NPAGE: (self.cursor_down,(10,),False),
             curses.KEY_PPAGE: (self.cursor_up,(10,),False),
             })
        self.keymap.update(keymap)
    def set(self,dl):
        self.dl=dl
        # XXX Frob cursor and scroll position if necessary
        self.redraw()
        field.set(self)
    def focus(self):
        # If we are obtaining the focus from the previous field, we should
        # move the cursor to the top.  If we are obtaining it from the next
        # field, we should move the cursor to the bottom.  Otherwise we
        # leave the cursor untouched.
        global focus
        if focus==self.prevfield: cursor=0
        elif focus==self.nextfield:
            if self.lastline: cursor=len(self.dl)
            else: cursor=len(self.dl)-1
        field.focus(self)
        self.redraw()
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
            # Check whether we are overwriting any of the last item
            if y==self.y+self.h+1: lastcomplete=lastcomplete-1
            self.addstr(self.y+self.h-1,self.x,'...'+' '*(self.w-3))
        if cursor_y is not None:
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
    def cursor_up(self,n):
        if self.cursor==0:
            self.prevfield.focus()
        else:
            self.cursor=self.cursor-n
            if self.cursor<0: self.cursor=0
        self.redraw()
    def cursor_at_end(self):
        if self.show_cursor:
            if self.lastline:
                return self.cursor>len(self.dl)
            else:
                return self.cursor>=len(self.dl)
        else:
            return self.display_complete
    def cursor_down(self,n):
        if self.cursor_at_end():
            self.nextfield.focus()
        else:
            self.cursor=self.cursor+n
            if self.lastline:
                if self.cursor>len(self.dl): self.cursor=len(self.dl)
            else:
                if self.cursor>=len(self.dl): self.cursor=len(self.dl)-1
        self.redraw()

class emptyline:
    """
    A line for use in a scrollable.  Has a natural colour, a "cursor
    is here" colour, and an optional "selected" colour.  This line has
    no text.

    """
    def __init__(self,colour=None,selected_colour=None):
        if colour is None: colour=curses.color_pair(0)
        self.colour=colour
        self.selected_colour=(
            selected_colour if selected_colour is not None else colour)
        self.cursor_colour=self.colour|curses.A_REVERSE
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
    def __init__(self,colour=None,selected_colour=None,lines=1):
        emptyline.__init__(self,colour,selected_colour)
        self.lines=lines
    def display(self,width):
        self.cursor=(0,0)
        return [""]*self.lines

class line(emptyline):
    """
    A line for use in a scrollable.  Has a natural colour, a "cursor
    is here" colour, an optional "selected" colour, and some text.  If
    the text is too long it will be truncated; this line will never
    wrap.

    """
    def __init__(self,text="",colour=None,selected_colour=None):
        emptyline.__init__(self,colour,selected_colour)
        self.text=text
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

class lrline(line):
    """
    A line for use in a scrollable.  Has a natural colour, a "cursor
    is here" colour, an optional "selected" colour, some left-aligned
    text (which will be wrapped if it is too long) and optionally some
    right-aligned text.

    """
    def __init__(self,ltext="",rtext="",colour=None,
                 selected_colour=None):
        self.ltext=ltext
        self.rtext=rtext
        if colour is None: colour=curses.color_pair(0)
        self.colour=colour
        self.selected_colour=(
            selected_colour if selected_colour is not None else colour)
    def update(self):
        pass
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

class editfield(field):
    """Accept input in a field.  Processes an implicit set of keycodes; when an
    unrecognised code is found processing moves to the standard keymap."""
    def __init__(self,win,y,x,w,keymap={},f=None,flen=None,validate=None,
                 readonly=False):
        """flen, if not None, is the maximum length of input allowed in the field.
        If this is greater than w then the field will scroll if necessary.  If
        validate is not none it will be called on every insertion into the field;
        it should return either a (potentially updated) string or None if the
        input is not allowed."""
        self.win=win
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
        if self.c>len(self.f): self.c=len(self.f)
        self.draw()
        field.focus(self)
    def set(self,l):
        if l is None: l=""
        if len(l)>self.flen: l=l[:self.flen]
        self.f=l
        self.c=len(self.f)
        self.i=0 # will be updated by draw() if necessary
        self.draw()
        field.set(self)
    def dismiss(self):
        field.dismiss(self)
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
            field.keypress(self,k)

class datefield(editfield):
    def __init__(self,win,y,x,keymap={},f=None,flen=None,readonly=False):
        if f is not None:
            f=formatdate(f)
        editfield.__init__(self,win,y,x,10,keymap=keymap,f=f,flen=10,
                           readonly=readonly,validate=validate_date)
    def set(self,v):
        if isinstance(v,str):
            editfield.set(self,v)
        else:
            editfield.set(self,formatdate(v))
    def read(self):
        try:
            d=strptime(self.f,"%Y/%m/%d")
        except:
            d=None
        if d is None: editfield.set(self,"")
        return d
    def draw(self):
        self.addstr(self.y,self.x,'YYYY/MM/DD',curses.A_REVERSE)
        self.addstr(self.y,self.x,self.f,curses.A_REVERSE)
        self.win.move(self.y,self.x+self.c)
    def insert(self,s):
        editfield.insert(self,s)
        if len(self.f)==4 or len(self.f)==7:
            self.set(self.f+'/')


class popupfield(field):
    def __init__(self,win,y,x,w,popupfunc,valuefunc,f=None,keymap={},readonly=False):
        self.win=win
        self.y=y
        self.x=x
        self.w=w
        self.popupfunc=popupfunc
        self.valuefunc=valuefunc
        self.readonly=readonly
        field.__init__(self,keymap)
        self.set(f)
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
        self.dismiss()
        self.nextfield.focus()
    def draw(self):
        if self.f is not None: s=self.valuefunc(self.f)
        else: s=""
        if len(s)>self.w: s=s[:self.w]
        self.addstr(self.y,self.x,' '*self.w,curses.A_REVERSE)
        self.addstr(self.y,self.x,s,curses.A_REVERSE)
        self.win.move(self.y,self.x)
    def keypress(self,k):
        if k==keyboard.K_CLEAR and self.f is not None and not self.readonly:
            self.f=None
            self.draw()
        elif k==keyboard.K_CASH and not self.readonly:
            self.popupfunc(self.setf,self.f)
        else:
            field.keypress(self,k)

# If d is provided then values in l are looked up in d before being
# displayed.
class listfield(popupfield):
    def __init__(self,win,y,x,w,l,d=None,f=None,keymap={},readonly=False):
        self.l=l
        self.d=d
        km=keymap.copy()
        if not readonly:
            km[keyboard.K_RIGHT]=(self.next,None,False)
            km[keyboard.K_LEFT]=(self.prev,None,False)
        popupfield.__init__(self,win,y,x,w,self.popuplist,
                            self.listval,f=f,keymap=km,readonly=readonly)
    def read(self):
        if self.f is None: return None
        return self.l[self.f]
    def listval(self,index):
        if self.d is not None:
            return self.d[self.l[index]]
        return self.l[index]
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

class buttonfield(field):
    def __init__(self,win,y,x,w,text,keymap={}):
        self.win=win
        self.y=y
        self.x=x
        self.t=text.center(w-2)
        field.__init__(self,keymap)
        self.draw()
    def focus(self):
        field.focus(self)
        self.draw()
    def dismiss(self):
        field.dismiss(self)
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

class table:
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
