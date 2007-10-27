# This module manages the display - the header line, clock, popup
# windows, and so on.

# What colour pairs are used for:
# Pair 1 - header bar
# Pair 2 - informational messages
# Pair 3 - manager's menus
# Pair 4 - item selection menus

import curses,curses.ascii,time,math,keyboard,sys,string,textwrap

import logging
log=logging.getLogger()

colour_header=1
colour_error=1
colour_info=2
colour_input=3
colour_line=4
colour_cashline=5
colour_changeline=6
colour_cancelline=7

# Hashes of keycodes and locations
inputs={}
codes={}
for i in keyboard.layout:
    inputs[i[0]]=i
    codes[i[2]]=i
# curses codes and their till keycode equivalents
kbcodes={
    curses.KEY_LEFT: keyboard.K_LEFT,
    curses.KEY_RIGHT: keyboard.K_RIGHT,
    curses.KEY_UP: keyboard.K_UP,
    curses.KEY_DOWN: keyboard.K_DOWN,
    ord('1'): keyboard.K_ONE,
    ord('2'): keyboard.K_TWO,
    ord('3'): keyboard.K_THREE,
    ord('4'): keyboard.K_FOUR,
    ord('5'): keyboard.K_FIVE,
    ord('6'): keyboard.K_SIX,
    ord('7'): keyboard.K_SEVEN,
    ord('8'): keyboard.K_EIGHT,
    ord('9'): keyboard.K_NINE,
    ord('0'): keyboard.K_ZERO,
    ord('.'): keyboard.K_POINT,
    curses.KEY_ENTER: keyboard.K_CASH,
    10: keyboard.K_CASH,
    }

# The page having the input focus - at top of stack
focus=None
# The page at the bottom of the stack
basepage=None

# Hotkeys for switching between pages.
hotkeys={}

class clock:
    def __init__(self,win):
        self.stdwin=win
    def nexttime(self):
        now=time.time()
        return math.ceil(now)
    def alarm(self):
        ts=time.strftime("%a %d %b %Y %H:%M:%S %Z")
        (my,mx)=stdwin.getmaxyx()
        self.stdwin.addstr(0,mx-len(ts),ts,curses.color_pair(colour_header))

def formattime(ts):
    "Returns ts formatted as %Y/%m/%d %H:%M:%S"
    if ts is None: return ""
    return time.strftime("%Y/%m/%d %H:%M:%S",ts)

def formatdate(ts):
    "Returns ts formatted as %Y/%m/%d"
    if ts is None: return ""
    return time.strftime("%Y/%m/%d",ts)

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

def updateheader(page):
    if page==basepage:
        stdwin.addstr(0,0,50*" ",curses.color_pair(colour_header))
        stdwin.addstr(0,0,page.pagename(),curses.color_pair(colour_header))

# Switch to a VC
def selectpage(page):
    global focus,basepage
    if page==basepage: return # Nothing to do
    # Tell the current page we're switching away
    if basepage:
        basepage.deselected(focus,savefocus())
    focus=page
    basepage=page
    updateheader(page)
    page.selected()

def handle_keyboard_input(k):
    global focus
    if k in kbcodes: k=kbcodes[k]
    if k in codes:
        log.debug("Keypress %s"%codes[k][1])
    if k in hotkeys:
        selectpage(hotkeys[k])
    else:
        focus.keypress(k)

class reader:
    def __init__(self,stdwin):
        self.stdwin=stdwin
        self.ibuf=[]
        self.decode=False
    def fileno(self):
        return sys.stdin.fileno()
    def doread(self):
        def pass_on_buffer():
            handle_keyboard_input(ord('['))
            for i in self.ibuf:
                handle_keyboard_input(i)
            self.decode=False
            self.ibuf=[]
        i=self.stdwin.getch()
        if i==-1: return
        if self.decode:
            if i==ord(']'):
                s=string.join([chr(x) for x in self.ibuf],'')
                if s in inputs:
                    handle_keyboard_input(inputs[s][2])
                    self.decode=False
                    self.ibuf=[]
                else:
                    pass_on_buffer()
                    handle_keyboard_input(ord(']'))
            else:
                self.ibuf.append(i)
                if len(self.ibuf)>3:
                    pass_on_buffer()
        elif i==ord('['):
            self.decode=True
        else:
            handle_keyboard_input(i)

class basicpage:
    def __init__(self,pan):
        self.pan=pan
        self.win=pan.window()
        self.focus=self
        self.stack=[]
        (self.h,self.w)=self.win.getmaxyx()
    def pagename(self):
        return "Basic page"
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

class basicwin:
    def __init__(self,keymap={},takefocus=True):
        self.keymap=keymap.copy()
        if takefocus: self.focus()
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
        win=self.pan.window()
        win.bkgdset(ord(' '),curses.color_pair(colour))
        win.clear()
        win.border()
        if title: win.addstr(0,1,title)
        if cleartext: win.addstr(h-1,w-1-len(cleartext),cleartext)
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
                return "Press %s to dismiss"%codes[dismiss][1]
        return cleartext

# itemlist entries are (keycode,desc,func,args)
class keymenu(basicpopup):
    def __init__(self,itemlist,title="Press a key",clear=True,
                 colour=colour_input):
        h=len(itemlist)+4
        pw=0 ; tw=0
        km={}
        for i in itemlist:
            promptwidth=len(codes[i[0]][1])
            textwidth=len(i[1])
            if promptwidth>pw: pw=promptwidth
            if textwidth>tw: tw=textwidth
            km[i[0]]=(i[2],i[3],True)
        if clear:
            cleartext="Press Clear to go back"
            km[keyboard.K_CLEAR]=(None,None,True)
        else:
            cleartext=None
        w=pw+tw+6
        basicpopup.__init__(self,h,w,title=title,colour=colour,
                            cleartext=cleartext,keymap=km)
        win=self.pan.window()
        (h,w)=win.getmaxyx()
        y=2
        for i in itemlist:
            win.addstr(y,2,"%s."%codes[i[0]][1])
            win.addstr(y,pw+4,i[1])
            y=y+1
        win.move(h-1,w-1)

# itemlist entries are (desc,func,args)
# A popup menu with a list of selections. Selection can be made by
# using cursor keys to move up and down, and pressing Cash/Enter to
# confirm.
class menu(basicpopup):
    def __init__(self,itemlist,default=0,
                 blurb="Select a line and press Cash/Enter",
                 title=None,clear=True,
                 colour=colour_input,w=None):
        self.itemlist=itemlist
        if w is None:
            w=0
            for i in itemlist:
                w=max(w,len(i[0]))
            w=w+2
        if w<25: w=25
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
                keyboard.K_CASH: (self.select,None,True)}
        else:
            km={}
        if clear:
            cleartext="Press Clear to go back"
            km[keyboard.K_CLEAR]=(None,None,True)
        else:
            cleartext=None
        basicpopup.__init__(self,h,w,title=title,cleartext=cleartext,
                            colour=colour,keymap=km)
        self.win=self.pan.window()
        (h,w)=self.win.getmaxyx()
        self.ytop=len(blurbl)+1
        self.top=0
        self.cursor=default
        if self.cursor is None: self.cursor=0
        self.h=h-self.ytop-1
        self.w=w-2
        y=1
        for i in blurbl:
            self.win.addstr(y,2,i)
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
        self.win.addstr(y+self.ytop,1,' '*self.w,attr)
        if ((y==0 and self.top>0) or
            (y==self.h-1 and lineno!=len(self.itemlist)-1)):
            self.win.addstr(y+self.ytop,1,'...',attr)
        else:
            self.win.addstr(y+self.ytop,1,self.itemlist[lineno][0],attr)
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

class infopopup(dismisspopup):
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
        h=len(t)
        h=min(h,maxh)
        dismisspopup.__init__(self,h+4,w+4,title,cleartext,colour,
                              dismiss,keymap)
        win=self.pan.window()
        (h,w)=win.getmaxyx()
        y=2
        for i in t:
            if y<h: win.addstr(y,2,i)
            y=y+1
        win.move(h-1,w-1)

class linepopup(dismisspopup):
    def __init__(self,lines=[],title=None,dismiss=keyboard.K_CLEAR,
                 cleartext=None,colour=colour_error,keymap={}):
        (mh,mw)=stdwin.getmaxyx()
        w=0
        for i in lines:
            w=max(len(i),w)
        w=w+4
        w=min(w,mw)
        h=min(len(lines)+2,mh)
        dismisspopup.__init__(self,h,w,title,cleartext,colour,dismiss,
                              keymap)
        win=self.pan.window()
        (h,w)=win.getmaxyx()
        y=1
        for i in lines:
            if y<h: win.addstr(y,2,i)
            y=y+1
        win.move(h-1,w-1)

def validate_int(s,c):
    try:
        int(s)
    except:
        return None
    return s
def validate_float(s,c):
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
        self.win.addstr(self.y,self.x,' '*self.w,curses.A_REVERSE)
        self.win.addstr(self.y,self.x,self.f[self.i:self.i+self.w],curses.A_REVERSE)
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
            self.insert(codes[k][1])
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
            d=time.strptime(self.f,"%Y/%m/%d")
        except:
            d=None
        if d is None: editfield.set(self,"")
        return d
    def draw(self):
        self.win.addstr(self.y,self.x,'YYYY/MM/DD',curses.A_REVERSE)
        self.win.addstr(self.y,self.x,self.f,curses.A_REVERSE)
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
        self.win.addstr(self.y,self.x,' '*self.w,curses.A_REVERSE)
        self.win.addstr(self.y,self.x,s,curses.A_REVERSE)
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
        self.win.addstr(self.y,self.x,s,curses.A_REVERSE)
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

def linemenu(linelist,func):
    """Pop up a menu to select a line from a list.  Call func with the
    line as an argument when a selection is made.  No call is made if
    Clear is pressed.  If there's only one line in the list, or it's
    not a list, shortcut to the function."""
    if type(linelist) is list:
        if len(linelist)==1:
            func(linelist[0])
            return
        il=[(keyboard.numberkeys[i],linelist[i][0],func,(linelist[i],))
            for i in range(0,len(linelist))]
        keymenu(il,title="Choose an item",colour=colour_line)
    else:
        func(linelist)

def addpage(page,hotkey,args=()):
    (my,mx)=stdwin.getmaxyx()
    win=curses.newwin(my-1,mx,1,0)
    pan=curses.panel.new_panel(win)
    p=page(pan,*args)
    pan.set_userptr(p)
    hotkeys[hotkey]=p
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
    global stdwin
    stdwin=w
    (my,mx)=stdwin.getmaxyx()
    curses.init_pair(1,curses.COLOR_WHITE,curses.COLOR_RED)
    curses.init_pair(2,curses.COLOR_BLACK,curses.COLOR_GREEN)
    curses.init_pair(3,curses.COLOR_WHITE,curses.COLOR_BLUE)
    curses.init_pair(4,curses.COLOR_BLACK,curses.COLOR_YELLOW)
    curses.init_pair(5,curses.COLOR_GREEN,curses.COLOR_BLACK)
    curses.init_pair(6,curses.COLOR_YELLOW,curses.COLOR_BLACK)
    curses.init_pair(7,curses.COLOR_BLUE,curses.COLOR_BLACK)
    stdwin.addstr(0,0," "*mx,curses.color_pair(1))
