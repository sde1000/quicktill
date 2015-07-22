from __future__ import unicode_literals

from . import ui,td,user,linekeys,keyboard
from .models import KeyboardBinding
from decimal import Decimal
import inspect,itertools

class Incompatible(Exception):
    def __init__(self,msg=None):
        self.msg=msg

# XXX it might be nice to do something here so that modifiers don't
# have to be instantiated to be used if they don't need extra
# information passing in on instantiation.  Otherwise typical config
# files will have tedious redundancy in them.

class BaseModifier(object):
    """The base modifier.  Not compatible with anything.

    """
    def __init__(self,name):
        self.name=name
    def mod_stockline(self,stockline,transline):
        raise Incompatible("The '{}' modifier can't be used with stocklines."
                           .format(self.name))
    def mod_plu(self,plu,transline):
        raise Incompatible("The '{}' modifier can't be used with price lookups."
                           .format(self.name))
    @property
    def description(self):
        return inspect.cleandoc(self.__doc__)

class Half(BaseModifier):
    """Half pint modifier.  Sets the serving size to 0.5 when used with
    items sold in pints.

    This is a test to see what happens with a second paragraph.

    """
    def mod_stockline(self,stockline,transline):
        st=transline.stockref.stockitem.stocktype
        if st.unit_id!='pt':
            raise Incompatible(
                "The {} modifier can only be used with stock "
                "that is sold in pints.".format(self.name))
        # There may not be a price at this point
        if transline.amount: transline.amount=transline.amount/2
        transline.stockref.qty=transline.stockref.qty*Decimal("0.5")
        transline.text="{} half pint".format(st.format())

class Test(BaseModifier):
    """Test modifier.  Uses alt price 1 if the note is 'Wine', rejects
    otherwise.

    """
    @classmethod
    def mod_plu(cls,plu,transline):
        if plu.note!='Wine':
            raise Incompatible(
                "This modifier can only be used with wine; the Note field "
                "of the price lookup must be set to 'Wine'.")
        if not plu.altprice1:
            raise Incompatible(
                "The {} price lookup does not have alternative price 1 set."
                .format(plu.description))
        transline.amount=plu.altprice1

all={
    'Half':Half("Half"),
    'Test':Test("Test"),
}

class modify(user.permission_checked,ui.listpopup):
    permission_required=('alter-modifier','Alter the key bindings for a modifier')
    def __init__(self,name):
        # XXX might not exist!
        mod=all[name]
        self.name=name
        bindings=td.s.query(KeyboardBinding).\
                  filter(KeyboardBinding.stockline==None).\
                  filter(KeyboardBinding.plu==None).\
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
        try:
            line=self.s.dl.pop(self.s.cursor)
        except IndexError:
            return
        self.s.redraw()
        td.s.add(line.userdata)
        td.s.delete(line.userdata)
        td.s.flush()

def defined_modifiers():
    # XXX testing only
    return all.keys()

class modifiermenu(ui.menu):
    def __init__(self):
        ui.menu.__init__(self,[(x,modify,(x,)) for x in defined_modifiers()],
                         blurb="Choose a modifier to alter from the list below, "
                         "or press a line key that is already bound to the "
                         "modifier.",
                         title="Modifiers")
