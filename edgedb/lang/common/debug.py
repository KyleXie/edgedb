##
# Copyright (c) 2008-2010, 2012 MagicStack Inc.
# All rights reserved.
#
# See LICENSE for details.
##

"""A collection of useful debugging routines."""

import logging
import inspect
import re
import os
import ast
import contextlib
import cProfile
import time

from edgedb.lang.common.functional import decorate
from edgedb.lang.common.exceptions import MultiError
from edgedb.lang.common.datastructures import Void


def _init_debug_channels():
    channels = set()

    for k, v in os.environ.items():
        if k.startswith('EDGEDB_DEBUG_') and v:
            channel = k[len('EDGEDB_DEBUG_'):].lower().replace('_', '.')
            channels.add(channel)

    return channels


channels = _init_debug_channels()


class DebugDecoratorParseError(Exception):
    pass


def _indent_code(source, absolute=None, relative=None):
    def _calc_tab_size(str):
        count = 0
        for i in str:
            if i == ' ':
                count += 1
            else:
                break
        return count

    tab_sizes = tuple(
        (_calc_tab_size(line) for line in source.split('\n') if line.strip()))
    if tab_sizes:
        tab_size = min(tab_sizes)
    else:
        tab_size = 0

    if relative is not None:
        absolute = tab_size + relative

    if absolute < 0:
        absolute = 0

    if absolute is not None:
        source = '\n'.join([(' ' * absolute) + line[tab_size:]
                           for line in source.split('\n')])

    return source


def _set_location(node, lineno):
    if 'lineno' in node._attributes:
        node.lineno = lineno

    for c in ast.iter_child_nodes(node):
        _set_location(c, lineno)
    return node


def _dump_header(title):
    return '\n' + '=' * 80 + '\n' + title + '\n' + '=' * 80 + '\n'


class debug:
    enabled = bool(channels)
    active = False

    def __new__(cls, func):
        if cls.active or not cls.enabled:
            return func

        cls.active = True

        source = _indent_code(inspect.getsource(func), absolute=0)
        sourceloc = inspect.getsourcelines(func)[1]
        orig_file = inspect.getsourcefile(func)

        func_start = source.find('\ndef ') + 1
        sourceloc += source[:func_start].count('\n')
        source = source[func_start:]

        tree = ast.parse(source, filename=orig_file)
        ast.increment_lineno(tree, sourceloc - 1)

        class Transformer(ast.NodeTransformer):

            pattern = re.compile(r'''
                (?P<type>LOG|LINE)
                \s+ \[ \s* (?P<tags> [\w\.]+ (?:\s* , \s* [\w+\.]+)* ) \s* \]
                (?P<title>.*)
            ''', re.X)

            def visit_Expr(self, node):
                if isinstance(node.value, ast.Str):
                    if node.value.s.startswith(
                            'LOG') or node.value.s.startswith('LINE'):
                        m = Transformer.pattern.match(node.value.s)
                        if m:
                            type = m.group('type').strip()
                            title = m.group('title').strip()
                            tags = {
                                t.strip()
                                for t in m.group('tags').split(',')
                            }

                            comment = node.value.s.split('\n')

                            # Str().lineno is for the _last_ line of the
                            # string. We want to use the first.
                            lineno = node.lineno - len(comment) + 1

                            text = (
                                'import edgedb.lang.common.debug, '
                                'os as _os_\n'
                                'if edgedb.lang.common.debug.channels & %r:\n'
                                '    pass\n'
                            ) % tags

                            if title:
                                if type == 'LOG':
                                    text += (
                                        '    print(edgedb.lang.common.debug'
                                        '._dump_header(%r))\n'
                                    ) % title
                                else:
                                    text += (
                                        '    print(_os_.getpid(), %r, %s)'
                                    ) % (title, ', '.join(comment[1:]))

                            code = ast.parse(text.rstrip(), filename=orig_file)
                            code = ast.fix_missing_locations(code)
                            _set_location(code, lineno)

                            if type == 'LOG' and len(comment) > 1:
                                ctext = _indent_code(
                                    '\n'.join(comment[1:]), absolute=0)
                                ccode = ast.parse(ctext, filename=orig_file)

                                ast.increment_lineno(ccode, lineno)

                                # Prepend the custom code to the If block body
                                code.body[1].body.extend(ccode.body)

                            return code.body
                        else:
                            raise DebugDecoratorParseError(
                                'invalid debug decorator syntax')
                return node

        tree = Transformer().visit(tree)
        code = compile(tree, orig_file if orig_file else '<string>', 'exec')

        _locals = {}
        exec(code, func.__globals__, _locals)

        new_func = _locals[func.__name__]
        cls.active = False

        decorate(new_func, func)

        return new_func


def debug_channels(*channels):
    class DebugContext:
        def __init__(self, *channels):
            self.channels = set(channels)

        def __enter__(self):
            global channels
            self.change = self.channels - channels
            channels.update(self.change)

        def __exit__(self, exc_type, exc_value, tb):
            global channels
            channels -= self.change

    return DebugContext(*channels)


def highlight(code, lang=None):
    try:
        from pygments import highlight as h
        from pygments.lexers import get_lexer_by_name
        from pygments.formatters import TerminalFormatter
    except ImportError:
        return code

    return h(
        code, get_lexer_by_name(lang), TerminalFormatter(
            bg='dark', style='native'))


class ErrorExpected(Exception):
    pass


@contextlib.contextmanager
def profiler(filename=None, sort='time'):
    """Profile a block of code.

    Provides an easier setup than the standard ``cProfile.run('command()')``.

    :param str filename: Optional argument to specify where to dump profiler
                         output. ``None`` by default, which means that the
                         profiler stats will be dumped in stdout.

    :param str sort: If ``filename`` argument is ``None``, and the results
                     are going to be printed to stdout, this argument
                     specifies the sorting of the call table.  The possible
                     valid values are specified in the stdlib's
                     ``pstats`` module.

    Usage:

    .. code-block:: python

        from edgedb.lang.common.debug import profiler

        with profiler():
            your_code()
    """
    prof = cProfile.Profile()

    prof.enable()
    try:
        yield
    finally:
        prof.disable()

        if filename is None:
            prof.print_stats(sort)
        else:
            prof.dump_stats(filename)


@contextlib.contextmanager
def debug_logger_off():
    """Disable printing log messages to stdout for the wrapped code."""
    logger = logging.getLogger()
    old_handlers = logger.handlers[:]
    logger.handlers[:] = []

    try:
        yield
    finally:
        logger.handlers[:] = old_handlers


class BufferingLogHandler(logging.Handler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffer = []

    def emit(self, record):
        self.buffer.append(record)

    def get_logs(self):
        return list(self.buffer)

    def reset_logs(self):
        self.buffer[:] = []


@contextlib.contextmanager
def custom_logger(handler):
    logger = logging.getLogger()

    try:
        with debug_logger_off():
            logger.addHandler(handler)
            yield
    finally:
        logger.removeHandler(handler)


@contextlib.contextmanager
def assert_logs(message_re, *, logger_re=None):
    """Ensure that the wrapped block of code logs a message.

    The message must match ``message_re``, and the logger
    must match ``logger_re``, if specified.

    .. code-block:: pycon

        >>> with assert_logs('foo'):
        ...     pass
        AssertionError
    """
    msg_re = re.compile(message_re)
    lgr_re = None
    if logger_re is not None:
        lgr_re = re.compile(logger_re)

    logger = logging.getLogger()
    handler = BufferingLogHandler(level=logging.DEBUG)

    try:
        logger_level = logger.level
        logger.setLevel(logging.DEBUG)

        with debug_logger_off():
            logger.addHandler(handler)
            yield
    finally:
        logger.removeHandler(handler)
        logger.setLevel(logger_level)

        for record in handler.buffer:
            if msg_re.search(record.msg):

                if lgr_re is None:
                    break
                else:
                    if lgr_re.search(record.name):
                        break
        else:
            if lgr_re is None:
                raise AssertionError(
                    'no expected message matching {!r} was logged'.format(
                        message_re))
            else:
                raise AssertionError(
                    'no expected message matching {!r} on logger '
                    '{!r} was logged'.format(message_re, logger_re))


class _ExceptionContainer:
    __slots__ = ('exception', )


@contextlib.contextmanager
def assert_raises(
        exception_cls, *, cause=Void, context=Void, error_re=None, attrs=None):
    cnt = _ExceptionContainer()

    try:
        yield cnt

    except MultiError as ex:
        cnt.exception = ex
        for error in ex.errors:
            if isinstance(error, exception_cls):
                return
        raise ErrorExpected(
            'no expected exception {!r} in MultiError'.format(
                exception_cls.__class__.__name__))

    except exception_cls as ex:
        cnt.exception = ex
        if cause is not Void:
            if cause is None:
                assert ex.__cause__ is None
            else:
                assert isinstance(ex.__cause__, cause)

        if context is not Void:
            if context is None:
                assert ex.__context__ is None
            else:
                assert isinstance(ex.__context__, context)

        try:
            msg = ex.args[0]
        except (AttributeError, IndexError):
            msg = str(ex)
        else:
            if not isinstance(msg, str):
                msg = str(ex)

        if error_re is not None:
            err_re = re.compile(str(error_re))

            if not err_re.search(msg):
                if cause not in (Void, None):
                    if not err_re.search(ex.__cause__.args[0]):
                        raise ErrorExpected(
                            '{} with cause {} was expected to be raised '
                            'with cause message that matches '
                            '{!r}, got {!r}'.format(
                                exception_cls.__name__, cause.__name__,
                                error_re, ex.__cause__.args[0])) from ex

                elif context not in (Void, None):
                    if not err_re.search(ex.__context__.args[0]):
                        raise ErrorExpected(
                            '{} with cause {} was expected to be raised '
                            'with context message that matches '
                            '{!r}, got {!r}'.format(
                                exception_cls.__name__, cause.__name__,
                                error_re, ex.__cause__.args[0])) from ex

                else:
                    raise ErrorExpected(
                        '{} was expected to be raised with '
                        'message that matches {!r}, got {!r}'.format(
                            exception_cls.__name__, error_re, msg)) from ex

        if attrs is not None:
            for attr, attr_value in attrs.items():
                try:
                    test = getattr(ex, attr)
                    if attr_value != test:
                        raise ErrorExpected(
                            '{} was expected to have attribute {!r} '
                            'with value {!r}, got {!r}'.format(
                                exception_cls.__name__, attr,
                                attr_value, test))
                except AttributeError:
                    raise ErrorExpected(
                        '{} was expected to have attribute {!r}'.format(
                            exception_cls.__name__, attr))

    except Exception as ex:
        cnt.exception = ex
        raise ErrorExpected('{} was expected to be raised, got {}'.format(
            exception_cls.__name__, ex.__class__.__name__)) from ex

    else:
        raise ErrorExpected(
            '%s was expected to be raised' % exception_cls.__name__)


@contextlib.contextmanager
def assert_shorter_than(timeout):
    """Ensure that the wrapped block of code executes no longer than requested.

    .. code-block:: pycon

        >>> with assert_shorter_than(0.1):
        ...     import time
        ...     time.sleep(0.2)
        AssertionError ...
    """
    timeout = float(timeout)
    start = time.time()
    try:
        yield
    finally:
        total = time.time() - start
        if total > timeout:
            raise AssertionError(
                'block was expected to execute within {:.4} seconds, '
                'but took {:.4}'.format(timeout, total))


@contextlib.contextmanager
def assert_longer_than(timeout):
    """Ensure that the wrapped block of code executes as long as requested.

    .. code-block:: pycon

        >>> with assert_longer_than(0.1):
        ...     import time
        ...     time.sleep(0.01)
        AssertionError ...
    """
    timeout = float(timeout)
    start = time.time()
    try:
        yield
    finally:
        total = time.time() - start
        if total < timeout:
            raise AssertionError(
                'block was expected to execute longer than {:.4} seconds, '
                'but took {:.4}'.format(timeout, total))


def timeit(target):
    """Simplify writing performance benchmarks.

    Usage:

    .. code-block:: python

        from edgedb.lang.common.debug import timeit

    1) in a "with" statement:
        >>> with timeit('long list'):
        ...     result = ''.join(str(i) for i in range(0, 10**5))
        ...
        long list, in 0.101 seconds

    2) as a decorator with some message:
        >>> @timeit('long list generator')
        ... def test(length):
        ...     return ''.join(str(i) for i in range(0, length))
        ...
        >>> list = test(10**5)
        long list generator, in 0.099 seconds

    3) as a simple decorator:
        >>> @timeit
        ... def test(length):
        ...     return ''.join(str(i) for i in range(0, length))
        ...
        >>> list = test(10**5)
        <function test at 0x71f978>, in 0.098 seconds
    """
    class Timer:
        def __init__(self, message):
            self.message = message

        def __enter__(self):
            self.started = time.time()
            return self

        def __exit__(self, exc_type, exc_value, tb):
            print(
                "%s, in %.3f seconds" %
                (self.message, time.time() - self.started))

        def log(self, msg=''):
            print(
                '>>>', self.message, msg, '%.3f' %
                (time.time() - self.started))

        def decorate(self, func):
            def new_func(*args, **kwargs):
                with self:
                    return func(*args, **kwargs)

            return new_func

        def __call__(self, *args):
            if len(args) == 1 and callable(args[0]):
                return self.decorate(args[0])
            else:
                raise Exception("Invalid arguments")

    if target and isinstance(target, str):
        return Timer(target)
    elif target and callable(target):
        return Timer(repr(target)).decorate(target)
    else:
        raise Exception("Invalid arguments")
