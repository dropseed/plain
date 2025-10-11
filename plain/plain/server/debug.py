#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.

"""The debug module contains utilities and functions for better
debugging Gunicorn."""

import inspect
import linecache
import re
import sys

__all__ = ['spew', 'unspew']

_token_spliter = re.compile(r'\W+')


class Spew:

    def __init__(self, trace_names=None, show_values=True):
        self.trace_names = trace_names
        self.show_values = show_values

    def __call__(self, frame, event, arg):
        if event == 'line':
            lineno = frame.f_lineno
            if '__file__' in frame.f_globals:
                filename = frame.f_globals['__file__']
                if (filename.endswith('.pyc') or
                        filename.endswith('.pyo')):
                    filename = filename[:-1]
                name = frame.f_globals['__name__']
                line = linecache.getline(filename, lineno)
            else:
                name = '[unknown]'
                try:
                    src = inspect.getsourcelines(frame)
                    line = src[lineno]
                except OSError:
                    line = 'Unknown code named [%s].  VM instruction #%d' % (
                        frame.f_code.co_name, frame.f_lasti)
            if self.trace_names is None or name in self.trace_names:
                print(f'{name}:{lineno}: {line.rstrip()}')
                if not self.show_values:
                    return self
                details = []
                tokens = _token_spliter.split(line)
                for tok in tokens:
                    if tok in frame.f_globals:
                        details.append(f'{tok}={frame.f_globals[tok]!r}')
                    if tok in frame.f_locals:
                        details.append(f'{tok}={frame.f_locals[tok]!r}')
                if details:
                    print("\t{}".format(' '.join(details)))
        return self


def spew(trace_names=None, show_values=False):
    """Install a trace hook which writes incredibly detailed logs
    about what code is being executed to stdout.
    """
    sys.settrace(Spew(trace_names, show_values))


def unspew():
    """Remove the trace hook installed by spew.
    """
    sys.settrace(None)
