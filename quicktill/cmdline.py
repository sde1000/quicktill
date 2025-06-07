"""Command line argument parsing infrastructure.
"""

import sys


class command:
    database_required = True
    _commands = []

    def __init_subclass__(cls):
        super().__init_subclass__()
        cls._commands.append(cls)

    @classmethod
    def add_subparsers(cls, parser, configfile, defaults):
        subparsers = parser.add_subparsers(title="commands")
        for c in cls._commands:
            command_name = c.command if hasattr(c, "command") else c.__name__
            parser = subparsers.add_parser(
                command_name,
                help=c.help if hasattr(c, "help") else None,
                description=c.description if hasattr(c, "description")
                else c.__doc__)
            c.add_arguments(parser)
            subparser_defaults = defaults.get(command_name, {})
            if not isinstance(subparser_defaults, dict):
                print(f"{configfile}: {command_name} defaults must be a table",
                      file=sys.stderr)
                sys.exit(1)
            if "command" in subparser_defaults:
                print(f"{configfile}: {command_name} defaults may not include "
                      f"the 'command' key", file=sys.stderr)
                sys.exit(1)
            parser.set_defaults(command=c, **subparser_defaults)

    @staticmethod
    def add_arguments(parser):
        pass

    @staticmethod
    def run(args):
        pass
