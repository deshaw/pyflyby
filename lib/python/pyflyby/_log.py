# pyflyby/_log.py.
# Copyright (C) 2011, 2012, 2013, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import absolute_import, division, with_statement

import logging
import os
import sys


LEVELS = dict( (k, getattr(logging, k.upper()))
               for k in ['debug', 'info', 'warning', 'error'] )

class PFBLogger(logging.Logger):
    def __init__(self, name, level):
        logging.Logger.__init__(self, name)
        formatter = logging.Formatter(
            '{0}: %(message)s'.format(os.path.basename(sys.argv[0])))
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        self.addHandler(handler)
        self.set_level(level)

    def set_level(self, level):
        """
        Set the pyflyby logger's level to C{level}.

        @type level:
          C{str}
        """
        if isinstance(level, int):
            level_num = level
        else:
            level_num = LEVELS.get(level.lower())
        logging.Logger.setLevel(self, level_num)


logger = PFBLogger('pyflyby', 'info')
