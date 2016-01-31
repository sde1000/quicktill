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
    @staticmethod
    def add_arguments(parser):
        pass
    @staticmethod
    def run(args):
        pass

