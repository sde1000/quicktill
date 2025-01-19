"""Monitor till events
"""

from .cmdline import command
from . import listen
from . import td
from . import event
from .models import LogEntry, User, StockType, StockLine, StockItem
from .models import Config, KeyCap
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import undefer


class monitor(command):
    @staticmethod
    def run(args):
        mainloop = event.SelectorsMainLoop()
        listener = listen.db_listener(mainloop, td.engine)

        # Start listening for all the types of notification we understand
        listener.listen_for("log", monitor.notify_log)
        listener.listen_for("user_register", monitor.notify_user_register)
        listener.listen_for("group_membership_changed",
                            monitor.notify_group_membership_changed)
        listener.listen_for("group_grants_changed",
                            monitor.notify_group_grants_changed)
        listener.listen_for("stockline_change", monitor.notify_stockline_change)
        listener.listen_for("stocktype_change", monitor.notify_stocktype_change)
        listener.listen_for("stockitem_change", monitor.notify_stockitem_change)
        listener.listen_for("keycaps", monitor.notify_keycaps)
        listener.listen_for("config", monitor.notify_config)
        listener.listen_for("update", monitor.notify_update)

        while True:
            mainloop.iterate()

    @staticmethod
    def notify_log(id_str):
        try:
            id = int(id_str)
        except Exception:
            return
        with td.orm_session():
            logentry = td.s.get(LogEntry, id)
            if not logentry:
                return
            print(f"log: {logentry.id} {logentry.time} "
                  f"{logentry.loguser.fullname}: {logentry}")

    @staticmethod
    def notify_user_register(id_str):
        try:
            id = int(id_str)
        except Exception:
            return
        with td.orm_session():
            user = td.s.get(User, id, options=[joinedload(User.register)])
            if not user:
                return
            if user.register:
                print(f"user_register: {user.fullname} now at register "
                      f"{user.register_id} ({user.register.terminal_name}) "
                      f"with transaction {user.trans_id}")
            else:
                print(f"user_register: {user.fullname} now not at a register")

    @staticmethod
    def notify_group_membership_changed(blank):
        # This notification doesn't have a payload
        print("group_membership_changed: a group has changed permissions")

    @staticmethod
    def notify_group_grants_changed(blank):
        # This notification doesn't have a payload
        print("group_grants_change: a user's groups have changed")

    @staticmethod
    def notify_stockline_change(id_str):
        try:
            id = int(id_str)
        except Exception:
            return
        with td.orm_session():
            stockline = td.s.get(StockLine, id)
            if not stockline:
                print(f"stockline: id {id} deleted")
                return
            print(f"stockline: {stockline.name} note '{stockline.note}'")

    @staticmethod
    def notify_stocktype_change(id_str):
        try:
            id = int(id_str)
        except Exception:
            return
        with td.orm_session():
            stocktype = td.s.get(
                StockType, id, options=[joinedload(StockType.meta)])
            if not stocktype:
                print(f"stocktype: id {id} deleted")
                return
            print(f"stocktype: {stocktype}, price {stocktype.saleprice}, "
                  f"dept {stocktype.department.description}")
            if stocktype.meta:
                print(f"  metadata: {', '.join(stocktype.meta.keys())}")

    @staticmethod
    def notify_stockitem_change(id_str):
        try:
            id = int(id_str)
        except Exception:
            return
        with td.orm_session():
            stock = td.s.get(StockItem, id, options=[
                undefer(StockItem.remaining),
                joinedload(StockItem.stocktype),
                joinedload(StockItem.stocktype).joinedload(StockType.unit),
            ])
            if not stock:
                print(f"stock: id {id} deleted")
                return
            print(f"stock: {stock.id} {stock.stocktype} "
                  f"{stock.remaining}/{stock.size} {stock.stocktype.unit.name}")
            if stock.finished:
                print(f"  stock finished {stock.finished}")

    @staticmethod
    def notify_keycaps(keycode):
        with td.orm_session():
            keycap = td.s.get(KeyCap, keycode)
            if not keycap:
                return
            print(f"keycap: {keycap.keycode} => '{keycap.keycap}' "
                  f"class '{keycap.css_class}'")

    @staticmethod
    def notify_config(key):
        with td.orm_session():
            config = td.s.get(Config, key)
            if not config:
                return
            print(f"config: {config.key} = {config.value}")

    @staticmethod
    def notify_update(blank):
        print("update: till update notified")
