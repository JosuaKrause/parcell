#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import division

import os
import sys

try:
    from parcell.main import main
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from parcell.main import main

if __name__ == '__main__':
    main()
