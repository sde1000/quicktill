from . import ui,td,user,linekeys,keyboard
from .models import KeyboardBinding
from decimal import Decimal
import inspect,itertools
import logging
log=logging.getLogger(__name__)

class Incompatible(Exception):
    def __init__(self,msg=None):
        self.msg=msg

# Dictionary of all registered modifiers, allowing modifier instances
# to be looked up using the modifier name
all={}

class BaseModifier(object):
    """The base modifier.  Not compatible with anything.

    """
    def __init__(self,name):
        global all
        self.name=name
        all[name]=self
    def mod_stockline(self,stockline,transline):
        raise Incompatible("The '{}' modifier can't be used with stocklines."
                           .format(self.name))
    def mod_plu(self,plu,transline):
        raise Incompatible("The '{}' modifier can't be used with price lookups."
                           .format(self.name))
    @property
    def description(self):
        return inspect.cleandoc(self.__doc__)

class BadModifier(BaseModifier):
    """This modifier exists in the database, but is not defined in the
    configuration file.  It can't be used with any stock line or price
    lookup.  You should either declare it in the configuration file,
    or delete its keyboard bindings.

    If you modify the configuration file, you must restart the till
    software to pick up the changes.

    """
    pass

class RegisterSimpleModifier(type):
    """Metaclass that automatically instantiates modifiers using their
    class name.

    """
    def __init__(cls,name,bases,attrs):
        if name!="SimpleModifier":
            cls(name=name)

class SimpleModifier(BaseModifier, metaclass=RegisterSimpleModifier):
    """Modifiers created as a subclass of this register themselves
    automatically using the class name.  They shouldn't have their own
    __init__ methods.  Their methods can access the modifier name as
    self.name.

    """
    pass

class modify(user.permission_checked,ui.listpopup):
    permission_required=('alter-modifier','Alter the key bindings for a modifier')
    def __init__(self,name):
        # If the modifier does not exist, create it so that its
        # keyboard bindings can be deleted.
        global all
        if name not in all:
            BadModifier(name=name)
        mod=all[name]
        self.name=name
        bindings=td.s.query(KeyboardBinding).\
                  filter(KeyboardBinding.stockline==None).\
                  filter(KeyboardBinding.plu==None).\
                  filter(KeyboardBinding.modifier==name).\
                  all()
        f=ui.tableformatter(' l   c ')
        kbl=linekeys.keyboard_bindings_table(bindings,f)
        hl=[(ui.lrline(x),ui.emptyline()) for x in mod.description.split('\n\n')]
        hl=list(itertools.chain.from_iterable(hl))
        hl=hl+[ui.line("To add a binding, press a line key."),
               ui.line("To delete a binding, highlight it and press Cancel."),
               ui.emptyline(),
               f("Line key","Menu key")]
        ui.listpopup.__init__(self,kbl,header=hl,title="{} modifier".format(name),
                              w=58)
    def keypress(self,k):
        if hasattr(k,'line'):
            self.dismiss()
            linekeys.addbinding(self,k,func=lambda:modify(self.name))
        elif k==keyboard.K_CANCEL:
            self.deletebinding()
        else:
            super(modify,self).keypress(k)
    def deletebinding(self):
        log.debug("modifier deletebinding: cursor is %s",self.s.cursor)
        if self.s.cursor is None: return
        line=self.s.dl.pop(self.s.cursor)
        self.s.redraw()
        td.s.add(line.userdata)
        td.s.delete(line.userdata)
        td.s.flush()

def defined_modifiers():
    """Return a list of all modifiers.

    """
    return sorted(all.keys())

class modifiermenu(ui.menu):
    def __init__(self):
        ui.menu.__init__(self,[(x,modify,(x,)) for x in defined_modifiers()],
                         blurb="Choose a modifier to alter from the list below, "
                         "or press a line key that is already bound to the "
                         "modifier.",
                         title="Modifiers")
    def keypress(self,k):
        if hasattr(k,'line'):
            linekeys.linemenu(k,self.mod_selected,allow_stocklines=False,
                              allow_plus=False,allow_mods=True)
        else:
            ui.menu.keypress(self,k)
    def mod_selected(self,kb):
        self.dismiss()
        td.s.add(kb)
        modify(kb.modifier)
