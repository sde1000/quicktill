from __future__ import unicode_literals
from . import keyboard,ui,td,user
from .models import KeyCap,KeyboardBinding

class edit_keycaps(user.permission_checked,ui.dismisspopup):
    """This popup window enables the keycaps of line keys to be edited.

    """
    permission_required=('edit-keycaps',
                         'Change the names of keys on the keyboard')
    def __init__(self):
        ui.dismisspopup.__init__(self,8,60,title="Edit Keycaps",
                                 colour=ui.colour_input)
        self.addstr(
            2,2,"Press a line key; alter the legend and press Cash/Enter.")
        self.addstr(4,2,"Keycode:")
        self.addstr(5,2," Legend:")
        self.keycode=None
        self.kcfield=ui.editfield(5,11,46,keymap={
                keyboard.K_CASH: (self.setcap,None)})
        self.kcfield.focus()
    def selectline(self,linekey):
        self.addstr(4,11," "*20)
        self.addstr(4,11,linekey.name)
        self.kcfield.set(linekey.keycap)
        self.keycode=linekey
    def setcap(self):
        if self.keycode is None: return
        if self.kcfield.f=="": return
        newcap=KeyCap(keycode=self.keycode.name,
                      keycap=self.kcfield.f)
        td.s.merge(newcap)
        td.s.flush()
    def keypress(self,k):
        if hasattr(k,'line'):
            self.selectline(k)
        else:
            ui.dismisspopup.keypress(self,k)

def linemenu(keycode,func,allow_stocklines=True,allow_plus=False,
             allow_mods=False):
    """Given a keycode, find out what is bound to it.  If there's more
    than one thing, pop up a menu to select a particular binding.
    Call func with the keyboard binding as an argument when a
    selection is made (NB at this point, the binding may be a detached
    instance).  No call is made if Clear is pressed.  If there's only
    one keyboard binding in the list, shortcut to the function.

    This function returns the number of keyboard bindings found.  Some
    callers may wish to use this to inform the user that a key has no
    bindings rather than having an uninformative empty menu pop up.

    """
    # Find the keyboard bindings associated with this keycode
    kb=td.s.query(KeyboardBinding).\
        filter(KeyboardBinding.keycode==keycode.name)
    if not allow_stocklines:
        kb=kb.filter(KeyboardBinding.stocklineid==None)
    if not allow_plus:
        kb=kb.filter(KeyboardBinding.pluid==None)
    if not allow_mods:
        kb=kb.filter((KeyboardBinding.stocklineid!=None)|(KeyboardBinding.pluid!=None))
    kb=kb.all()

    if len(kb)==1: func(kb[0])
    elif len(kb)>1:
        il=sorted([(keyboard.__dict__[x.menukey],x.name,func,(x,))
                   for x in kb],key=lambda x:x[0].keycap)
        ui.keymenu(il,title=keycode.keycap,colour=ui.colour_line)
    return len(kb)
