#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import division

import time
import atexit
import getpass
import logging
import argparse
import threading
import subprocess

from tej import parse_ssh_destination

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
        return s in _TUNNELS and _TUNNELS[s] > 0

def clean(s):
    with _LOCK:
        if _PROCS[s] is not None:
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
            logger().debug("run %s", ' '.join(cmd))
            proc = subprocess.Popen(cmd, close_fds=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _TUNNELS[s] = 2
            _PROCS[s] = proc
            stdout, stderr = proc.communicate(stdin)
            logger().warning("SSH tunnel terminated!\nSTDOUT:\n%s\nSTDERR:\n%s\n", stdout, stderr)
            _PROCS[s] = None
        except subprocess.CalledProcessError as e:
            logger().warning("SSH tunnel failed!\n%s\n%s", ' '.join(cmd), e.output)
        finally:
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
            raise ValueError("Failed to start tunnel!")
    # might not actually be working yet
    # time.sleep(1)
    logger().debug('Tunnel open! Proceed!')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parcell Tunnel')
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
    start_tunnel("cmd", tunnel, dest, port)
    while check_tunnel("cmd"):
        time.sleep(1)
