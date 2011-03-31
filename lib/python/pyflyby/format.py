
from __future__ import absolute_import, division, with_statement

class FormatParams(object):
    max_line_length = 80
    wrap_paren = True
    indent = 4

    def __init__(self, **kwargs):
        for key, value in kwargs.iteritems():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                raise ValueError("bad kwarg %r" % (key,))


def fill(tokens, sep=(", ", ""), prefix="", suffix="", newline="\n",
         max_line_length=80):
    """
    Given a sequences of strings, fill them into a single string with up to
    C{max_line_length} characters each.

      >>> fill(["'hello world'", "'hello two'"],
      ...            prefix=("print ", "      "), suffix=(" \\\\", ""),
      ...            max_line_length=25)
      "print 'hello world', \\\\\\n      'hello two'\\n"

    @param tokens:
      Sequence of strings to fill.  There must be at least one token.
    @param sep:
      Separator string to append to each token.  If a 2-element tuple, then
      indicates the separator between tokens and the separator after the last
      token.  Trailing whitespace is removed from each line before appending
      the suffix, but not from between tokens on the same line.
    @param prefix:
      String to prepend at the beginning of each line.  If a 2-element tuple,
      then indicates the prefix for the first line and prefix for subsequent
      lines.
    @param suffix:
      String to append to the end of each line.  If a 2-element tuple, then
      indicates the suffix for all lines except the last, and the suffix for
      the last line.
    @return:
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


def pyfill(prefix, tokens, params=FormatParams()):
    """
    Fill a Python statement.

      >>> print pyfill('print ', ["foo.bar", "baz", "quux", "quuuuux"]),
      print foo.bar, baz, quux, quuuuux

      >>> print pyfill('print ', ["foo.bar", "baz", "quux", "quuuuux"],
      ...        FormatParams(max_line_length=15)),
      print (foo.bar,
             baz,
             quux,
             quuuuux)

      >>> print pyfill('print ', ["foo.bar", "baz", "quux", "quuuuux"],
      ...        FormatParams(max_line_length=14)),
      print (
          foo.bar,
          baz, quux,
          quuuuux)

    @param prefix:
      Prefix for first line.
    @param tokens:
      Sequence of string tokens
    @type params:
      L{FormatParams}
    @rtype:
      C{str}
    """
    N = params.max_line_length
    if params.wrap_paren:
        # Check how we will break up the tokens.
        len_full = sum(len(tok) for tok in tokens) + 2 * (len(tokens)-1)
        if len(prefix) + len_full <= N:
            # The entire thing fits on one line; no parens needed.  We check
            # this first because breaking into lines adds paren overhead.
            #
            # Output looks like:
            #   from foo import abc, defgh, ijkl, mnopq, rst
            return prefix + ", ".join(tokens) + "\n"
        if len(prefix) + max(len(token) for token in tokens) + 2 <= N:
            # Some tokens fit on the first line; wrap the rest.  The first
            # line has an overhead of 2 because of "(" and ",".  We check the
            # longest token since even if the first token fits, we still want
            # to avoid later tokens running over N.
            #
            # Output looks like:
            #   from foo import (abc, defgh,
            #                    ijkl, mnopq,
            #                    rst)
            pprefix = prefix + "("
            return fill(tokens, max_line_length=N,
                        prefix=(pprefix, " " * len(pprefix)), suffix=("", ")"))
        else:
            # Some token doesn't fit on a prefixed line.  We need a single
            # opening paren and continue all imports on separate lines.
            #
            # Output looks like:
            #   from foo import (
            #       abc, defgh, ijkl,
            #       mnopq, rst)
            return (prefix + "(\n"
                    + fill(tokens, max_line_length=N,
                           prefix=(" " * params.indent), suffix=("", ")")))
    else:
        raise NotImplementedError
