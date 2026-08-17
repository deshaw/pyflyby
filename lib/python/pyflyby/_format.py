# pyflyby/_format.py.
# Copyright (C) 2011, 2012, 2013, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import annotations, print_function

import dataclasses
from   dataclasses              import dataclass, fields
import sys
from   typing                   import Any, Optional, Sequence, Tuple, Union

if sys.version_info < (3, 12):
    from typing_extensions          import Self
else:
    from typing import Self


@dataclass(frozen=True)
class FormatParams:
    max_line_length: Union[int, float, None] = None
    max_line_length_default: int = 79
    wrap_paren: bool = True
    indent: int = 4
    hanging_indent: str = 'never'
    use_black: bool = False

    @classmethod
    def coerce(cls, arg: Optional[FormatParams] = None) -> Self:
        """
        Return ``arg`` as an instance of ``cls``.

          >>> FormatParams.coerce(None)
          <FormatParams {}>

        ``arg`` may be ``None``, or any `FormatParams`; parameters that
        ``cls`` does not have are dropped.
        """
        if arg is None:
            return cls()
        if not isinstance(arg, FormatParams):
            raise TypeError("expected None or a FormatParams, got %s"
                            % (type(arg).__name__,))
        names = {f.name for f in fields(cls)}
        return cls(**{f.name: getattr(arg, f.name) for f in fields(arg)
                      if f.name in names})

    def replace(self, **kwargs: Any) -> Self:
        """
        Return a copy of ``self`` with the given parameters overridden.

          >>> FormatParams(max_line_length=20).replace(wrap_paren=False)
          <FormatParams {'max_line_length': 20, 'wrap_paren': False}>

        The result has the same class as ``self``, so subclass-only parameters
        are preserved.
        """
        return dataclasses.replace(self, **kwargs)

    def __repr__(self) -> str:
        """
        Show only non-default parameters; the generated dataclass repr
        would spell out every one of them.
        """
        nondefault = {f.name: getattr(self, f.name) for f in fields(self)
                      if getattr(self, f.name) != f.default}
        return f'<{self.__class__.__name__} {nondefault}>'


def fill(
    tokens: Sequence[str],
    sep: Union[str, Tuple[str, str]] = (", ", ""),
    prefix: Union[str, Tuple[str, str]] = "",
    suffix: Union[str, Tuple[str, str]] = "",
    newline: str = "\n",
    max_line_length: Union[int, float] = 80,
) -> str:
    r"""
    Given a sequences of strings, fill them into a single string with up to
    ``max_line_length`` characters each.

      >>> fill(["'hello world'", "'hello two'"],
      ...            prefix=("print ", "      "), suffix=(" \\", ""),
      ...            max_line_length=25)
      "print 'hello world', \\\n      'hello two'\n"

    :param tokens:
      Sequence of strings to fill.  There must be at least one token.
    :param sep:
      Separator string to append to each token.  If a 2-element tuple, then
      indicates the separator between tokens and the separator after the last
      token.  Trailing whitespace is removed from each line before appending
      the suffix, but not from between tokens on the same line.
    :param prefix:
      String to prepend at the beginning of each line.  If a 2-element tuple,
      then indicates the prefix for the first line and prefix for subsequent
      lines.
    :param suffix:
      String to append to the end of each line.  If a 2-element tuple, then
      indicates the suffix for all lines except the last, and the suffix for
      the last line.
    :return:
      Filled string.
    """
    N = max_line_length
    assert len(tokens) > 0
    if isinstance(prefix, tuple):
        first_prefix, cont_prefix = prefix
    else:
        first_prefix = cont_prefix = prefix
    if isinstance(suffix, tuple):
        nonterm_suffix, term_suffix = suffix
    else:
        nonterm_suffix = term_suffix = suffix
    if isinstance(sep, tuple):
        nonterm_sep, term_sep = sep
    else:
        nonterm_sep = term_sep = sep
    lines = [first_prefix + tokens[0]]
    for token, is_last in zip(tokens[1:], [False]*(len(tokens)-2) + [True]):
        suffix = term_suffix if is_last else nonterm_suffix
        sep = (term_sep if is_last else nonterm_sep).rstrip()
        # Does the next token fit?
        if len(lines[-1] + nonterm_sep + token + sep + suffix) <= N:
            # Yes; add it.
            lines[-1] += nonterm_sep + token
        else:
            # No; break into new line.
            lines[-1] += nonterm_sep.rstrip() + nonterm_suffix + newline
            lines.append(cont_prefix + token)
    lines[-1] += term_sep.rstrip() + term_suffix + newline
    return ''.join(lines)


def pyfill(prefix: str, tokens: Sequence[str], params: FormatParams = FormatParams()) -> str:
    """
    Fill a Python statement.

      >>> print(pyfill('print ', ["foo.bar", "baz", "quux", "quuuuux"]), end='')
      print foo.bar, baz, quux, quuuuux
      >>> print(pyfill('print ', ["foo.bar", "baz", "quux", "quuuuux"],
      ...        FormatParams(max_line_length=15, hanging_indent='auto')), end='')
      print (foo.bar,
             baz,
             quux,
             quuuuux)
      >>> print(pyfill('print ', ["foo.bar", "baz", "quux", "quuuuux"],
      ...        FormatParams(max_line_length=14, hanging_indent='auto')), end='')
      print (
          foo.bar,
          baz, quux,
          quuuuux)

    :param prefix:
      Prefix for first line.
    :param tokens:
      Sequence of string tokens
    :type params:
      `FormatParams`
    :rtype:
      ``str``
    """
    max_line_length: Union[int, float]
    if params.max_line_length is None:
        max_line_length = params.max_line_length_default
    else:
        max_line_length = params.max_line_length

    if params.wrap_paren:
        # Check how we will break up the tokens.
        len_full = sum(len(tok) for tok in tokens) + 2 * (len(tokens)-1)
        if len(prefix) + len_full <= max_line_length:
            # The entire thing fits on one line; no parens needed.  We check
            # this first because breaking into lines adds paren overhead.
            #
            # Output looks like:
            #   from foo import abc, defgh, ijkl, mnopq, rst
            return prefix + ", ".join(tokens) + "\n"
        if params.hanging_indent == "never":
            hanging_indent = False
        elif params.hanging_indent == "always":
            hanging_indent = True
        elif params.hanging_indent == "auto":
            # Decide automatically whether to do hanging-indent mode.  If any
            # line would exceed the max_line_length, then do hanging indent;
            # else don't.
            #
            # In order to use non-hanging-indent mode, the first line would
            # have an overhead of 2 because of "(" and ",".  We check the
            # longest token since even if the first token fits, we still want
            # to avoid later tokens running over N.
            maxtoklen = max(len(token) for token in tokens)
            hanging_indent = (len(prefix) + maxtoklen + 2 > max_line_length)
        else:
            raise ValueError("bad params.hanging_indent=%r"
                             % (params.hanging_indent,))
        if hanging_indent:
            # Hanging indent mode.  We need a single opening paren and
            # continue all imports on separate lines.
            #
            # Output looks like:
            #   from foo import (
            #       abc, defgh, ijkl,
            #       mnopq, rst)
            return (prefix + "(\n"
                    + fill(tokens, max_line_length=max_line_length,
                           prefix=(" " * params.indent), suffix=("", ")")))
        else:
            # Non-hanging-indent mode.
            #
            # Output looks like:
            #   from foo import (abc, defgh,
            #                    ijkl, mnopq,
            #                    rst)
            pprefix = prefix + "("
            return fill(tokens, max_line_length=max_line_length,
                        prefix=(pprefix, " " * len(pprefix)), suffix=("", ")"))
    else:
        raise NotImplementedError
