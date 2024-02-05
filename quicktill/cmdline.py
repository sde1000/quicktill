"""Command line argument parsing infrastructure.
"""


class command:
    database_required = True
    _commands = []

    def __init_subclass__(cls):
        super().__init_subclass__()
        cls._commands.append(cls)

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
