#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import division

import server
import logging
import argparse

def main():
    parser = argparse.ArgumentParser(description='Parcell')
    parser.add_argument('--reuse-pw', action='store_true', dest='reuse_pw', help="only ask for one password")
    parser.add_argument('--quota', default=4096, help="set cache quota")
    parser.add_argument('--ram-quota', default=1024, help="set RAM cache quota")
    parser.add_argument('-a', type=str, default="localhost", help="specifies the server address")
    parser.add_argument('-p', type=int, default=8000, help="specifies the server port")
    parser.add_argument('-v', '--verbose', action='count', default=1, dest='verbosity', help="augments verbosity level")
    args = parser.parse_args()

    levels = [ logging.CRITICAL, logging.WARNING, logging.INFO, logging.DEBUG ]
    logging.basicConfig(level=levels[min(args.verbosity, 3)])

    server.enable_restart()
    server.start_server(args.a, args.p, args.quota, args.ram_quota, args.reuse_pw)
