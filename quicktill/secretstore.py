from cryptography.fernet import Fernet, InvalidToken
import getpass
from .models import Secret
from . import td
from . import cmdline

class SecretException(Exception):
    pass

class SecretDoesNotExist(SecretException):
    """The requested secret does not exist in the database
    """
    pass

class SecretNotAvailable(SecretException):
    """The requested secret exists, but is not usable

    It may not be readable with the configured key, or may be older
    than the provided maximum age.
    """
    pass

class Secrets:
    """A group of secrets stored in the database

    Secret values are strings; they are utf-8 encoded before being
    passed to Fernet
    """
    _key_names = {}

    def __init__(self, key_name, key):
        self._key_name = key_name
        try:
            self._fernet = Fernet(key)
        except:
            self._fernet = None
        self._key_names[key_name] = self

    @classmethod
    def find(cls, secret_name):
        return cls._key_names.get(secret_name)

    def fetch(self, secret_name, max_age=None, lock_for_update=False):
        if lock_for_update:
            s = td.s.query(Secret).filter(Secret.key_name == self._key_name)\
                                  .filter(Secret.secret_name == secret_name)\
                                  .with_for_update()\
                                  .one_or_none()
        else:
            s = td.s.query(Secret).get((self._key_name, secret_name))
        if not s:
            raise SecretDoesNotExist
        if not self._fernet:
            raise SecretNotAvailable
        try:
            return self._fernet.decrypt(s.token, ttl=max_age).decode('utf-8')
        except InvalidToken:
            raise SecretNotAvailable

    def store(self, secret_name, value, create=False):
        if not isinstance(value, str):
            raise TypeError("Secret value must be a str()")
        if not self._fernet:
            raise SecretNotAvailable
        s = td.s.query(Secret).get((self._key_name, secret_name))
        if not s:
            if not create:
                raise SecretDoesNotExist
            s = Secret(key_name=self._key_name, secret_name=secret_name)
            td.s.add(s)
        s.token = self._fernet.encrypt(value.encode('utf-8'))

class genkey(cmdline.command):
    database_required = False
    command = "generate-secret-key"
    help = "output a fresh secret key suitable for use with Secrets " \
        "in the till configuration file"

    @staticmethod
    def run(args):
        print(Fernet.generate_key())

class passwd(cmdline.command):
    help = "store or update a password in the database"

    @staticmethod
    def add_arguments(parser):
        parser.add_argument(
            "-p", "--password", help="password to store; if not specified, "
            "will be read from stdin")
        parser.add_argument(
            "key_name", metavar="KEY-NAME",
            help="name of the key to use to encrypt the password")
        parser.add_argument(
            "secret_name", metavar="SECRET-NAME",
            help="name to store the password under")

    @staticmethod
    def run(args):
        keystore = Secrets.find(args.key_name)
        if not keystore:
            print(f"No key configured for {args.key_name}: check the till "
                  "configuration file")
            return 1
        password = args.password or getpass.getpass("New password: ")
        if not args.password:
            pwcheck = getpass.getpass("New password again: ")
            if password != pwcheck:
                print(f"Passwords didn't match.")
                return 1
        with td.orm_session():
            keystore.store(args.secret_name, password, create=True)
