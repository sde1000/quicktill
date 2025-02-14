"""Users and permissions.

Users are granted access to Groups of Permissions.

We maintain a dictionary in which we can look up descriptions of
actions that are collected from the places these actions are used.
The dictionary stores the first description it sees for each action;
the assumption is that old descriptions loaded from the database will
be superseded by descriptions from the code, which will be seen first.

This module provides a class to derive from (permission_checked) and a
function decorator (permission_required) for other modules to use to
indicate restricted functionality.
"""

from . import ui, td, keyboard, tillconfig, cmdline, config, passwords
from .models import User, UserToken, Permission, Group, LogEntry
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
import socket
import logging
import datetime


password_check_after = config.IntervalConfigItem(
    'user:password_check_after', None,
    display_name='Prompt for password after',
    description=('How long to allow a user token to be unused before a '
                 'password is required to log in. A blank value will disable '
                 'password checking at login.')
)

require_user_passwords = config.BooleanConfigItem(
    'user:require_user_passwords', False,
    display_name='Require users to have passwords',
    description=('When set, require users without a password to set one when '
                 'they next try to use the till. When not set, users will '
                 'be allowed to clear their own passwords.')
)

allow_password_only_login = config.BooleanConfigItem(
    'user:allow_password_only_login', False,
    display_name='Allow users to log in with user ID and password',
    description=('Allow users to log in with only their user ID and password, '
                 'without using a user token. Requires the K_PASS_LOGIN key '
                 'to be present on the keyboard.')
)


# We declare 'log' later on for writing log entries to the database
debug_log = logging.getLogger(__name__)


class ActionDescriptionRegistry(dict):
    def __getitem__(self, key):
        if key in self:
            return dict.__getitem__(self, key)
        else:
            return "undefined"

    def __setitem__(self, key, val):
        if key in self:
            return
        if val is None:
            return
        dict.__setitem__(self, key, val)


action_descriptions = ActionDescriptionRegistry()


class _permission_checked_metaclass(type):
    """Metaclass for permission_checked classes."""
    def __new__(meta, name, bases, dct):
        # Called when a permission_checked class is defined.  Look at
        # the permission_required and register its action description.
        pr = dct.get("permission_required")
        if pr:
            action_descriptions[pr[0]] = pr[1]
        return type.__new__(meta, name, bases, dct)

    def __call__(cls, *args, **kwargs):
        # Called when a permission_checked class is about to be
        # instantiated

        if cls.permission_required is None:
            # allow permission_required to be set to None, if subclasses
            # want to override the permission_required of their parent and
            # remove the permission check entirely
            return type.__call__(cls, *args, **kwargs)

        u = ui.current_user()
        if cls.allowed(u):
            return type.__call__(cls, *args, **kwargs)
        else:
            if u:
                ui.infopopup(
                    [f"{u.fullname} does not have the "
                     f"'{cls.permission_required[0]}' permission "
                     "which is required for this operation."],
                    title="Not allowed")
            else:
                ui.infopopup(
                    [f"This operation needs the "
                     f"'{cls.permission_required[0]}' permission, "
                     f"but there is no current user."],
                    title="Not allowed")


class permission_checked(object, metaclass=_permission_checked_metaclass):
    """Base class for restricted access classes

    Inherit from this class if you want your class to check
    permissions before allowing itself to be initialised.

    Set permission_required = (action, description) in your class to
    describe the permission required.
    """
    @classmethod
    def allowed(cls, user=None):
        """Check permission

        Can the specified user (or the current user if None) do this
        thing?
        """
        user = user or ui.current_user()
        if user is None:
            return False
        return user.may(cls.permission_required[0])


class permission_required:
    """Function decorator to perform permission check

    A factory that creates decorators that will perform a permission
    check on the current user before permitting the call.

    Use as follows:
    @permission_required('test', 'Perform tests')
    def do_test(...):
        pass

    Don't use this on the __init__ method of classes; subclass
    permission_checked and set the permission_required class attribute
    instead.  It's ok to use this on other methods of classes.
    """
    def __init__(self, action, description=None):
        self._action = action
        self._description = description
        if description:
            action_descriptions[action] = description

    def __call__(self, function):
        """Decorate a function to perform the permission check"""
        def allowed(user=None):
            user = user or ui.current_user()
            if user is None:
                return False
            return user.may(self._action)

        def permission_check(*args, **kwargs):
            if allowed():
                return function(*args, **kwargs)
            else:
                u = ui.current_user()
                if u:
                    ui.infopopup(
                        [f"{u.fullname} does not have the '{self._action}' "
                         f"permission which is required for this operation."],
                        title="Not allowed")
                else:
                    ui.infopopup(
                        [f"This operation needs the '{self._action}' "
                         f"permission, but there is no current user."],
                        title="Not allowed")
        permission_check.allowed = allowed
        return permission_check


_permissions_checked = False


def _check_permissions():
    """Check that all permissions exist, and assign to default groups
    """
    global _permissions_checked
    if _permissions_checked:
        return
    # The common case will be that no new permissions have been
    # created.  Load all existing permissions at once in a single
    # database query.  We'll only make further queries if we have a
    # new permission.
    td.s.query(Permission).all()
    for p, d in action_descriptions.items():
        dbperm = td.s.get(Permission, p)
        if dbperm:
            if dbperm.description != d:
                dbperm.description = d
            continue
        dbperm = Permission(id=p, description=d)
        td.s.add(dbperm)
        accumulated_permissions = set()
        for group, description, permissions in default_groups.groups:
            accumulated_permissions.update(permissions)
            dbgroup = td.s.get(Group, group)
            if not dbgroup:
                dbgroup = Group(id=group, description=description)
                td.s.add(dbgroup)
            if p in accumulated_permissions:
                dbgroup.permissions.append(dbperm)
    td.s.flush()
    _permissions_checked = True


def current_dbuser():
    user = ui.current_user()
    if user and hasattr(user, 'dbuser'):
        return user.dbuser


class built_in_user:
    """A user not present in the database

    A user defined in the configuration file.  Usually applied to a
    built-in page.

    permissions is a list of strings.  It's stored as-is for
    reference, and also flattened into a set for lookup purposes.
    """
    def __init__(self, fullname, shortname, permissions=[],
                 is_superuser=False):
        self.fullname = fullname
        self.shortname = shortname
        self.permissions = permissions
        self.is_superuser = is_superuser
        self._flat_permissions = set(permissions)

    def may(self, action):
        """May this user perform the specified action?

        Superusers can do anything!
        """
        if self.is_superuser:
            return True
        return self.has_permission(action)

    def has_permission(self, action):
        """Does this user have the specified permission?

        This ignores the superuser flag.
        """
        return action in self._flat_permissions

    @property
    def all_permissions(self):
        return list(self._flat_permissions)

    def display_info(self):
        def pl_display(perm):
            pl = sorted(perm)
            if pl:
                return [f"  {x} ({action_descriptions[x]})" for x in pl]
            else:
                return ["  (None)"]
        info = [f"User ID: {self.userid}",
                f"Full name: {self.fullname}",
                f"Short name: {self.shortname}", ""]
        if self.is_superuser:
            info.append("Has all permissions.")
        else:
            info = info + ["Permissions:"]\
                + pl_display(self._flat_permissions)
        ui.infopopup(info, title=f"{self.fullname} user information",
                     colour=ui.colour_info)


class database_user(built_in_user):
    """A user loaded from the database.

    register pages require these, because they use the userid
    attribute to distinguish between different users.
    """
    def __init__(self, user):
        self.userid = user.id
        self.dbuser = user
        super().__init__(
            user.fullname, user.shortname,
            permissions=[p.id for p in user.permissions],
            is_superuser=user.superuser)


def load_user(userid):
    """Load the specified user from the database

    Load the specified user from the database and return a user object
    for them.  If the user does not exist or is not active, return
    None.
    """
    if not userid:
        return
    _check_permissions()
    dbuser = td.s.get(User, userid)
    if not dbuser or not dbuser.enabled:
        return
    return database_user(dbuser)


class token:
    """A user token

    A token presented by a user at the terminal.  Usually passed to
    ui.handle_keyboard_input()
    """
    def __init__(self, t):
        self.usertoken = t

    def __eq__(self, other):
        if not isinstance(other, token):
            return False
        return self.usertoken == other.usertoken

    def __hash__(self):
        return hash(self.usertoken)

    def __repr__(self):
        return f"token('{self.usertoken}')"


class tokenkey(token):
    """A key that represents a user token
    """
    def __init__(self, t, label):
        super().__init__(t)
        self.keycap = label

    def __str__(self):
        return self.keycap


class tokenlistener:
    def __init__(self, address, addressfamily=socket.AF_INET):
        self.s = socket.socket(addressfamily, socket.SOCK_DGRAM)
        self.s.bind(address)
        self.s.setblocking(0)
        tillconfig.mainloop.add_fd(self.s.fileno(), self.doread,
                                   desc="token listener")

    def doread(self):
        d = self.s.recv(1024).strip().decode("utf-8")
        debug_log.debug(f"Received: {repr(d)}")
        if d:
            ui.unblank_screen()
            with td.orm_session():
                ui.handle_keyboard_input(token(d))


def _should_prompt_for_password(dbt):
    """Determine whether the token password timeout has lapsed.

    If true, the user should be prompted to enter their password (if they have
    one).
    """
    if not password_check_after():
        return False

    if not dbt.last_successful_login:
        return True

    return (datetime.datetime.now() - dbt.last_successful_login) \
        > password_check_after()


def token_login(t):
    """Log in a user from a usertoken.
    """
    _check_permissions()

    dbt = td.s.get(UserToken, t.usertoken, options=[
        joinedload(UserToken.user),
        joinedload(UserToken.user).joinedload(User.permissions)])
    if not dbt:
        ui.toast(f"User token '{t.usertoken}' not recognised.")
        return

    dbt.last_seen = datetime.datetime.now()

    u = dbt.user
    if not u:
        ui.toast(f"User token '{t.usertoken}' ({dbt.description}) is not "
                 f"assigned to a user")
        return
    if not u.enabled:
        ui.toast(f"User '{u.fullname}' is not active.")
        return

    if require_user_passwords() and not u.password:
        _change_current_user_password_login_initial(u.id)
        return

    if u.password:
        if _should_prompt_for_password(dbt):
            _password_prompt(dbt)
            return
        dbt.last_successful_login = datetime.datetime.now()

    _finish_login(u)


def password_login():
    """Log in a user by prompting for user ID and password.
    """
    if not allow_password_only_login():
        ui.toast("Password-only login is not enabled. Use a token to log in.")
        return

    _password_login_prompt()


def _finish_login(u):
    """Complete the user module side of the login and return to the till or
    stock terminal.
    """
    u.last_seen = datetime.datetime.now()
    tillconfig.login_handler(database_user(u))


class _dismiss_on_token_or_login_key:
    """Mixin class to prevent multiple login-related popups
    """
    def hotkeypress(self, k):
        if k == keyboard.K_PASS_LOGIN or hasattr(k, 'usertoken'):
            self.dismiss()
        super().hotkeypress(k)


class _password_prompt(_dismiss_on_token_or_login_key, ui.dismisspopup):
    def __init__(self, dbt):
        super().__init__(8, 40, title=dbt.user.shortname,
                         colour=ui.colour_input)
        self.t = dbt.token
        self.win.wrapstr(2, 2, 36,
                         'Enter your password then press Cash/Enter.')
        self.password = ui.editfield(5, 2, 36, keymap={
            keyboard.K_CASH: (self.check_password, None)}, hidden=True)
        self.password.focus()

    def check_password(self):
        if not self.password.f:
            ui.infopopup(["You must provide a password."], title="Error")
            return

        dbt = td.s.get(UserToken, self.t, options=[
            joinedload(UserToken.user),
            joinedload(UserToken.user).joinedload(User.permissions)])

        if not passwords.check_password(self.password.f, dbt.user.password):
            ui.infopopup(["Incorrect password. If you have forgotten your "
                          "password, call your manager for help resetting it."],
                         title="Error")
            self.password.clear()
            return

        dbt.last_successful_login = datetime.datetime.now()

        self.dismiss()

        _finish_login(dbt.user)


class _password_login_prompt(_dismiss_on_token_or_login_key, ui.dismisspopup):
    def __init__(self):
        super().__init__(10, 40, title="Log In",
                         colour=ui.colour_input)
        self.win.wrapstr(2, 2, 36,
                         'Enter your user ID and password then press '
                         'Cash/Enter.')
        self.win.drawstr(5, 2, 12, "User ID: ", align='>')
        self.win.drawstr(6, 2, 12, "Password: ", align='>')
        self.win.drawstr(5, 20, 6, "Name: ", align=">")
        self.uname = ui.editfield(5, 26, 9, readonly=True)
        uid_keymap = {
            keyboard.K_CASH: (self.check_uid, None),
            keyboard.K_DOWN: (self.check_uid, None),
            keyboard.K_TAB: (self.check_uid, None),
        }
        self.uid = ui.editfield(5, 14, 5,
                                validate=ui.validate_positive_nonzero_int,
                                keymap=uid_keymap)
        password_keymap = {
            keyboard.K_CASH: (self.check_password, None),
            keyboard.K_UP: (self.clear, None),
            keyboard.K_CLEAR: (self.clear, None),
            keyboard.K_TAB: (self.clear, None),
        }
        self.password = ui.editfield(6, 14, 21, keymap=password_keymap,
                                     hidden=True)
        self.uid.focus()

    def check_uid(self):
        if not self.uid.f:
            ui.infopopup(["You must provide a user ID."], title="Error")
            return

        dbu = td.s.get(User, self.uid.f)

        if not dbu:
            ui.infopopup([f"The user with ID {self.uid.f} does not exist."],
                         title="Error")
            self.uid.clear()
            return

        if not dbu.password:
            ui.infopopup([f"The user with ID {self.uid.f} does not have a "
                          "password. Call your manager for help setting "
                          "one."],
                         title="Error")
            self.uid.clear()
            return

        self.uname.set(dbu.shortname)
        self.password.focus()

    def clear(self):
        self.uname.clear()
        self.uid.clear()
        self.password.clear()
        self.uid.focus()

    def check_password(self):
        if not self.password.f:
            ui.infopopup(["You must provide a password."], title="Error")
            return

        dbu = td.s.get(User, self.uid.f)

        if not dbu:
            ui.infopopup([f"The user with ID {self.uid.f} does not exist."],
                         title="Error")
            self.uid.clear()
            return

        if not dbu.enabled:
            ui.infopopup(["This user is not enabled."], title="Error")
            self.uid.clear()
            return

        if not passwords.check_password(self.password.f, dbu.password):
            ui.infopopup(["Incorrect password. If you have forgotten your "
                          "password, call your manager for help resetting it."],
                         title="Error")
            self.password.clear()
            return

        self.dismiss()

        _finish_login(dbu)


class LogError(Exception):
    """Tried to make an entry in the user activity log with no current user
    """
    pass


def log(message):
    """Record an entry in the user activity log
    """
    u = current_dbuser()
    if not u:
        raise LogError
    le = LogEntry(source=tillconfig.terminal_name,
                  loguser=u,
                  description=message)
    le.update_refs(td.s)
    td.s.add(le)


# Here is the user interface for adding, editing and deleting users.
class adduser(permission_checked, ui.dismisspopup):
    permission_required = ('edit-user', 'Edit a user')

    def __init__(self):
        super().__init__(6, 60, title="Add user",
                         colour=ui.colour_input)
        self.win.drawstr(2, 2, 12, 'Full name: ', align=">")
        self.win.drawstr(3, 2, 12, 'Short name: ', align=">")
        self.fullnamefield = ui.editfield(2, 14, 40, keymap={
            keyboard.K_CLEAR: (self.dismiss, None)})
        self.shortnamefield = ui.editfield(3, 14, 30, keymap={
            keyboard.K_CASH: (self.enter, None)})
        ui.map_fieldlist([self.fullnamefield, self.shortnamefield])
        self.fullnamefield.focus()

    def enter(self):
        if not self.fullnamefield.f:
            ui.infopopup(["You must provide a full name."], title="Error")
            return
        if not self.shortnamefield.f:
            ui.infopopup(["You must provide a short name."], title="Error")
            return
        u = User(fullname=self.fullnamefield.f.strip(),
                 shortname=self.shortnamefield.f.strip(),
                 enabled=True)
        td.s.add(u)
        td.s.flush()
        log(f"Added new user {u.logref}")
        self.dismiss()
        edituser(u.id)


class tokenfield(ui.ignore_hotkeys, ui.valuefield):
    emptymessage = "Use a token to fill in this field"

    def __init__(self, y, x, w, allow_inuse=False, keymap={}):
        self.y = y
        self.x = x
        self.w = w
        self.message = self.emptymessage
        self.f = None
        self._allow_inuse = allow_inuse
        super().__init__(keymap)
        self.draw()

    def set(self, t):
        if t is None:
            self.f = None
            self.message = self.emptymessage
        else:
            dbt = td.s.get(UserToken, t)
            if dbt and dbt.user and not self._allow_inuse:
                self.message = f"In use by {dbt.user.fullname}"
                self.f = None
            else:
                self.f = t
        self.sethook()
        self.draw()

    def draw(self):
        pos = self.win.getyx()
        self.win.clear(self.y, self.x, 1, self.w,
                       colour=self.win.colour.reversed)
        if self.f:
            self.win.drawstr(self.y, self.x, self.w, self.f,
                             colour=self.win.colour.reversed)
        else:
            if self.focused:
                self.win.drawstr(self.y, self.x, self.w, self.message,
                                 colour=self.win.colour.reversed)
        if self.focused:
            self.win.move(self.y, self.x)
        else:
            self.win.move(*pos)

    def focus(self):
        super().focus()
        self.draw()

    def defocus(self):
        super().defocus()
        self.message = self.emptymessage
        self.draw()

    def keypress(self, k):
        if hasattr(k, 'usertoken'):
            self.set(k.usertoken)
        elif k == keyboard.K_CLEAR and (
                self.f is not None or self.message != self.emptymessage):
            self.set(None)
        else:
            super().keypress(k)


class change_user_password(permission_checked, ui.dismisspopup):
    """Change a user's password.

    A user can change their own password with the change_current_user_password
    function.

    If can_clear is True, it will be possible to clear the password for the
    user.
    """
    permission_required = ('edit-user-password', 'Edit a user\'s password')

    def __init__(self, userid, can_clear=True):
        self.userid = userid
        self.can_clear = can_clear
        user = td.s.get(User, userid)
        super().__init__(8, 60, title=f"Change password for {user.fullname}",
                         colour=ui.colour_input)
        self.win.drawstr(2, 2, 56, ('Type in the new password then '
                                    'press Cash/Enter.'))

        if self.can_clear:
            self.win.drawstr(3, 2, 56, ('To clear the password, leave the '
                                        'field blank.'))

        self.win.drawstr(5, 2, 14, 'Password: ', align=">")
        self.password = ui.editfield(5, 16, 40, keymap={
            keyboard.K_CASH: (self.save, None)}, hidden=True)

        self.password.focus()

    def save(self):
        if not self.can_clear and \
                (not self.password.f or len(self.password.f) < 1):
            ui.infopopup(["You must provide a password."], title="Error")
            return

        user = td.s.get(User, self.userid)

        if not self.password.f:
            user.password = None
            ui.toast(f'Password for user "{user.fullname}" removed.')

            if user.id != ui.current_user().userid:
                log(f'Cleared password for {user.logref}')
        else:
            user.password = passwords.compute_password_tuple(self.password.f)
            ui.toast(f'Password for user "{user.fullname}" changed.')

            if user.id != ui.current_user().userid:
                log(f'Changed password for {user.logref}')

        self.dismiss()

        self.after_change(user)

    def after_change(self, dbu):
        pass


class change_current_user_password(change_user_password):
    """Change the password of the current user.

    This actually just calls change_user_password, but with the user forced
    to be the current user, and with a different permission requirement.
    """
    permission_required = ('edit-current-user-password',
                           'Edit the password of the current user')

    def __init__(self):
        super().__init__(ui.current_user().userid,
                         can_clear=(not require_user_passwords()))


class _change_current_user_password_login_initial(
        _dismiss_on_token_or_login_key, ui.infopopup):
    def __init__(self, userid):
        self.userid = userid
        super().__init__([('The system is configured to require users to set '
                           'a password to log in. You must set a password '
                           'now.'),
                          '',
                          ('If you do not want to set a password now, you '
                           'can press Cancel to cancel this log on attempt.'),
                          '',
                          ('Press Cash/Enter to continue to set a '
                           'password.')],
                         dismiss=keyboard.K_CANCEL,
                         colour=ui.colour_info)

    def keypress(self, k):
        if k == keyboard.K_CASH:
            self.dismiss()
            _change_current_user_password_login(self.userid)
        else:
            super().keypress(k)


class _change_current_user_password_login(
        _dismiss_on_token_or_login_key, change_user_password):
    """Initialise a password for a user that is logging in without a password,
    but where one is required by the system configuration.

    This is functionally equivalent to change_current_user_password, but
    no permission is required.

    If the user already has a password set, an error will be displayed instead,
    although this should never happen if this is implemented correctly...
    """
    permission_required = None

    def __init__(self, userid):
        dbu = td.s.get(User, userid)
        if dbu.password:
            ui.infopopup([f"User '{dbu.fullname}' already has a password set."],
                         title="Error")
            return

        super().__init__(userid, can_clear=False)

    def after_change(self, dbu):
        _finish_login(dbu)


class manage_user_tokens(ui.dismisspopup):
    """Manage the tokens assigned to a user
    """
    def __init__(self, userid):
        self.userid = userid
        user = td.s.get(User, userid)
        super().__init__(15, 60, title=f"Manage tokens for {user.fullname}",
                         colour=ui.colour_input)
        self.win.drawstr(2, 2, 13, "Token: ", align=">")
        self.win.drawstr(3, 2, 13, "Description: ", align=">")
        self.tokenfield = tokenfield(
            2, 15, 40,
            keymap={keyboard.K_CLEAR: (self.dismiss, None)})
        self.description = ui.editfield(3, 15, 40)
        self.tokenfield.sethook = self.tokenfield_set
        self.description.sethook = self.description_set
        self.add_button = ui.buttonfield(5, 3, 13, "Add token", keymap={
            keyboard.K_CASH: (self.add_token, None)})
        self.exit_button = ui.buttonfield(5, 18, 10, "Exit", keymap={
            keyboard.K_CASH: (self.dismiss, None)})
        self.tokens = ui.scrollable(8, 1, 58, 6, [], keymap={
            keyboard.K_CANCEL: (self.delete_token, None)})
        self.win.bordertext("Press Cancel to delete a token", "L<")
        ui.map_fieldlist([self.tokenfield, self.description,
                          self.add_button, self.exit_button,
                          self.tokens])
        self.reload_tokens()
        self.tokenfield.focus()

    def reload_tokens(self):
        user = td.s.get(User, self.userid)
        f = ui.tableformatter(' l l l ')
        h = f("Token", "Description", "Last used")
        tl = [f(x.token, x.description, ui.formattime(x.last_seen) or "Never",
                userdata=x.token) for x in user.tokens]
        self.win.clear(7, 1, 1, 58)
        if tl:
            self.win.addstr(7, 1, h.display(58)[0])
        self.tokens.set(tl)

    def delete_token(self):
        if self.tokens.cursor is None:
            return
        line = self.tokens.dl.pop(self.tokens.cursor)
        self.tokens.redraw()
        token = td.s.get(UserToken, line.userdata)
        token.user = None
        td.s.flush()

    def add_token(self):
        t = self.tokenfield.f
        if not t:
            ui.infopopup(["You must use a token to fill in the 'Token' field "
                          "before pressing the Add Token button."],
                         title="Error")
            return
        user = td.s.get(User, self.userid)
        token = td.s.get(UserToken, t)
        if not token:
            token = UserToken(token=t)
        token.last_seen = None
        token.last_successful_login = None
        user.tokens.append(token)  # adds token to ORM session if not present
        td.s.flush()
        self.tokenfield.set(None)
        self.description.set("")
        self.reload_tokens()
        self.tokenfield.focus()

    def tokenfield_set(self):
        t = self.tokenfield.f
        if t:
            dbt = td.s.get(UserToken, t)
            if dbt:
                self.description.set(dbt.description)
            else:
                self.description.set("")
        else:
            self.description.set("")

    def description_set(self):
        if self.tokenfield.f:
            dbt = td.s.get(UserToken, self.tokenfield.f)
            if not dbt:
                dbt = UserToken(token=self.tokenfield.f)
                td.s.add(dbt)
            dbt.description = self.description.f


def do_add_group(userid, group):
    u = td.s.get(User, userid)
    g = td.s.get(Group, group)
    u.groups.append(g)
    log(f"Granted permission group {g.logref} to {u.logref}")
    td.s.flush()


def addgroup(userid):
    """Add a permission to a user.

    Displays a list of all available groups.
    """
    gl = td.s.query(Group).order_by(Group.id).all()
    # Remove permissions the user already has
    u = td.s.get(User, userid)
    existing = [g.id for g in u.groups]
    gl = [g for g in gl if g not in existing]
    f = ui.tableformatter(' l l ')
    menu = [(f(g.id, g.description),
             do_add_group, (userid, g.id)) for g in gl]
    ui.menu(menu, title=f"Give permission group to {u.fullname}",
            blurb=f"Choose the permission group to give to {u.fullname}")


class edituser(permission_checked, ui.basicpopup):
    permission_required = ('edit-user', 'Edit a user')

    def __init__(self, userid):
        self.userid = userid
        u = td.s.get(User, userid)
        if u.superuser and not ui.current_user().is_superuser:
            ui.infopopup(
                [f"You can't edit {u.fullname} because that user has the "
                 "superuser bit set and you do not."], title="Not allowed")
            return
        super().__init__(15, 60, title="Edit user", colour=ui.colour_input)
        self.win.drawstr(2, 2, 14, 'User ID: ', align='>')
        self.win.drawstr(3, 2, 14, 'Full name: ', align=">")
        self.win.drawstr(4, 2, 14, 'Short name: ', align=">")
        self.win.drawstr(5, 2, 14, 'Web username: ', align=">")
        self.win.drawstr(6, 2, 14, 'Active: ', align=">")
        self.win.drawstr(2, 16, 5, str(u.id))
        self.fnfield = ui.editfield(3, 16, 40, f=u.fullname)
        self.snfield = ui.editfield(4, 16, 30, f=u.shortname)
        self.wnfield = ui.editfield(5, 16, 30, f=u.webuser)
        self.actfield = ui.booleanfield(6, 16, f=u.enabled, allow_blank=False)
        self.tokenfield = ui.buttonfield(8, 7, 20, "Edit tokens", keymap={
            keyboard.K_CASH: (manage_user_tokens, (self.userid,))})
        self.permfield = ui.buttonfield(8, 30, 20, "Edit permissions", keymap={
            keyboard.K_CASH: (self.editpermissions, None)})
        self.passfield = ui.buttonfield(10, 18, 21, "Change password", keymap={
            keyboard.K_CASH: (change_user_password, (self.userid,))})
        self.savefield = ui.buttonfield(12, 6, 17, "Save and exit", keymap={
            keyboard.K_CASH: (self.save, None)})
        self.exitfield = ui.buttonfield(
            12, 29, 23, "Exit without saving", keymap={
                keyboard.K_CASH: (self.dismiss, None)})
        fl = [self.fnfield, self.snfield, self.wnfield, self.actfield,
              self.tokenfield, self.permfield, self.passfield, self.savefield,
              self.exitfield]
        if u.superuser and ui.current_user().is_superuser:
            fl.append(ui.buttonfield(
                6, 25, 30, "Remove superuser privilege", keymap={
                    keyboard.K_CASH: (self.remove_superuser, None)}))
        ui.map_fieldlist(fl)
        self.tokenfield.focus()

    def remove_superuser(self):
        self.dismiss()
        u = td.s.get(User, self.userid)
        u.superuser = False
        log(f"Removed superuser status from {u.logref}")

    def removepermission(self, group):
        u = td.s.get(User, self.userid)
        g = td.s.get(Group, group)
        u.groups.remove(g)
        log(f"Removed permission group {g.logref} from {u.logref}")

    def editpermissions(self):
        u = td.s.get(User, self.userid)
        f = ui.tableformatter(' l l ')
        pl = [(f(g.id, g.description),
               self.removepermission, (g.id,)) for g in u.groups]
        pl.insert(0, ("Add permission group", addgroup, (self.userid,)))
        ui.menu(pl, title=f"Permissions for {u.fullname}",
                blurb="Select a permission group and press Cash/Enter "
                "to remove it.")

    def save(self):
        fn = self.fnfield.f.strip()
        sn = self.snfield.f.strip()
        wn = self.wnfield.f.strip()
        if len(fn) == 0 or len(sn) == 0:
            ui.infopopup(
                ["You can't leave the full name or short name blank."],
                title="Error")
            return
        u = td.s.get(User, self.userid)
        u.fullname = fn
        u.shortname = sn
        u.webuser = wn if len(wn) > 0 else None
        u.enabled = self.actfield.read()
        self.dismiss()
        # Update current_user().dbuser to ensure it is in the database
        # session; it may be a detached instance in some circumstances
        cu = ui.current_user()
        cu.dbuser = td.s.get(User, cu.userid)
        log(f"Updated details for user {u.logref}")


def display_info(userid=None):
    if userid is None:
        u = ui.current_user()
        if u:
            u.display_info()
        else:
            ui.infopopup(["There is no current user."], title="User info",
                         colour=ui.colour_info)
    else:
        u = database_user(td.s.get(User, userid))
        u.display_info()


def usersmenu():
    """Create and edit users and tokens
    """
    ui.keymenu(
        [("1", "Users", manageusers, None),
         ("2", "Tokens", managetokens, None),
         ("3", "Current user information", display_info, None),
         ("4", "Change my password", change_current_user_password, None),
         ], title="Manage Users")


def reactivate_user(userid):
    u = td.s.get(User, userid)
    u.enabled = True
    ui.toast(f'User "{u.fullname}" reactivated.')
    log(f"Reactivated user {u.logref}")
    edituser(userid)


@permission_required('edit-user', 'Edit a user')
def maybe_adduser():
    """Check for inactive users before adding a new user

    Experience shows that managers tend to add duplicate users rather
    than reactivating existing users.

    If there are any inactive users, show a list of them and invite
    the user to reactivate one instead of adding a new user.
    """
    inactive_users = td.s.query(User).filter(User.enabled == False)\
                                     .order_by(User.fullname)\
                                     .all()
    if not inactive_users:
        return adduser()

    f = ui.tableformatter(' l l ')
    lines = [(f(x.fullname, x.shortname), reactivate_user, (x.id,))
             for x in inactive_users]
    lines.append(("Add new user", adduser, None))

    ui.menu(lines, title="Check inactive users",
            blurb="Is the person you want to add already in this list "
            "of inactive user records?  If they are, pick them from the list "
            "to reactivate them.")


@permission_required("list-users", "List till users")
def manageusers(include_inactive=False):
    """List, create and edit users.
    """
    q = td.s.query(User).order_by(User.fullname)
    if not include_inactive:
        q = q.filter(User.enabled == True)
    ul = q.all()
    # There is guaranteed to be a current user because the
    # permission_required() check will have passed to get here
    u = ui.current_user()
    may_edit = u.may('edit-user')
    f = ui.tableformatter(' l l l ')
    lines = [(f(x.fullname, x.shortname,
                "(Active)" if x.enabled else "(Inactive)"),
              edituser if may_edit else display_info, (x.id,)) for x in ul]
    if not include_inactive:
        lines.insert(0, ("Include inactive users", manageusers, (True,)))
    if u.may('edit-user'):
        lines.insert(0, ("Add new user", maybe_adduser, None))
    ui.menu(lines, title="User list",
            blurb="Select a user and press Cash/Enter")


class managetokens(permission_checked, ui.dismisspopup):
    """Manage the users assigned to tokens
    """
    permission_required = ("manage-tokens", "Manage user login tokens")

    def __init__(self):
        super().__init__(12, 60, title="Manage tokens", colour=ui.colour_input)
        self.win.drawstr(2, 2, 13, "Token: ", align=">")
        self.win.drawstr(3, 2, 13, "Description: ", align=">")
        self.win.drawstr(4, 2, 13, "Assigned to: ", align=">")
        self.win.drawstr(5, 2, 13, "Last used: ", align=">")
        self.tokenfield = tokenfield(
            2, 15, 40, allow_inuse=True,
            keymap={keyboard.K_CLEAR: (self.dismiss, None)})
        self.description = ui.editfield(3, 15, 40)
        ui.map_fieldlist([self.tokenfield, self.description])
        self.user = ui.label(4, 15, 40)
        self.lastused = ui.label(5, 15, 40)
        self.opt_1 = ui.label(7, 2, 50)
        self.opt_2 = ui.label(8, 2, 50)
        self.opt_3 = ui.label(9, 2, 50)
        self.tokenfield.sethook = self.tokenfield_set
        self.description.sethook = self.description_set
        self.tokenfield.focus()

    def tokenfield_set(self):
        t = self.tokenfield.f
        if t:
            dbt = td.s.get(UserToken, t)
            if dbt and dbt.user:
                self.description.set(dbt.description)
                self.user.set(dbt.user.fullname)
                self.lastused.set(
                    f"{dbt.last_seen:%Y-%m-%d %H:%M}" if dbt.last_seen
                    else "Never")
                self.opt_1.set("1. Assign this token to a different user")
                self.opt_2.set("2. Remove this token from {}".format(
                    dbt.user.fullname))
                self.opt_3.set("3. Forget about this token")
            else:
                self.user.set("(not assigned)")
                if dbt:
                    self.description.set(dbt.description)
                    self.lastused.set(str(dbt.last_seen) or "never")
                else:
                    self.description.set("")
                    self.lastused.set("")
                self.opt_1.set("1. Assign this token to a user")
                self.opt_2.set("")
                self.opt_3.set("3. Forget about this token")
        else:
            self.description.set("")
            self.user.set("")
            self.lastused.set("")
            self.opt_1.set("")
            self.opt_2.set("")
            self.opt_3.set("")

    def description_set(self):
        if self.tokenfield.f:
            dbt = td.s.get(UserToken, self.tokenfield.f)
            if not dbt:
                dbt = UserToken(token=self.tokenfield.f)
                td.s.add(dbt)
            dbt.description = self.description.f

    def keypress(self, k):
        if self.tokenfield.f:
            if k == "1":
                self.assign()
            elif k == "2":
                self.unassign()
            elif k == "3":
                self.forget()

    def assign(self):
        dbt = td.s.get(UserToken, self.tokenfield.f)
        users = td.s.query(User)\
                    .filter(User.enabled == True)
        if dbt:
            users = users.filter(User.id != dbt.user_id)
        users = users.all()
        menu = [(user.fullname, self.finish_assign, (user.id,))
                for user in users]
        ui.menu(menu, title="Assign token to user", blurb="Choose the user "
                "to assign this token to")

    def unassign(self):
        dbt = td.s.get(UserToken, self.tokenfield.f)
        if dbt:
            dbt.user = None
        self.tokenfield_set()

    def forget(self):
        dbt = td.s.get(UserToken, self.tokenfield.f)
        if dbt:
            td.s.delete(dbt)
        self.tokenfield.set("")

    def finish_assign(self, userid):
        dbt = td.s.get(UserToken, self.tokenfield.f)
        if not dbt:
            dbt = UserToken(token=self.tokenfield.f,
                            description=self.description.f)
        user = td.s.get(User, userid)
        dbt.user = user
        dbt.last_successful_login = None
        td.s.add(dbt)
        self.tokenfield_set()


class adduser_cmd(cmdline.command):
    """Add a user.

    This user will be a superuser.  This is necessary during setup.
    """
    command = "adduser"
    help = "add a superuser to the database"

    @staticmethod
    def add_arguments(parser):
        parser.add_argument("--webuser", help="Web username for new user")
        parser.add_argument("fullname", help="Full name of user")
        parser.add_argument("shortname", help="Short name of user")
        parser.add_argument("usertoken", help="User ID token")

    @staticmethod
    def run(args):
        with td.orm_session():
            u = User(fullname=args.fullname, shortname=args.shortname,
                     enabled=True, superuser=True)
            if args.webuser:
                u.webuser = args.webuser
            td.s.add(u)
            try:
                td.s.flush()
            except IntegrityError:
                print(f"A user with web username '{u.webuser}' "
                      "already exists.")
                td.s.rollback()
                return 1
            t = UserToken(
                token=args.usertoken, user=u, description=args.fullname)
            td.s.add(t)
            try:
                td.s.flush()
            except IntegrityError:
                print(f"User token {args.usertoken} already exists.")
                td.s.rollback()
                return 1
            print("User added.")


class listusers(cmdline.command):
    """List all active users.
    """
    help = "list active users"

    @staticmethod
    def add_arguments(parser):
        parser.add_argument(
            "-i", "--include-inactive", action="store_true",
            dest="inactive", help="include inactive users")

    @staticmethod
    def run(args):
        with td.orm_session():
            users = td.s.query(User)\
                        .order_by(User.id)
            if not args.inactive:
                users = users.filter_by(enabled=True)
            for u in users.all():
                print(f"{u.id:>4}: {u.fullname} ({u.shortname})")


class show_usertoken(cmdline.command):
    """Display user token
    """
    description = """
    Listen for user tokens; output the first received token and then
    exit. Will fail to start if the till is already running and
    listening for user tokens.

    Useful during initial till setup to find out the user token to use
    with the 'adduser' command for the first till user.
    """
    database_required = False
    command = "show-usertoken"
    help = "output first received user token"

    @staticmethod
    def add_arguments(parser):
        parser.add_argument(
            "-p", "--port", type=int, default=8455, help="port to listen on")

    @staticmethod
    def run(args):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind(('127.0.0.1', args.port))
        except OSError:
            print(f"Unable to bind to port {args.port}; is the till already "
                  "running?")
            return 1
        try:
            print(s.recv(1024).strip().decode("utf-8"))
        except KeyboardInterrupt:
            pass
        finally:
            s.close()


# These permissions aren't used directly in the till but may be used
# in other components like the web interface
action_descriptions['edit-config'] = "Modify the till configuration"
action_descriptions['edit-department'] = "Create or alter departments"
action_descriptions['edit-group'] = "Modify permission groups"


class default_groups:
    """Three basic group definitions.

    Pub configuration files can use these as they are, or add or
    remove individual items.
    """
    basic_user = set([
        "sell-stock",
        "sell-stocktype",
        "sell-plu",
        "sell-dept",
        "take-payment",
        "cancel-line-in-open-transaction",
        "print-receipt",
        "recall-trans",
        "record-waste",
        "current-session-summary",
        "version",
        "netinfo",
        "kitchen-message",
        "kitchen-order",
        "edit-transaction-note",
        "price-check",
        "edit-current-user-password",
    ])

    skilled_user = set([
        "drink-in",
        "nosale",
        "merge-trans",
        "split-trans",
        "void-from-closed-transaction",
        "stock-check",
        "stock-level-check",
        "use-stock",
        "restock",
        "return-stock",
        "auto-allocate",
        "manage-stockline-associations",
        "annotate",
        "stockline-note",
        "cancel-cash-payment",
    ])

    manager = set([
        "print-receipt-by-number",
        "restore-deferred",
        "exit",
        "deliveries",
        "edit-supplier",
        "start-session",
        "end-session",
        "record-takings",
        "session-summary",
        "list-users",
        "edit-user",
        "edit-user-password",
        "edit-group",
        "manage-tokens",
        "override-price",
        "reprice-stock",
        "defer-trans",
        "edit-keycaps",
        "move-keys",
        "finish-unconnected-stock",
        "stock-history",
        "purge-finished-stock",
        "alter-stocktype",
        "add-custom-transline",
        "reprint-stocklabel",
        "add-best-before",
        "create-stockline",
        "alter-stockline",
        "list-unbound-stocklines",
        "create-plu",
        "alter-plu",
        "list-unbound-plus",
        "alter-modifier",
        "edit-barcode",
        "return-finished-item",
        "recall-any-trans",
        "apply-discount",
        "print-price-list",
        "edit-unit",
        "edit-stockunit",
        "stocktake",
        "manage-payment-methods",
    ])

    installer = set([
        "edit-payment-methods",
    ])

    groups = [
        ('basic-user', "Default for all users", basic_user),
        ('skilled-user', "Functions for more skilled users", skilled_user),
        ('manager', "Management functions", manager),
        ('installer', "Initial configuration options", installer),
    ]

# I'm not doing anything with this list yet, but here are permissions
# that have been retired:

# update-supplier - redundant, edit-supplier is used instead
# print-stocklist - reprint-stocklabel is used instead
# twitter - feature removed
