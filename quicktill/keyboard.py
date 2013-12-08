class keycode(object):
    def __new__(cls,name,keycap,*args,**kwargs):
        # If a keycode of this name already exists, return it instead
        existing=globals().get(name)
        if existing: return existing
        self=object.__new__(cls)
        self.name=name
        self.keycap=keycap
        self._register()
        return self
    def __init__(self,*args,**kwargs):
        pass
    def _register(self):
        globals()[self.name]=self
    def __unicode__(self):
        return self.name
    def __repr__(self):
        return '%s("%s","%s")'%(self.__class__.__name__,self.name,self.keycap)

class notekey(keycode):
    def __init__(self,name,keycap,notevalue):
        self.notevalue=notevalue

class modkey(keycode):
    def __init__(self,name,keycap,qty,depts):
        self.qty=qty
        self.depts=depts

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
        from . import td,models
        dept=td.s.query(models.Department).get(self._dept)
        if dept: return dept.description
        return "Department %d"%self._dept
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
        from . import td,models
        cap=td.s.query(models.KeyCap).get(self.name)
        if cap: return cap.keycap
        return "Line %d"%self._line
    @property
    def line(self):
        return self._line
    def __repr__(self):
        return "linekey(%d)"%self._line

# The only keycodes that need to be defined here are those referred to
# explicitly in the till code.

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

# Tendering keys
keycode("K_CASH","Cash / Enter")
keycode("K_CARD","Card")
keycode("K_DRINKIN","Drink 'In'")

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
