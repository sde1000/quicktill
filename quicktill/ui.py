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

# itemlist entries are (desc,func,args)
# A popup menu with a list of selections. Selection can be made by
# using cursor keys to move up and down, and pressing Cash/Enter to
# confirm.
class menu(basicpopup):
    def __init__(self,itemlist,default=0,
                 blurb="Select a line and press Cash/Enter",
                 title=None,clear=True,
                 colour=colour_input,w=None,dismiss_on_select=True,
                 keymap={}):
        self.itemlist=itemlist
        if w is None:
            w=0
            # This can be replaced with a generator expression in python2.4:
            # w=max(w,max(len(x[0]) for x in itemlist))
            for i in itemlist:
                w=max(w,len(i[0]))
            w=w+2
        w=max(25,w)
        if title is not None:
            w=max(len(title)+3,w)
        if blurb:
            blurbl=textwrap.wrap(blurb,w-4)
        else:
            blurbl=[]
        h=len(itemlist)+len(blurbl)+2
        if len(itemlist)>0:
            km={keyboard.K_DOWN: (self.cursor_down,(1,),False),
                keyboard.K_UP: (self.cursor_up,(1,),False),
                keyboard.K_RIGHT: (self.cursor_down,(5,),False),
                keyboard.K_LEFT: (self.cursor_up,(5,),False),
                curses.KEY_NPAGE: (self.cursor_down,(10,),False),
                curses.KEY_PPAGE: (self.cursor_up,(10,),False),
                keyboard.K_CASH: (self.select,None,dismiss_on_select)}
        else:
            km={}
        km.update(keymap)
        if clear:
            cleartext="Press Clear to go back"
            km[keyboard.K_CLEAR]=(None,None,True)
        else:
            cleartext=None
        basicpopup.__init__(self,h,w,title=title,cleartext=cleartext,
                            colour=colour,keymap=km)
        (h,w)=self.win.getmaxyx()
        self.ytop=len(blurbl)+1
        self.top=0
        self.cursor=default
        if self.cursor is None: self.cursor=0
        self.h=h-self.ytop-1
        self.w=w-2
        y=1
        for i in blurbl:
            self.addstr(y,2,i)
            y=y+1
        self.check_scroll()
        self.redraw()
    def select(self):
        i=self.itemlist[self.cursor]
        if i[2] is None:
            i[1]()
        else:
            i[1](*i[2])
    def drawline(self,lineno):
        y=lineno-self.top
        if y<0: return
        if y>=self.h: return
        if lineno==self.cursor: attr=curses.A_REVERSE
        else: attr=0
        self.addstr(y+self.ytop,1,' '*self.w,attr)
        if ((y==0 and self.top>0) or
            (y==self.h-1 and lineno!=len(self.itemlist)-1)):
            self.addstr(y+self.ytop,1,'...',attr)
        else:
            self.addstr(y+self.ytop,1,self.itemlist[lineno][0],attr)
    def redraw(self):
        for i in range(0,len(self.itemlist)):
            self.drawline(i)
        self.win.move(self.cursor-self.top+self.ytop,1)
    def check_scroll(self):
        oldtop=self.top
        # Check for scrolling up
        if self.cursor-self.top<1 and self.top>0:
            self.top=self.cursor-(self.h/3)
            if self.top<0: self.top=0
        # Check for scrolling down
        if (self.cursor-self.top>=self.h-1 and
               self.cursor!=len(self.itemlist)):
            self.top=self.cursor-(self.h*2/3)
        # Check for scrolling beyond end of list
        if self.top+self.h>len(self.itemlist):
            self.top=len(self.itemlist)-self.h
        return self.top!=oldtop # Redraw necessary
    def cursor_down(self,lines):
        self.cursor=self.cursor+lines
        if self.cursor>=len(self.itemlist): self.cursor=len(self.itemlist)-1
        self.check_scroll()
        self.redraw()
    def cursor_up(self,lines):
        self.cursor=self.cursor-lines
        if self.cursor<0: self.cursor=0
        self.check_scroll()
        self.redraw()

class linepopup(dismisspopup):
    def __init__(self,lines=[],title=None,dismiss=keyboard.K_CLEAR,
                 cleartext=None,colour=colour_error,keymap={}):
        (mh,mw)=stdwin.getmaxyx()
        w=0
        # This can be replaced by a generator expression in python2.4:
        # w=max(len(i) for i in lines)
        for i in lines:
            w=max(len(i),w)
        w=min(w+4,mw)
        h=min(len(lines)+2,mh)
        dismisspopup.__init__(self,h,w,title,cleartext,colour,dismiss,
                              keymap)
        self.scrolly=0
        self.scrollpage=((h-2)*2)/3
        self.lines=lines
        self.redraw()
    def redraw(self):
        (h,w)=self.win.getmaxyx()
        end=self.scrolly+h-2
        if end>len(self.lines):
            self.scrolly=self.scrolly-(end-len(self.lines))
        if self.scrolly<0: self.scrolly=0
        end=self.scrolly+h-2
        scrolltop=(self.scrolly>0)
        scrollbot=(end<len(self.lines))
        y=1
        for i in self.lines[self.scrolly:self.scrolly+h-2]:
            self.addstr(y,2,' '*(w-4))
            if (y==1 and scrolltop) or (y==(h-2) and scrollbot):
                self.addstr(y,2,'...')
            else:
                self.addstr(y,2,i)
            y=y+1
        self.win.move(h-1,w-1)
    def keypress(self,k):
        if k==keyboard.K_DOWN:
            self.scrolly=self.scrolly+1
            self.redraw()
        elif k==keyboard.K_UP:
            self.scrolly=self.scrolly-1
            self.redraw()
        elif k==keyboard.K_RIGHT:
            self.scrolly=self.scrolly+self.scrollpage
            self.redraw()
        elif k==keyboard.K_LEFT:
            self.scrolly=self.scrolly-self.scrollpage
            self.redraw()
        else:
            dismisspopup.keypress(self,k)

class infopopup(linepopup):
    """A pop-up box that formats and displays text.  The text parameter is
    a list of paragraphs."""
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
        km={
            keyboard.K_DOWN: next,
            keyboard.K_CASH: next,
            curses.ascii.TAB: next,
            keyboard.K_UP: prev,
            keyboard.K_CLEAR: prev}
        km.update(keymap)
        basicwin.__init__(self,keymap=km,takefocus=False)
    def set(self):
        if self.sethook is not None: self.sethook()
    def focus(self):
        basicwin.focus(self)
        if self.focushook is not None: self.focushook()

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
