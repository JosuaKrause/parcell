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
import getpass
import logging
import argparse
import paramiko
import threading

from tunnel import start_tunnel, check_tunnel

from tej import RemoteQueue, QueueDoesntExist, JobNotFound, parse_ssh_destination

def msg(message, *args, **kwargs):
    print(message.format(*args, **kwargs), file=sys.stdout)

def set_msg(m):
    global msg
    msg = m

def _get_config_list(config):
    if not os.path.exists(config):
        os.makedirs(config)
    return [ c[:-len(Connector.EXT)] for c in os.listdir(config) if c.endswith(Connector.EXT) ]

def get_envs():
    return _get_config_list(Connector.DIR_ENV)

def get_servers():
    return _get_config_list(Connector.DIR_SERVER)

def get_projects():
    return _get_config_list(Connector.DIR_PROJECT)

def _get_config_path(c, config):
    return "{0}{1}".format(os.path.join(config, c), Connector.EXT)

def _read_config(f_in, config):
    if not os.path.exists(config):
        os.makedirs(config)
    with open(_get_config_path(f_in, config), 'rb') as f:
        return json.load(f)

def _write_config(f_out, config, obj):
    if not os.path.exists(config):
        os.makedirs(config)
    with open(_get_config_path(f_out, config), 'wb') as f:
        json.write(obj)

def _read_env(f_in):
    es = _read_config(f_in, Connector.DIR_ENV)

    def get(field):
        res = []
        if field in es:
            for e in es[field]:
                name = e["name"]
                cmd = e["cmd"]
                regex = re.compile(e.get("regex", Connector.DEFAULT_REGEX))
                line = int(e.get("line", Connector.DEFAULT_LINE))
                res.append((name, cmd, regex, line))
        return res

    return {
        "versions": get("versions"),
        "cpus": get("cpus"),
    }

def _write_env(f_out, env):
    obj = {}

    def conv(e):
        name, cmd, regex, line = e
        res = {
            "name": name,
            "cmd": cmd,
        }
        if regex != Connector.DEFAULT_REGEX:
            res["regex"] = regex
        if line != Connector.DEFAULT_LINE:
            res["line"] = line
        return res

    for (k, es) in env.items():
        obj[k] = [ conv(e) for e in es ]
    _write_config(f_out, Connector.DIR_ENV, obj)

def _read_server(f_in):
    res = _read_config(f_in, Connector.DIR_SERVER)
    if "password" in res:
        raise ValueError("password should not be stored in config! {0}".format(f_in))
    return res

def _get_server(s):
    with Connector._MAIN_LOCK:
        if s not in Connector._ALL_SERVERS:
            Connector._ALL_SERVERS[s] = _read_server(s)
        return Connector._ALL_SERVERS[s]

def _write_server(f_out, server):
    obj = {}
    for (k, v) in server.items():
        if k == "password":
            continue
        obj[k] = v
    _write_config(f_out, Connector.DIR_SERVER, obj)

def _read_project(f_in):
    pr = _read_config(f_in, Connector.DIR_PROJECT)
    path_local = pr["local"]
    if not os.path.exists(path_local):
        os.makedirs(path_local)
    command = pr["cmd"]
    env = (pr["env"], _read_env(pr["env"]))
    servers = pr["servers"]
    s_conn = dict([ (s, _get_server(s)) for s in servers ])
    return (path_local, command, env, servers, s_conn)

def _write_project(f_out, path_local, command, env, servers, s_conn):
    e_name, e_obj = env
    _write_env(e_name, e_obj)

    def get_server(s_name):
        _write_server(s_name, s_conn[s_name])
        return s_name

    obj = {
        "local": path_local,
        "cmd": command,
        "env": e_name,
        "servers": [ get_server(s) for s in servers ],
    }

_REUSE_PW = False
def set_password_reuse(reuse_pw):
    global _REUSE_PW
    _REUSE_PW = reuse_pw

_GLOBAL_PASSWORD = None
def _ask_password(user, address):
    global _GLOBAL_PASSWORD
    pw_id = (user, address)
    if pw_id not in Connector._ALL_PWS:
        if _REUSE_PW and _GLOBAL_PASSWORD is not None:
            res = _GLOBAL_PASSWORD
        elif os.path.exists(Connector.PW_FILE):
            with open(Connector.PW_FILE, 'rb') as f:
                res = f.read().strip()
        else:
            res = getpass.getpass("password for {0}@{1}:".format(user, address))
        if _REUSE_PW and _GLOBAL_PASSWORD is None:
            _GLOBAL_PASSWORD = res
        Connector._ALL_PWS[pw_id] = res
    return Connector._ALL_PWS[pw_id]

def _ask_for_ssh_replay(dest, e):
    msg("SSH connection could not be established due to\n{0}", e)
    msg("Please establish a SSH connection in a *different* terminal using")
    msg("\nssh{0} {1}{2} hostname\n",
        " -p {0}".format(dest["port"]) if "port" in dest else "",
        "{0}@".format(dest["username"]) if "username" in dest else "",
        dest["hostname"],
        )
    msg("Press ENTER to continue after a connection was successfully established to try again")
    raw_input("")

def _setup_tunnel(s, server):
    with Connector._MAIN_LOCK:
        tunnel = parse_ssh_destination(server["tunnel"])
        if "password" in tunnel:
            raise ValueError("tunnel password should not be stored in config! {0}@{1}:{2}".format(tunnel["username"], tunnel["hostname"], tunnel["port"]))
        if server.get("needs_tunnel_pw", False):
            tunnel["password"] = _ask_password(tunnel["username"], tunnel["hostname"])
        start_tunnel(s, tunnel, _get_destination_obj(server, False), server["tunnel_port"])

def _get_destination_obj(dest, front):
    res = dict([
        it for it in dest.items() if it[0] not in Connector.SERVER_SKIP_KEYS
    ])
    if front and "tunnel_port" in dest:
        res["hostname"] = "127.0.0.1"
        res["port"] = dest["tunnel_port"]
    return res

class TunnelableRemoteQueue(RemoteQueue):
    def __init__(self, *args, **kwargs):
        # needs to be before actual constructor because
        # _ssh_client is called from within
        self.is_tunnel = kwargs.pop("is_tunnel", False)
        RemoteQueue.__init__(self, *args, **kwargs)

    def _ssh_client(self):
         ssh = paramiko.SSHClient()
         ssh.load_system_host_keys()
         policy = paramiko.RejectPolicy() if not self.is_tunnel else paramiko.WarningPolicy()
         ssh.set_missing_host_key_policy(policy)
         return ssh

def _get_remote(s):
    with Connector._MAIN_LOCK:
        server = _get_server(s)
        if "tunnel" in server and not check_tunnel(s):
            _setup_tunnel(s, server)
        if s not in Connector._ALL_REMOTES:
            if server.get("needs_pw", False) and "password" not in server:
                raise ValueError("no password found in {0}".format(server))
            remote_dir = "{0}_{1}".format(Connector.DIR_REMOTE_TEJ, s)
            dest = _get_destination_obj(server, True)
            runs = 0
            while s not in Connector._ALL_REMOTES:
                try:
                    runs += 1
                    Connector._ALL_REMOTES[s] = TunnelableRemoteQueue(dest, remote_dir, is_tunnel=("tunnel" in server))
                except (paramiko.SSHException, paramiko.ssh_exception.NoValidConnectionsError) as e:
                    if runs < 5:
                        time.sleep(1)
                    else:
                        _ask_for_ssh_replay(dest, e)
        return Connector._ALL_REMOTES[s]

def _test_connection(s):
    msg("checking connectivity of {0}", s)
    conn = _get_remote(s)
    conn.check_call("hostname")

def init_passwords():
    with Connector._MAIN_LOCK:
        for s in get_servers():
            server = _get_server(s)
            server["password"] = _ask_password(server["username"], server["hostname"])
            _test_connection(s)

def get_connector(project):
    with Connector._MAIN_LOCK:
        if project not in Connector._ALL_CONNECTORS:
            Connector(project) # adds itself to the list
        return Connector._ALL_CONNECTORS[project]

class Connector(object):
    DIR_REMOTE_TEJ = "~/.parcell"
    DIR_ENV = "env"
    DIR_SERVER = "server"
    DIR_PROJECT = "project"
    EXT = ".json"
    SCRIPT_FILE = "_start"
    PW_FILE = "pw.txt"

    DEFAULT_REGEX = "(.*)"
    DEFAULT_LINE = 0

    SERVER_SKIP_KEYS = frozenset([
        "needs_pw",
        "tunnel",
        "tunnel_port",
        "needs_tunnel_pw",
    ])
    _ALL_SERVERS = {}
    _ALL_REMOTES = {}
    _ALL_CONNECTORS = {}
    _ALL_PWS = {}
    _MAIN_LOCK = threading.RLock()

    def __init__(self, p):
        self._lock = threading.RLock()
        project = _read_project(p)
        self._path_local, self._command, self._env, self._servers, self._s_conn = project
        self._rqs = dict([ (s, _get_remote(s)) for s in self._servers ])
        Connector._ALL_CONNECTORS[p] = self

    def get_path(self):
        return self._path_local

    def get_command(self):
        return self._command

    def get_env(self):
        return self._env[0]

    def _get_env(self, rq, chk):
        name, cmd, regex, line = chk
        output = rq.check_output(cmd)
        oarr = output.split("\n")
        if line >= len(oarr):
            raise ValueError("line {0} not in:\n{1}".format(line, oarr))
        m = regex.search(oarr[line])
        if m is None:
            raise ValueError("unexpected mismatch {0} not in:\n{1}".format(regex.pattern, oarr[line]))
        return name, m.group(1)

    def get_cpu(self, rq):
        for cpu in self._env[1]["cpus"]:
            _, c = self._get_env(rq, cpu)
            if c:
                try:
                    return float(c)
                except TypeError:
                    pass
        return float('nan')

    def get_servers(self):
        return self._servers

    def get_server_stats(self, s):
        server = self._s_conn[s]
        rq = self._rqs[s]
        return {
            "name": server["hostname"],
            "versions": [ self._get_env(rq, chk) for chk in self._env[1]["versions"] ],
            "cpu": self.get_cpu(rq),
        }

    def get_all_cpus(self):
        return [ (s, self.get_cpu(self._rqs[s])) for s in self.get_servers() ]

    def get_best_server(self):
        servers = self.get_servers()
        if len(servers) < 2:
            return servers[0] if servers else None
        best_s = None
        best_cpu = float('nan')
        for (s, cpu) in self.get_all_cpus():
            if math.isnan(best_cpu) or cpu < best_cpu:
                best_s = s
                best_cpu = cpu
        if math.isnan(best_cpu):
            return None
        return best_s

    def get_all_jobs(self):
        return [ (s, j, i) for s in self.get_servers() for (j, i) in self.get_job_list(s) ]

    def get_job_list(self, s):
        try:
            rq = self._rqs[s]
            return list(rq.list())
        except QueueDoesntExist:
            return []

    def get_job_status(self, s, j):
        rq = self._rqs[s]
        status, path, result = rq.status(j)
        return {
            "status": status,
            "path": str(path),
            "result": result,
        }

    def submit_job(self, s):
        with self._lock:
            rq = self._rqs[s]

            with open(os.path.join(self._path_local, Connector.SCRIPT_FILE), 'wb') as f:
                print(self._command, file=f)

            return rq.submit(None, self._path_local, Connector.SCRIPT_FILE)

    def get_job_files(self, s, j, rel_path):
        rq = self._rqs[s]
        status, path, result = rq.status(j)
        return rq.check_output("ls -p1t {0}".format(str(path / rel_path))).split("\n")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parcell Connector')
    parser.add_argument('--reuse-pw', action='store_true', dest='reuse_pw', help="only ask for one password")
    parser.add_argument('-v', '--verbose', action='count', default=1, dest='verbosity', help="augments verbosity level")
    parser.add_argument('project', type=str, nargs='?', help="project file")
    args = parser.parse_args()

    levels = [ logging.CRITICAL, logging.WARNING, logging.INFO, logging.DEBUG ]
    logging.basicConfig(level=levels[min(args.verbosity, 3)])

    if not args.project:
        for p in get_projects():
            print(p)
        exit(0)

    msg("{0}", " ".join(sys.argv))
    msg("initializing passwords -- please type as prompted")
    set_password_reuse(args.reuse_pw)
    init_passwords()
    msg("initializing passwords -- done")

    conn = Connector(args.project)
    for s in conn.get_servers():
        for (k, v) in conn.get_server_stats(s).items():
            if isinstance(v, (list, tuple)):
                print("{0}:".format(k))
                for (kk, vv) in v:
                    print("  {0}: {1}".format(kk, vv))
            else:
                print("{0}: {1}".format(k, v))
