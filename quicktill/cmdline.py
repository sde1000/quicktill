"""Command line argument parsing infrastructure.
"""

import argparse

class CommandTracker(type):
    """
    Metaclass keeping track of all the types of command we understand.

    """
    def __init__(cls,name,bases,attrs):
        if not hasattr(cls,'_commands'):
            cls._commands=[]
        else:
            cls._commands.append(cls)

class command(object, metaclass=CommandTracker):
    database_required = True

    @classmethod
    def add_subparsers(cls, parser):
        subparsers = parser.add_subparsers(title="commands")
        for c in cls._commands:
            parser = subparsers.add_parser(
                c.command if hasattr(c, "command") else c.__name__,
                help=c.help if hasattr(c, "help") else None,
                description=c.description if hasattr(c, "description")
                else c.__doc__)
            parser.set_defaults(command=c)
            c.add_arguments(parser)

    @staticmethod
    def add_arguments(parser):
        pass

    @staticmethod
    def run(args):
        pass
