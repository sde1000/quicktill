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

from . import ui,td,event
from .models import User,UserToken,Permission
import socket,logging
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
    def __get__(self,obj,objtype):
        self._func.__get__(obj,objtype)
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
    dbt=td.s.query(UserToken).get(t.usertoken)
    if not dbt:
        tokeninfo(["User token '{}' not recognised.".format(t.usertoken)],
                   title="Unknown token")
        return
    u=dbt.user
    if not u.enabled:
        tokeninfo(["User '{}' is not active.".format(u.fullname)],
                  title="User not active")
        return
    return database_user(u)
