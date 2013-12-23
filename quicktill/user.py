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

"""

from . import ui
import functools

class ActionDescriptionRegistry(dict):
    def __getitem__(self,key):
        if key in self: return dict.__getitem__(self,key)
        else: return "undefined"
    def __setitem__(self,key,val):
        if key in self: return
        if val is None: return
        dict.__setitem__(self,key,val)

action_descriptions=ActionDescriptionRegistry()

# XXX at the moment we use this to decorate functions and class
# methods.  When we decorate the __init__ method of a class, callers
# that refer to the class don't see our 'allowed' method.  At some
# point we should extend this to be a class decorator too.
class permission_check(object):
    """
    Check that a user has permission to do something.

    """
    def __init__(self,action,description=None,func=None):
        self._action=action
        action_descriptions[action]=description
        self._func=func
        if func:
            self.func_doc=func.func_doc
            self.func_name=func.func_name
            self.func_dict=func.func_dict
    def allowed(self,user=None):
        """
        Can the specified user (or the current user if None) do this
        thing?

        """
        user=user or ui.current_user()
        if user is None: return False
        return user.has_permission(self._action)
    # When a class method is decorated, we have to take part in the
    # descriptor protocol to pass in the object instance
    def __get__(self,obj,objtype):
        return functools.partial(self.__call__,obj)
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

class permission_required(object):
    """
    A factory that creates decorators that will perform a permission
    check on the current user before permitting the call.

    Use as follows:
    @permission_required('test','Perform tests')
    def do_test(...):
    pass

    """
    def __init__(self,action,description=None):
        self._action=action
        self._description=description
    def __call__(self,function):
        return permission_check(self._action,self._description,function)

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
        ui.infopopup(["Full name: {}".format(self.fullname),
                      "Short name: {}".format(self.shortname),"",
                      "Explicit permissions:"]+
                     pl_display(self.permissions)+
                     ["","All permissions:"]+
                     pl_display(self._flat_permissions),
                     title="{} user information".format(self.fullname),
                     colour=ui.colour_info)
