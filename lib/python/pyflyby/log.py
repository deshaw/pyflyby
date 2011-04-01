
from __future__ import absolute_import, division, with_statement

import logging
import os
import sys

def _create_logger():
    logger = logging.Logger('pyflyby')
    formatter = logging.Formatter(
        '{0}: %(message)s'.format(os.path.basename(sys.argv[0])))
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

logger = _create_logger()
