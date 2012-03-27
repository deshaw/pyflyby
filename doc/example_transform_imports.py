#!/usr/bin/env python

# Suppose you want to change all "from foo.bar" imports to "from bar"
# imports.  Here is an example of how to do that.

from __future__ import absolute_import, division, with_statement

import re

from   pyflyby.cmdline          import filename_args, parse_args
from   pyflyby.imports2s        import SourceToSourceFileImportsTransformation
from   pyflyby.importstmt       import Import, Imports


def transform_imports(imports):
    results = []
    for imp in imports:
        module_name, member_name, import_as = imp.split
        module_name = re.sub("foo.bar", "bar", module_name)
        results.append(Import.from_split((module_name, member_name, import_as)))
    return Imports(results)


def main():
    options, args = parse_args(
        import_format_params=True, modify_action_params=True)
    @options.action
    def modify(x):
        transformer = SourceToSourceFileImportsTransformation(x)
        for block in transformer.import_blocks:
            block.imports = transform_imports(block.imports)
        return transformer.pretty_print(params=options.params)
    for filename in filename_args(args):
        modify(filename)


if __name__ == '__main__':
    main()
