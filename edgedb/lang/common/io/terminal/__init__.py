##
# Copyright (c) 2008-2010 MagicStack Inc.
# All rights reserved.
#
# See LICENSE for details.
##

import os
import sys
import builtins

from edgedb.lang.common.exceptions import EdgeDBError
from edgedb.lang.common.io.terminal.color import (
    colorize, colorstr, dummycolorstr)
from edgedb.lang.common.datastructures import xvalue


def isatty(file):
    return os.isatty(file.fileno())


class TerminalError(EdgeDBError):
    pass


class Terminal:
    def __init__(self, fd=None, *, colors=None):
        if fd is not None and not isinstance(fd, int):
            self.fd = fd
            self.fileno = fd.fileno()

        else:
            self.fd = None
            self.fileno = fd or sys.stdout.fileno()

        self.colors = self.supports_colors() if colors is None else colors

        if self.colors:
            self.colorstr = colorstr
        else:
            self.colorstr = dummycolorstr

    def has_colors(self):
        return self.colors

    def supports_colors(self):
        return self.isatty() and os.getenv('TERM', None) != 'dumb'

    def isatty(self):
        return os.isatty(self.fileno)

    @property
    def size(self):
        try:
            import fcntl
            import termios
            import struct
            size = struct.unpack(
                '2h', fcntl.ioctl(self.fileno, termios.TIOCGWINSZ, '    '))
        except Exception:
            size = (os.getenv('LINES', 25), os.getenv('COLUMNS', 80))

        return size

    def colorize(self, string='', fg=None, bg=None, opts=()):
        if self.has_colors():
            return colorize(string, fg, bg, opts)
        else:
            return string

    def print(self, *args, indent=0, **kwargs):
        new_args = []
        for arg in args:
            if isinstance(arg, xvalue):
                new_args.append(self.colorize(arg.value, **arg.attrs))
            else:
                new_args.append(arg)

        if indent:
            lines = ' '.join(new_args).split('\n')
            indent = ' ' * indent
            indented = '\n'.join(indent + line for line in lines)
            new_args = (indented, )

        if self.fd:
            builtins.print(*new_args, file=self.fd, **kwargs)
        else:
            builtins.print(*new_args, **kwargs)
