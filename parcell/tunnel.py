#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import division

import sys
import time
import atexit
import getpass
import logging
import pexpect
import argparse
import threading

from tej import parse_ssh_destination
from StringIO import StringIO

_LOGGER = None
def logger():
    global _LOGGER
    if _LOGGER is None:
        _LOGGER = logging.getLogger('tunnel')
    return _LOGGER

def _pretty_dest(dest):
    return ', '.join("{0}={1}".format(k, v if k != "password" else "***") for k, v in dest.items())

_LOCK = threading.RLock()
_TUNNELS = {}
_PROCS = {}
def start_tunnel(s, via, dest, tunnel_port):
    with _LOCK:
        if check_tunnel(s):
            return
        _forward_tunnel(s, int(tunnel_port), via, dest)

def check_tunnel(s):
    with _LOCK:
        if s not in _TUNNELS:
            return False
        if _TUNNELS[s] == -3 or _TUNNELS[s] == -4:
            sys.exit(1)
        return _TUNNELS[s] > 0

def check_permission_denied(s):
    with _LOCK:
        if s not in _TUNNELS:
            return False
        if _TUNNELS[s] == -3 or _TUNNELS[s] == -4:
            sys.exit(1)
        return _TUNNELS[s] == -2

def clean(s):
    with _LOCK:
        if _PROCS is not None and _PROCS[s] is not None:
            try:
                _PROCS[s].terminate()
            except:
                try:
                    _PROCS[s].kill()
                except:
                    pass
            _PROCS[s] = None

def clean_all():
    with _LOCK:
        for s in _PROCS.keys():
            clean(s)

atexit.register(clean_all)

def _forward_tunnel(s, local_port, via, remote):

    def run():
        log = StringIO()
        try:
            _TUNNELS[s] = 1
            cmd = [
                "ssh",
                "-N",
                "-L",
                "{0}:{1}:{2}".format(local_port, remote["hostname"], remote.get("port", 22)),
            ]
            if "port" in via:
                cmd.append("-p")
                cmd.append(str(int(via["port"])))
            username = via.get("username", getpass.getuser())
            hostname = via["hostname"]
            cmd.append("{0}@{1}".format(username, hostname))
            if "password" in via:
                stdin = via["password"] + '\n'
            else:
                stdin = None
            cmd = ' '.join(cmd)
            logger().debug("run %s", cmd)
            proc = pexpect.spawn(cmd, timeout=None)
            proc.logfile_read = log
            _PROCS[s] = proc
            try:
                _TUNNELS[s] = 2
                while True:
                    scenario = proc.expect([ 'RSA key', 'Permission denied', 'password:' ])
                    if scenario == 0:
                        print("The authenticity of host {0} could not be established!".format(hostname))
                        print("Please make sure you can connect to the server by running\n")
                        print("ssh -p {0} {1}@{2} hostname\n".format(via.get("port", 22), username, hostname))
                        print("and then try again.")
                        _TUNNELS[s] = -3
                        return
                    elif scenario == 1:
                        _TUNNELS[s] = -2
                        return
                    elif scenario == 2:
                        if stdin is not None:
                            time.sleep(0.1)
                            proc.sendline(stdin)
                        else:
                            print("It seems connecting to {0}@{1} requires a password".format(username, hostname))
                            print("but it is not specified in the server definition '{0}'.".format(s))
                            print("Please adjust the settings and try again.")
                            _TUNNELS[s] = -4
                            return
            except pexpect.EOF:
                pass
            _PROCS[s] = None
        finally:
            if _TUNNELS[s] == -2 or _TUNNELS[s] == -3 or _TUNNELS[s] == -4:
                return
            log.seek(0)
            logger().info("SSH tunnel terminated!\nLOG:\n%s", log.read())
            if _TUNNELS[s] >= 0:
                _TUNNELS[s] = -1
            clean(s)

    _PROCS[s] = None
    _TUNNELS[s] = 0
    t = threading.Thread(target=run, name="Tunnel-{0}".format(s))
    t.daemon = True
    t.start()
    logger().debug('Waiting for tunnel to open...')
    while _TUNNELS[s] < 2:
        if _TUNNELS[s] < 0:
            if _TUNNELS[s] == -3 or _TUNNELS[s] == -4:
                sys.exit(1)
            if _TUNNELS[s] == -2:
                return
            raise ValueError("Failed to start tunnel!")
    # DISCLAIMER! Tunnel might not be working yet -- check connection repeatedly
    logger().debug('Tunnel open! Proceed!')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parcell Tunnel')
    parser.add_argument('--reuse-pw', action='store_true', dest='reuse_pw', help="only ask for one password")
    parser.add_argument('-v', '--verbose', action='count', default=1, dest='verbosity', help="augments verbosity level")
    parser.add_argument('tunnel', type=str, help="tunnel host")
    parser.add_argument('dest', type=str, help="destination host")
    parser.add_argument('port', type=str, help="local port")
    args = parser.parse_args()

    levels = [ logging.CRITICAL, logging.WARNING, logging.INFO, logging.DEBUG ]
    logging.basicConfig(level=levels[min(args.verbosity, 3)])

    tunnel = parse_ssh_destination(args.tunnel)
    dest = parse_ssh_destination(args.dest)
    port = int(args.port)

    from connector import ask_password, set_password_reuse

    set_password_reuse(args.reuse_pw)
    tunnel["password"] =  ask_password(tunnel["username"], tunnel["hostname"])
    dest["password"] =  ask_password(dest["username"], dest["hostname"])

    start_tunnel("cmd", tunnel, dest, port)
    try:
        while check_tunnel("cmd"):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
