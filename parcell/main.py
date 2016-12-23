#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import division

import os
import sys
import atexit
import logging
import argparse

from . import __version__
import server
import loading

CLAIM_FILE = ".LOCK"
def claim():
    if server.is_child():
        return
    if os.path.exists(CLAIM_FILE):
        print("FATAL! Only one instance of parcell allowed at a time.", file=sys.stderr)
        print("If actually no other instance is running remove the {0} file".format(CLAIM_FILE), file=sys.stderr)
        sys.exit(1)
    with open(CLAIM_FILE, 'wb') as f:
        print("", file=f)
    atexit.register(lambda: os.remove(CLAIM_FILE))

def _start(args):
    server.enable_restart()
    server.start_server(args.a, args.p, args.quota, args.ram_quota, args.reuse_pw)

def _list(args):
    for p in loading.get_projects():
        print(p, file=sys.stdout)

def _add(args):
    loading.set_password_reuse(args.reuse_pw)
    loading.set_msg(loading.simple_msg)
    if not loading.add_project(args.name):
        sys.exit(2)

def main():
    # root parser
    parser = argparse.ArgumentParser(description='parcell')
    parser.add_argument('-v', '--verbose', action='count', default=1, dest='verbosity', help="augments verbosity level")
    parser.add_argument('--version', action='version', version="parcell version {0}".format(__version__))
    subparsers = parser.add_subparsers(title="commands", metavar='')

    # add action
    parser_add = subparsers.add_parser('add', help="adds a new project")
    parser_add.add_argument('--reuse-pw', action='store_true', dest='reuse_pw', help="only ask for one password")
    parser_add.add_argument('name', help="the name of the new project")
    parser_add.set_defaults(func=_add)

    # list action
    parser_list = subparsers.add_parser('list', help="lists all projects")
    parser_list.set_defaults(func=_list)

    # start action
    parser_start = subparsers.add_parser('start', help="starts the parcell web interface")
    parser_start.add_argument('--reuse-pw', action='store_true', dest='reuse_pw', help="only ask for one password")
    parser_start.add_argument('--quota', default=4096, help="set cache quota")
    parser_start.add_argument('--ram-quota', default=1024, help="set RAM cache quota")
    parser_start.add_argument('-a', type=str, default="localhost", help="specifies the server address")
    parser_start.add_argument('-p', type=int, default=8000, help="specifies the server port")
    parser_start.set_defaults(func=_start)

    # parse arguments
    args = parser.parse_args()

    levels = [ logging.CRITICAL, logging.WARNING, logging.INFO, logging.DEBUG ]
    level = levels[min(args.verbosity, 3)]
    logging.basicConfig(level=level)

    claim()

    try:
        args.func(args)
    except KeyboardInterrupt:
        if level == logging.DEBUG:
            raise
        print("", file=sys.stdout)
        sys.exit(1)
    sys.exit(0)

if __name__ == '__main__':
    main()
