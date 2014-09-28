"""
Users and permissions.

For each user we store a set of strings which correspond to the
actions that user is allowed to perform.  We also support the
definition of "groups" which are themselves sets of strings
corresponding to actions.

We maintain a dictionary in which we can look up descriptions of
actions that are collected from the places these actions are used.
The dictionary stores the first description it sees for each action;
the assumption is that old descriptions loaded from the database will
be superseded by descriptions from the code, which will be seen first.

This module provides a class to derive from (permission_checked) and a
function decorator (permission_required) for other modules to use to
indicate restricted functionality.

"""

from __future__ import unicode_literals
from . import ui,td,event,keyboard,tillconfig
from .models import User,UserToken,Permission
from sqlalchemy.orm import joinedload
import types
import socket,logging
import datetime
log=logging.getLogger(__name__)

class ActionDescriptionRegistry(dict):
    def __getitem__(self,key):
        if key in self: return dict.__getitem__(self,key)
        else: return "undefined"
    def __setitem__(self,key,val):
        if key in self: return
        if val is None: return
        dict.__setitem__(self,key,val)

action_descriptions=ActionDescriptionRegistry()

class _permission_checked_metaclass(type):
    """
    Metaclass for permission_checked classes.

    """
    def __new__(meta,name,bases,dct):
        # Called when a permission_checked class is defined.  Look at
        # the permission_required and register its action description.
        pr=dct.get("permission_required")
        if pr:
            action_descriptions[pr[0]]=pr[1]
        return type.__new__(meta,name,bases,dct)
    def __call__(cls,*args,**kwargs):
        # Called when a permission_checked class is about to be
        # instantiated
        u=ui.current_user()
        if cls.allowed(u):
            return type.__call__(cls,*args,**kwargs)
        else:
            if u:
                ui.infopopup(
                    ["{user} does not have the '{req}' permission "
                     "which is required for this operation.".format(
                            user=u.fullname, req=cls.permission_required[0])],
                    title="Not allowed")
            else:
                ui.infopopup(
                    ["This operation needs the '{req}' permission, "
                     "but there is no current user.".format(
                            req=cls.permission_required[0])],
                    title="Not allowed")

class permission_checked(object):
    """
    Inherit from this class if you want your class to check
    permissions before allowing itself to be initialised.

    Set permission_required=(action,description) in your class to
    describe the permission required.

    """
    __metaclass__=_permission_checked_metaclass
    @classmethod
    def allowed(cls,user=None):
        """
        Can the specified user (or the current user if None) do this
        thing?

        """
        user=user or ui.current_user()
        if user is None: return False
        return user.has_permission(cls.permission_required[0])

class _permission_check(object):
    """
    Wrap a function to check that the current user has permission to
    do something before permitting the function to be called.

    """
    def __init__(self,action,description=None,func=None):
        self._action=action
        action_descriptions[action]=description
        self._func=func
        if func:
            self.func_doc=func.func_doc
            self.func_name=func.func_name
            self.__module__=func.__module__
            self.func_defaults=func.func_defaults
            self.func_code=func.func_code
            self.func_globals=func.func_globals
            self.func_dict=func.func_dict
            self.func_closure=func.func_closure
    def allowed(self,user=None):
        """
        Can the specified user (or the current user if None) do this
        thing?

        """
        user=user or ui.current_user()
        if user is None: return False
        return user.has_permission(self._action)
    def __get__(self,obj,objtype=None):
        return types.MethodType(self.__call__,obj,objtype)
    def __call__(self,*args,**kwargs):
        if not callable(self._func):
            raise TypeError("'permission_check' object is not callable")
        if self.allowed():
            self._func(*args,**kwargs)
        else:
            u=ui.current_user()
            if u:
                ui.infopopup(
                    ["{user} does not have the '{req}' permission "
                     "which is required for this operation.".format(
                            user=u.fullname, req=self._action)],
                    title="Not allowed")
            else:
                ui.infopopup(
                    ["This operation needs the '{req}' permission, "
                     "but there is no current user.".format(
                            req=self._action)],
                    title="Not allowed")
    def __repr__(self):
        return "permission_required('{}') for {}".format(
            self._action,repr(self._func))

class permission_required(object):
    """
    A factory that creates decorators that will perform a permission
    check on the current user before permitting the call.

    Use as follows:
    @permission_required('test','Perform tests')
    def do_test(...):
    pass

    Don't use this on the __init__ method of classes; subclass
    permission_checked and set the permission_required class attribute
    instead.  It's ok to use this on other methods of classes.

    """
    def __init__(self,action,description=None):
        self._action=action
        self._description=description
    def __call__(self,function):
        return _permission_check(self._action,self._description,function)

class group(object):
    """
    A group of permissions.  Groups always store their contents as a
    set, even if they are passed other groups.  Groups cannot refer to
    themselves.

    """
    all_groups={}
    def __new__(cls,name,*args,**kwargs):
        # Prevent creation of multiple groups with the same name -
        # merge them instead.
        if name in group.all_groups: return group.all_groups[name]
        self=object.__new__(cls)
        group.all_groups[name]=self
        return self
    def __init__(self,name,description,members=[]):
        action_descriptions[name]=description
        self.name=name
        if not hasattr(self,'members'): self.members=set()
        for m in members:
            if m in group.all_groups:
                self.members.update(group.all_groups[m].members)
            else:
                self.members.add(m)

def current_dbuser():
    user=ui.current_user()
    if user and hasattr(user,'dbuser'): return user.dbuser

class built_in_user(object):
    """
    A user defined in the configuration file.  Usually applied to a
    built-in page.

    permissions is a list of strings.  It's stored as-is for
    reference, and also flattened into a set for lookup purposes.

    """
    def __init__(self,fullname,shortname,permissions=[],is_superuser=False):
        self.fullname=fullname
        self.shortname=shortname
        self.permissions=permissions
        self.is_superuser=is_superuser
        self._flat_permissions=set()
        for m in permissions:
            if m in group.all_groups:
                self._flat_permissions.update(group.all_groups[m].members)
            else:
                self._flat_permissions.add(m)
    def has_permission(self,action):
        """
        Check whether this user has permission to perform the
        specified action.

        """
        if self.is_superuser: return True
        return action in self._flat_permissions
    @property
    def all_permissions(self):
        return list(self._flat_permissions)
    def display_info(self):
        def pl_display(perm):
            pl=sorted(perm)
            return ["  {0} ({1})".format(x,action_descriptions[x]) for x in pl]
        info=["Full name: {}".format(self.fullname),
                      "Short name: {}".format(self.shortname),""]
        if self.is_superuser:
            info.append("Has all permissions.")
        else:
            info=info+["Explicit permissions:"]+\
                pl_display(self.permissions)+\
                ["","All permissions:"]+\
                pl_display(self._flat_permissions)
        ui.infopopup(info,title="{} user information".format(self.fullname),
                     colour=ui.colour_info)

class database_user(built_in_user):
    """
    A user loaded from the database.  register pages require these,
    because they use the userid attribute to distinguish between
    different users.

    """
    def __init__(self,user):
        self.userid=user.id
        self.dbuser=user
        built_in_user.__init__(self,user.fullname,user.shortname,
                               permissions=[p.id for p in user.permissions],
                               is_superuser=user.superuser)

class token(object):
    """
    A token presented by a user at the terminal.  Usually passed to
    ui.handle_keyboard_input()

    """
    def __init__(self,t):
        self.usertoken=t
    def __repr__(self):
        return "token('{}')".format(self.usertoken)

class tokenlistener(object):
    def __init__(self,address):
        self.s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind(address)
        self.s.setblocking(0)
        event.rdlist.append(self)
    def fileno(self):
        return self.s.fileno()
    def doread(self):
        d=self.s.recv(1024).strip()
        log.debug("Received: {}".format(repr(d)))
        if d:
            tillconfig.unblank_screen()
            with td.orm_session():
                ui.handle_keyboard_input(token(d))

class tokeninfo(ui.ignore_hotkeys,ui.autodismiss,ui.infopopup):
    autodismisstime=2

def user_from_token(t):
    """
    Find a user given a token object.  Pops up a dialog box that
    ignores hotkeys to explain if the user can't be found.  (Ignoring
    hotkeys ensures the box can't pop up on top of itself.)

    """
    dbt=td.s.query(UserToken).\
        options(joinedload('user')).\
        options(joinedload('user.permissions')).\
        get(t.usertoken)
    if not dbt:
        tokeninfo(["User token '{}' not recognised.".format(t.usertoken)],
                   title="Unknown token")
        return
    dbt.last_seen=datetime.datetime.now()
    u=dbt.user
    if not u.enabled:
        tokeninfo(["User '{}' is not active.".format(u.fullname)],
                  title="User not active")
        return
    return database_user(u)

# Here is the user interface for adding, editing and deleting users.
class adduser(permission_checked,ui.dismisspopup):
    permission_required=('edit-user','Edit a user')
    def __init__(self):
        ui.dismisspopup.__init__(self,6,60,title="Add user",
                                 colour=ui.colour_input)
        self.addstr(2,2,' Full name:')
        self.addstr(3,2,'Short name:')
        self.fullnamefield=ui.editfield(2,14,40,keymap={
                keyboard.K_CLEAR: (self.dismiss,None)})
        self.shortnamefield=ui.editfield(3,14,30,keymap={
                keyboard.K_CASH: (self.enter,None)})
        ui.map_fieldlist([self.fullnamefield,self.shortnamefield])
        self.fullnamefield.focus()
    def enter(self):
        if not self.fullnamefield.f:
            ui.infopopup(["You must provide a full name."],title="Error")
            return
        if not self.shortnamefield.f:
            ui.infopopup(["You must provide a short name."],title="Error")
            return
        u=User(fullname=self.fullnamefield.f.strip(),
               shortname=self.shortnamefield.f.strip(),
               enabled=True)
        td.s.add(u)
        td.s.flush()
        self.dismiss()
        edituser(u.id)

class tokenfield(ui.ignore_hotkeys,ui.field):
    emptymessage="Use a token to fill in this field"
    def __init__(self,y,x,w,keymap={}):
        ui.field.__init__(self,keymap)
        self.y=y
        self.x=x
        self.w=w
        self.message=self.emptymessage
        self.f=None
        self.draw()
    def set(self,t):
        if t is None:
            self.f=None
            self.message=self.emptymessage
        else:
            dbt=td.s.query(UserToken).get(t)
            if dbt:
                self.message="In use by {}".format(
                    dbt.user.fullname)
                self.f=None
            else:
                self.f=t
        self.sethook()
        self.draw()
    def draw(self):
        pos=self.win.getyx()
        self.addstr(self.y,self.x,' '*self.w,ui.curses.A_REVERSE)
        if self.f:
            self.addstr(self.y,self.x,self.f[:self.w],ui.curses.A_REVERSE)
        else:
            if self.focused:
                self.addstr(self.y,self.x,self.message[:self.w],
                            ui.curses.A_REVERSE)
        if self.focused: self.win.move(self.y,self.x)
        else: self.win.move(*pos)
    def focus(self):
        ui.field.focus(self)
        self.draw()
    def defocus(self):
        ui.field.defocus(self)
        self.message=self.emptymessage
        self.draw()
    def keypress(self,k):
        if hasattr(k,'usertoken'):
            self.set(k.usertoken)
        elif k==keyboard.K_CLEAR and (
            self.f is not None or self.message!=self.emptymessage):
            self.set(None)
        else:
            ui.field.keypress(self,k)

class addtoken(ui.dismisspopup):
    def __init__(self,userid):
        self.userid=userid
        u=td.s.query(User).get(userid)
        ui.dismisspopup.__init__(self,6,66,title="Add token for {}".format(
                u.fullname),colour=ui.colour_input)
        self.addstr(2,2,'Description:')
        self.addstr(3,2,'      Token:')
        self.descfield=ui.editfield(2,20,40,keymap={
                keyboard.K_CLEAR: (self.dismiss,None)})
        self.tokenfield=tokenfield(3,20,40,keymap={
                keyboard.K_CASH: (self.save,None)})
        ui.map_fieldlist([self.descfield,self.tokenfield])
        self.descfield.focus()
    def save(self):
        desc=self.descfield.f.strip()
        if len(desc)==0 or self.tokenfield.f is None:
            ui.infopopup(["You must fill in both fields."],title="Error")
            return
        u=td.s.query(User).get(self.userid)
        t=UserToken(token=self.tokenfield.f,description=desc)
        u.tokens.append(t)
        td.s.flush()
        self.dismiss()

def do_add_permission(userid,permission):
    u=td.s.query(User).get(userid)
    p=Permission(id=permission,description=action_descriptions[permission])
    p=td.s.merge(p)
    u.permissions.append(p)
    td.s.flush()

def addpermission(userid):
    """
    Add a permission to a user.  Displays a list of all available
    permissions.

    """
    cu=ui.current_user()
    if cu.is_superuser:
        pl=action_descriptions.keys()
    else:
        pl=cu.all_permissions
    # Add in groups if the list of permissions includes everything in that group
    for g in group.all_groups:
        for m in group.all_groups[g].members:
            if m not in pl: break
        else: # else on a for loop is skipped if the loop was exited with break
            pl.append(g)
    # Remove permissions the user already has
    u=td.s.query(User).get(userid)
    existing=[p.id for p in u.permissions]
    pl=[p for p in pl if p not in existing]
    # Generally most users will be given group permissions, so we want
    # to sort the groups to the top of the list.
    pl=sorted(pl)
    pl=sorted(pl,key=lambda p:p not in group.all_groups)
    f=ui.tableformatter(' l l ')
    menu=[(f(p,action_descriptions[p]),
           do_add_permission,(userid,p)) for p in pl]
    ui.menu(menu,title="Give permission to {}".format(u.fullname),
            blurb="Choose the permission to give to {}".format(u.fullname))

class edituser(permission_checked,ui.basicpopup):
    permission_required=('edit-user','Edit a user')
    def __init__(self,userid):
        self.userid=userid
        u=td.s.query(User).get(userid)
        if u.superuser and not ui.current_user().is_superuser:
            ui.infopopup(["You can't edit {} because that user has the "
                          "superuser bit set and you do not.".format(
                        u.fullname)],title="Not allowed")
            return
        ui.basicpopup.__init__(self,12,60,title="Edit user",
                               colour=ui.colour_input)
        self.addstr(2,2,'   Full name:')
        self.addstr(3,2,'  Short name:')
        self.addstr(4,2,'Web username:')
        self.addstr(5,2,'      Active:')
        self.fnfield=ui.editfield(2,16,40,f=u.fullname)
        self.snfield=ui.editfield(3,16,30,f=u.shortname)
        self.wnfield=ui.editfield(4,16,30,f=u.webuser)
        self.actfield=ui.booleanfield(5,16,f=u.enabled,allow_blank=False)
        self.tokenfield=ui.buttonfield(7,7,15,"Edit tokens",keymap={
                keyboard.K_CASH: (self.edittokens,None)})
        self.permfield=ui.buttonfield(7,30,20,"Edit permissions",keymap={
                keyboard.K_CASH: (self.editpermissions,None)})
        self.savefield=ui.buttonfield(9,6,17,"Save and exit",keymap={
                keyboard.K_CASH: (self.save,None)})
        self.exitfield=ui.buttonfield(9,29,23,"Exit without saving",keymap={
                keyboard.K_CASH: (self.dismiss,None)})
        fl=[self.fnfield,self.snfield,self.wnfield,self.actfield,
            self.tokenfield,self.permfield,self.savefield,self.exitfield]
        if u.superuser and ui.current_user().is_superuser:
            fl.append(ui.buttonfield(5,25,30,"Remove superuser privilege",
                                     keymap={
                        keyboard.K_CASH: (self.remove_superuser,None)}))
        ui.map_fieldlist(fl)
        self.tokenfield.focus()
    def remove_superuser(self):
        self.dismiss()
        u=td.s.query(User).get(self.userid)
        u.superuser=False
        td.s.flush()
    def removetoken(self,token):
        t=td.s.query(UserToken).get(token)
        td.s.delete(t)
        td.s.flush()
    def edittokens(self):
        u=td.s.query(User).get(self.userid)
        f=ui.tableformatter(' l l l ')
        h=f("Description","Value","Last used")
        tl=[(f(x.description,x.token,x.last_seen),
             self.removetoken,(x.token,)) for x in u.tokens]
        tl.insert(0,("Add new token",addtoken,(self.userid,)))
        ui.menu(tl,title="Tokens for {}".format(u.fullname),
                blurb=["Select a token and press Cash/Enter to remove it.",
                       "",h])
    def removepermission(self,permission):
        u=td.s.query(User).get(self.userid)
        p=td.s.query(Permission).get(permission)
        u.permissions.remove(p)
        td.s.flush()
    def editpermissions(self):
        u=td.s.query(User).get(self.userid)
        f=ui.tableformatter(' l l ')
        pl=[(f(p.id,p.description),
             self.removepermission,(p.id,)) for p in u.permissions]
        pl.insert(0,("Add permission",addpermission,(self.userid,)))
        ui.menu(pl,title="Permissions for {}".format(u.fullname),
                blurb="Select a permission and press Cash/Enter to remove it.")
    def save(self):
        fn=self.fnfield.f.strip()
        sn=self.snfield.f.strip()
        wn=self.wnfield.f.strip()
        if len(fn)==0 or len(sn)==0:
            ui.infopoup(["You can't leave the full name or short name blank."],
                        title="Error")
            return
        u=td.s.query(User).get(self.userid)
        u.fullname=fn
        u.shortname=sn
        u.webuser=wn if len(wn)>0 else None
        u.enabled=self.actfield.f
        td.s.flush()
        self.dismiss()

def display_info(userid):
    u=td.s.query(User).get(userid)
    database_user(u).display_info()

# Permission descriptions for the users menu
action_descriptions['list-users']="List till users"

def usersmenu(include_inactive=False):
    """
    List, create and edit users.

    This menu displays different options depending on the permissions
    of the calling user.

    """
    u=ui.current_user()
    if u is None:
        ui.infopopup(["There is no current user."],title="No user info",
                     colour=ui.colour_info)
        return
    if not u.has_permission('list-users') and not u.has_permission('edit-user'):
        # A user who doesn't have the "list users" or "edit user"
        # permission will just see their own information.
        u.display_info()
        return
    q=td.s.query(User).order_by(User.fullname)
    if not include_inactive:
        q=q.filter(User.enabled==True)
    ul=q.all()
    if u.has_permission('edit-user'):
        f=ui.tableformatter(' l l l ')
        lines=[(f(x.fullname,x.shortname,
                  "(Active)" if x.enabled else "(Inactive)"),
                edituser,(x.id,)) for x in ul]
    else:
        f=ui.tableformatter(' l l ')
        lines=[(f(x.fullname,"(Active)" if x.enabled else "(Inactive)"),
                display_info,(x.id,)) for x in ul]
    if not include_inactive:
        lines.insert(0,("Include inactive users",usersmenu,(True,)))
    if u.has_permission('edit-user'):
        lines.insert(0,("Add new user",adduser,None))
    ui.menu(lines,title="User list",blurb="Select a user and press Cash/Enter")
