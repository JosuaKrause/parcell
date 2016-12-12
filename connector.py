#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import division

import os
import re
import sys
import json
import math
import getpass
import logging
import argparse

from tej import RemoteQueue, QueueDoesntExist, JobNotFound

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
        raise ValueError("project root cannot be found: {0}".format(path_local))
    command = pr["cmd"]
    env = (pr["env"], _read_env(pr["env"]))
    servers = pr["servers"]
    s_conn = dict([ (s, _read_server(s)) for s in servers ])
    needs_pw = bool(pr["pw"])
    return (path_local, command, env, servers, s_conn, needs_pw)

def _write_project(f_out, path_local, command, env, servers, s_conn, needs_pw):
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
        "pw": needs_pw,
    }

def _ask_password(user, address):
    print("{0}@{1} ".format(user, address), file=sys.stdout)
    return getpass.getpass()

def _get_remote(server, needs_pw, prompt):
    if needs_pw and "password" not in server:
        if prompt:
            server["password"] = _ask_password(server["username"], server["hostname"])
        else:
            with open(Connector.PW_FILE, 'rb') as f:
                server["password"] = f.read().strip()
    return RemoteQueue(server, Connector.DIR_REMOTE_TEJ)

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

    def __init__(self, project, prompt):
        project = _read_project(project)
        self._path_local, self._command, self._env, self._servers, self._s_conn, self._needs_pw = project
        self._prompt = prompt
        self._rqs = dict([ (s, _get_remote(self._s_conn[s], self._needs_pw, self._prompt)) for s in self._servers ])

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
        rq = self._rqs[s]

        with open(os.path.join(self._path_local, Connector.SCRIPT_FILE), 'wb') as f:
            print(self._command, file=f)

        return rq.submit(None, self._path_local, Connector.SCRIPT_FILE)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parcell Connector')
    parser.add_argument('-v', action='store_true', help="use verbose output")
    parser.add_argument('project', type=str, help="project file")
    args = parser.parse_args()

    logging.basicConfig(level=(logging.INFO if args.v else logging.CRITICAL))

    conn = Connector(args.project, True)

    for s in conn.get_servers():
        for (k, v) in conn.get_server_stats(s).items():
            if isinstance(v, (list, tuple)):
                print("{0}:".format(k))
                for (kk, vv) in v:
                    print("  {0}: {1}".format(kk, vv))
            else:
                print("{0}: {1}".format(k, v))
