#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import division

import os
import re
import sys
import json
import threading

def msg(message, *args, **kwargs):
    print(message.format(*args, **kwargs), file=sys.stdout)

def set_msg(m):
    global msg
    msg = m

MAIN_LOCK = threading.RLock()

DIR_ENV = "env"
DIR_SERVER = "server"
DIR_PROJECT = "project"
EXT = ".json"

DEFAULT_REGEX = "(.*)"
DEFAULT_LINE = 0

UPGRADE_ENV = []
UPGRADE_SERVER = []
UPGRADE_PROJECT = []

def _get_config_list(config):
    if not os.path.exists(config):
        os.makedirs(config)
    return [ c[:-len(EXT)] for c in os.listdir(config) if c.endswith(EXT) ]

def get_envs():
    return _get_config_list(DIR_ENV)

def get_servers():
    return _get_config_list(DIR_SERVER)

def get_projects():
    return _get_config_list(DIR_PROJECT)

def _get_config_path(c, config):
    return "{0}{1}".format(os.path.join(config, c), EXT)

def _read_config(f_in, config, upgrade):
    if not os.path.exists(config):
        os.makedirs(config)
    with open(_get_config_path(f_in, config), 'rb') as f:
        res = json.load(f)
    res, chg = _check_version(res, upgrade)
    if chg:
        _write_config(f_in, config, res)
    return res

def _write_config(f_out, config, obj):
    if not os.path.exists(config):
        os.makedirs(config)
    with open(_get_config_path(f_out, config), 'wb') as f:
        json.write(obj)

def _check_version(obj, upgrade):
    v = int(obj.get("version", 0))
    chg = False
    while v < len(upgrade):
        obj = upgrade[v](obj)
        v += 1
        obj["version"] = v
        chg = True
    return obj, chg

def _read_env(f_in):
    es = _read_config(f_in, DIR_ENV, UPGRADE_ENV)

    def get(field):
        res = []
        if field in es:
            for e in es[field]:
                name = e["name"]
                cmd = e["cmd"]
                regex = re.compile(e.get("regex", DEFAULT_REGEX))
                line = int(e.get("line", DEFAULT_LINE))
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
        if regex != DEFAULT_REGEX:
            res["regex"] = regex
        if line != DEFAULT_LINE:
            res["line"] = line
        return res

    for (k, es) in env.items():
        obj[k] = [ conv(e) for e in es ]
    _write_config(f_out, DIR_ENV, obj)

def _read_server(f_in):
    res = _read_config(f_in, DIR_SERVER, UPGRADE_SERVER)
    if "password" in res:
        raise ValueError("password should not be stored in config! {0}".format(f_in))
    return res

def _write_server(f_out, server):
    obj = {}
    for (k, v) in server.items():
        if k == "password":
            continue
        obj[k] = v
    _write_config(f_out, DIR_SERVER, obj)

ALL_SERVERS = {}
def get_server(s):
    with MAIN_LOCK:
        if s not in ALL_SERVERS:
            ALL_SERVERS[s] = _read_server(s)
        return ALL_SERVERS[s]

def read_project(f_in):
    pr = _read_config(f_in, DIR_PROJECT, UPGRADE_PROJECT)
    path_local = pr["local"]
    if not os.path.exists(path_local):
        os.makedirs(path_local)
    command = pr["cmd"]
    env = (pr["env"], _read_env(pr["env"]))
    servers = pr["servers"]
    s_conn = dict([ (s, get_server(s)) for s in servers ])
    return (path_local, command, env, servers, s_conn)

def _write_project(f_out, path_local, command, env, servers, s_conn):
    e_name, e_obj = env
    _write_env(e_name, e_obj)

    def get_server_name(s_name):
        _write_server(s_name, s_conn[s_name])
        return s_name

    obj = {
        "local": path_local,
        "cmd": command,
        "env": e_name,
        "servers": [ get_server_name(s) for s in servers ],
    }
