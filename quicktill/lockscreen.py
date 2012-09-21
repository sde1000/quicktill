from . import ui,keyboard,td

def usersmenu(func):
    users=td.users_list()
    lines=ui.table([(code,name) for code,name in users]).format(' r l ')
    sl=[(x,func,(y[0],)) for x,y in zip(lines,users)]
    ui.menu(sl,title="Users",blurb="Choose a user and press Cash/Enter.")

class popup(ui.dismisspopup):
    def __init__(self):
        ui.dismisspopup.__init__(self,7,45,title="Screen Lock",
                                 colour=ui.colour_confirm)
        self.addstr(2,2,"Enter your code to lock:")
        self.addstr(4,2,"Press Manage Till to add or remove users.")
        self.codefield=ui.editfield(2,27,2,keymap={
                keyboard.K_CASH: (self.enter_key,None),
                keyboard.K_MANAGETILL: (editusers,None)})
        self.codefield.focus()
    def enter_key(self):
        if self.codefield.f=='': usersmenu(self.user_selected)
        user=td.users_get(self.codefield.f)
        if user:
            self.dismiss()
            UnlockPopup(self.codefield.f,user)
        else:
            self.codefield.set("")
    def user_selected(self,code):
        self.codefield.set(code)
        self.enter_key()

class UnlockPopup(ui.basicpopup):
    def __init__(self,code,user):
        msg="This screen is locked by %s."%user
        minwidth=len(msg)+4
        ui.basicpopup.__init__(self,7,max(45,minwidth),title="Screen Lock",
                               colour=ui.colour_confirm)
        self.code=code
        self.addstr(2,2,"This screen is locked by %s."%user)
        self.addstr(4,2,"Enter code to unlock: ")
        self.codefield=ui.editfield(4,24,2,keymap={
                keyboard.K_CASH: (self.enter_key,None)})
        self.codefield.focus()
    def enter_key(self):
        if self.codefield.f=='': usersmenu(self.user_selected)
        if self.codefield.f==self.code:
            self.dismiss()
        else:
            self.codefield.set("")
    def user_selected(self,code):
        self.codefield.set(code)
        self.enter_key()
    
class editusers(ui.listpopup):
    """
    A window showing the list of users for the lock screen.  Pressing
    Cancel on a line deletes the user.  Pressing Enter goes to the
    dialog for adding a new user.

    """
    def __init__(self):
        ulist=td.users_list()
        f=ui.tableformatter(' l l ')
        headerline=ui.tableline(f,["Code","Name"])
        lines=[ui.tableline(f,(code,user),userdata=code)
               for code,user in ulist]
        ui.listpopup.__init__(
            self,lines,title="Lock Screen Users",
            header=["Press Cancel to delete a code.  "
                    "Press Enter to add a new code.",
                    headerline])
    def keypress(self,k):
        if k==keyboard.K_CANCEL and self.s and len(self.s.dl)>0:
            line=self.s.dl.pop(self.s.cursor)
            self.s.redraw()
            td.users_del(line.userdata)
        elif k==keyboard.K_CASH:
            self.dismiss()
            adduser()
        else:
            ui.listpopup.keypress(self,k)

class adduser(ui.dismisspopup):
    def __init__(self):
        ui.dismisspopup.__init__(self,7,34,title="Add Lock Screen User",
                                 colour=ui.colour_input)
        self.addstr(2,2,"New code: ")
        self.addstr(3,2,"New user name:")
        self.codefield=ui.editfield(2,12,2)
        self.namefield=ui.editfield(4,2,30,keymap={
                keyboard.K_CASH: (self.enter,None)})
        ui.map_fieldlist([self.codefield,self.namefield])
        self.codefield.focus()
    def enter(self):
        if len(self.codefield.f)!=2:
            ui.infopopup(["The code must be two characters."],title="Error")
            return
        if len(self.namefield.f)<2:
            ui.infopopup(["You must provide a name."],title="Error")
            return
        if td.users_get(self.codefield.f):
            ui.infopopup(["That code is already in use."],title="Error")
            return
        self.dismiss()
        td.users_add(self.codefield.f,self.namefield.f)
