#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import division

import os
import re
import sys
import json
import math
import time
import select
import socket
import getpass
import logging
import paramiko
import threading
try:
    import SocketServer
except ImportError:
    import socketserver as SocketServer

BUFF_SIZE = 1024

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
def start_tunnel(s, via, dest, tunnel_port):
    with _LOCK:
        if check_tunnel(s):
            return
        forward_tunnel(s, int(tunnel_port), via, dest)

def check_tunnel(s):
    with _LOCK:
        return s in _TUNNELS and _TUNNELS[s] > 0

class ForwardServer(SocketServer.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

class Handler(SocketServer.BaseRequestHandler):

    def handle(self):
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            logger().debug('Connecting with %s', _pretty_dest(self.tunnel))
            client.connect(**self.tunnel)
            transport = client.get_transport()
            # FIXME don't start a new connection every time!

            chain_host = self.chain["hostname"]
            chain_port = self.chain.get("port", 22)
            chain_addr = (chain_host, chain_port)
            logger().debug('Using tunnel! %s:%d', chain_host, chain_port)
            if not transport.is_active():
                logger().warning('Connection "%s" not active anymore', self.sid)
                _TUNNELS[self.sid] = -2
                return
            try:
                chan = transport.open_channel('direct-tcpip', chain_addr,
                                              self.request.getpeername())
            except Exception as e:
                logger().warning('Incoming request to %s:%d failed: %s', chain_host, chain_port, repr(e))
                _TUNNELS[self.sid] = -3
                return
            if chan is None:
                logger().warning('Incoming request to %s:%d was rejected by the SSH server.', *chain_addr)
                _TUNNELS[self.sid] = -4
                return
            logger().debug('Connected! Tunnel open %r -> %r -> %r', self.request.getpeername(), chan.getpeername(), chain_addr)
            try:
                while True:
                    r, w, x = select.select([ self.request, chan ], [], [])
                    if self.request in r:
                        data = self.request.recv(BUFF_SIZE)
                        if len(data) == 0:
                            break
                        chan.send(data)
                    if chan in r:
                        data = chan.recv(BUFF_SIZE)
                        if len(data) == 0:
                            break
                        self.request.send(data)
            finally:
                peername = self.request.getpeername()
                chan.close()
                self.request.close()
                logger().debug('Tunnel closed from %r', peername)
        finally:
            client.close()

def forward_tunnel(s, local_port, via, remote):

    class SubHander(Handler):
        chain = remote
        sid = s
        tunnel = via

    def run():
        try:
            _TUNNELS[s] = 1
            fs = ForwardServer(('', local_port), SubHander)
            _TUNNELS[s] = 2
            fs.serve_forever()
        finally:
            _TUNNELS[s] = -1

    _TUNNELS[s] = 0
    t = threading.Thread(target=run, name="Tunnel-{0}".format(s))
    t.daemon = True
    t.start()
    logger().debug('Waiting for tunnel to open...')
    while _TUNNELS[s] < 2:
        if _TUNNELS[s] < 0:
            raise ValueError("Failed to start tunnel!")
    time.sleep(0.1)
    logger().debug('Tunnel open! Proceed!')
