# -*- coding: utf-8 -*-

from . import td,models

__all__=["keycode","deptkey","linekey","numberkeys","cursorkeys","notes"]

class keycode(object):
    def __new__(cls,name,keycap,group=None):
        # If a keycode of this name already exists, return it instead
        existing=globals().get(name)
        if existing: return existing
        self=object.__new__(cls)
        self.name=name
        self.keycap=keycap
        self.group=group
        self._register()
        return self
    def __init__(self,*args,**kwargs):
        pass
    def _register(self):
        # Register this keycode in globals and in its group if necessary
        # Don't call this from anywhere other than __new__
        global __all__
        globals()[self.name]=self
        __all__.append(self.name)
        if self.group:
            g=globals().get(self.group)
            if not g:
                g=[]
                globals()[self.group]=g
                __all__.append(self.group)
            g.append(self)
    def __unicode__(self):
        return self.name
    def __repr__(self):
        if self.group: return 'keycode("%s","%s",group="%s")'%(
            self.name,self.keycap,self.group)
        return 'keycode("%s","%s")'%(self.name,self.keycap)

class deptkey(keycode):
    def __new__(cls,dept):
        existing=globals().get("K_DEPT%d"%dept)
        if existing: return existing
        self=object.__new__(cls)
        self._dept=dept
        self._register()
        return self
    def __init__(self,*args,**kwargs):
        pass
    @property
    def name(self):
        return "K_DEPT%d"%self._dept
    @property
    def keycap(self):
        dept=td.s.query(models.Department).get(self._dept)
        if dept: return dept.description
        return "Department %d"%self._dept
    @property
    def group(self): return "depts"
    @property
    def department(self):
        return self._dept
    def __repr__(self):
        return "deptkey(%d)"%self._dept

class linekey(keycode):
    def __new__(cls,line):
        existing=globals().get("K_LINE%d"%line)
        if existing: return existing
        self=object.__new__(cls)
        self._line=line
        self._register()
        return self
    def __init__(self,*args,**kwargs):
        pass
    @property
    def name(self):
        return "K_LINE%d"%self._line
    @property
    def keycap(self):
        cap=td.s.query(models.KepCap).get((tillconfig.kblayout,self.name))
        if cap: return cap.keycap
        return "Line %d"%self._line
    @property
    def group(self): return "lines"
    def __repr__(self):
        return "linekey(%d)"%self._line

# Some keycode definitions are included here for backward
# compatibility with old configuration files.  They will eventually be
# removed.  The only keycodes that need to be defined here are those
# referred to explicitly in the till code.

# Pages - will eventually be defined in the configuration file
keycode("K_ALICE","Alice")
keycode("K_BOB","Bob")
keycode("K_CHARLIE","Charlie")
keycode("K_DORIS","Doris")
keycode("K_EDDIE","Eddie")
keycode("K_FRANK","Frank")
keycode("K_GILES","Giles")
keycode("K_HELEN","Helen")
keycode("K_IAN","Ian")
keycode("K_JANE","Jane")
keycode("K_KATE","Kate")
keycode("K_LIZ","Liz")
keycode("K_MALLORY","Mallory")
keycode("K_NIGEL","Nigel")
keycode("K_OEDIPUS","Oedipus")

# Till management keys
keycode("K_USESTOCK","Use Stock")
keycode("K_MANAGESTOCK","Manage Stock")
keycode("K_WASTE","Record Waste")
keycode("K_MANAGETILL","Manage Till")
keycode("K_CANCEL","Cancel")
keycode("K_CLEAR","Clear")
keycode("K_PRICECHECK","Price Check")
keycode("K_PRINT","Print")
keycode("K_RECALLTRANS","Recall Transaction")
keycode("K_MANAGETRANS","Manage Transaction")
keycode("K_QUANTITY","Quantity")
keycode("K_FOODORDER","Order Food")
keycode("K_CANCELFOOD","Cancel Food")
keycode("K_EXTRAS","Extras")
keycode("K_PANIC","Panic")
keycode("K_APPS","Apps")
keycode("K_LOCK","Lock")
keycode("K_HALF","Half","modkeys")
keycode("K_DOUBLE","Double","modkeys")
keycode("K_4JUG","4pt Jug","modkeys")

# Tendering keys
keycode("K_CASH","Cash / Enter")
keycode("K_CARD","Card")
keycode("K_DRINKIN","Drink 'In'")

# It would be ugly to use a group here!
numberkeys=[
    keycode("K_ONE","1"),
    keycode("K_TWO","2"),
    keycode("K_THREE","3"),
    keycode("K_FOUR","4"),
    keycode("K_FIVE","5"),
    keycode("K_SIX","6"),
    keycode("K_SEVEN","7"),
    keycode("K_EIGHT","8"),
    keycode("K_NINE","9"),
    keycode("K_ZERO","0"),
    keycode("K_ZEROZERO","00"),
    keycode("K_POINT","."),
    ]
cursorkeys=[
    keycode("K_LEFT","Left"),
    keycode("K_RIGHT","Right"),
    keycode("K_UP","Up"),
    keycode("K_DOWN","Down"),
    ]
notes={
    keycode("K_FIVER","£5"): 500,
    keycode("K_TENNER","£10"): 1000,
    keycode("K_TWENTY","£20"): 2000,
    keycode("K_FIFTY","£50"): 5000,
    }

for d in range(1,21):
    deptkey(d)
for l in range(1,101):
    linekey(l)
