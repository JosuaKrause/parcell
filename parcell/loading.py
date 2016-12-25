#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import division

import os
import re
import sys
import json
import time
import getpass
import paramiko
import threading
import traceback
from tej import RemoteQueue, parse_ssh_destination

from tunnel import start_tunnel, check_tunnel

def simple_msg(message, *args, **kwargs):
    print(message.format(*args, **kwargs), file=sys.stdout)

msg = simple_msg
def set_msg(m):
    global msg
    msg = m

MAIN_LOCK = threading.RLock()

DIR_ENV_DEFAULT = os.path.join(os.path.dirname(__file__), "default_envs")
DIR_ENV = "envs"
DIR_SERVER = "servers"
DIR_PROJECT = "projects"
DIR_REMOTE_TEJ = "~/.parcell"
EXT = ".json"

PW_FILE = "pw.txt"

DEFAULT_REGEX = "(.*)"
DEFAULT_LINE = 0

UPGRADE_ENV = []
UPGRADE_SERVER = []
UPGRADE_PROJECT = []

SERVER_SKIP_KEYS = frozenset([
    "needs_pw",
    "tunnel",
    "tunnel_port",
    "needs_tunnel_pw",
])

def _get_config_list(config, default=None):
    if not os.path.exists(config):
        os.makedirs(config)
    res = [ c[:-len(EXT)] for c in os.listdir(config) if c.endswith(EXT) ]
    if default is not None:
        res += [ c[:-len(EXT)] for c in os.listdir(default) if c.endswith(EXT) ]
        res = list(set(res))
    return res

def get_envs():
    return _get_config_list(DIR_ENV, DIR_ENV_DEFAULT)

def get_servers():
    return _get_config_list(DIR_SERVER)

def get_projects():
    return _get_config_list(DIR_PROJECT)

def _get_config_path(c, config):
    return "{0}{1}".format(os.path.join(config, c), EXT)

def _read_config(f_in, config, upgrade, default=None):
    if not os.path.exists(config):
        os.makedirs(config)
    path = _get_config_path(f_in, config)
    is_new = False
    if not os.path.exists(path) and default:
        path = _get_config_path(f_in, default)
        msg("{0}", path)
        is_new = True
    with open(path, 'rb') as f:
        res = json.load(f)
    res, chg = _check_version(res, upgrade)
    if chg or is_new:
        # don't overwrite the default :P
        _write_config(f_in, config, res)
    return res

def _write_config(f_out, config, obj):
    if not os.path.exists(config):
        os.makedirs(config)
    with open(_get_config_path(f_out, config), 'wb') as f:
        json.dump(obj, f, indent=2, sort_keys=True)

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
    es = _read_config(f_in, DIR_ENV, UPGRADE_ENV, DIR_ENV_DEFAULT)

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
        if regex.pattern != DEFAULT_REGEX:
            res["regex"] = regex.pattern
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

def _get_tunnel_ports():
    sobjs = [ _read_server(n) for n in get_servers() ]
    return [ int(s["tunnel_port"]) for s in sobjs if "tunnel_port" in s ]

def _write_server(f_out, server):
    obj = {}
    for (k, v) in server.items():
        if k == "password":
            continue
        obj[k] = v
    _write_config(f_out, DIR_SERVER, obj)

ALL_SERVERS = {}
def _get_server(s):
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
    s_conn = dict([ (s, _get_server(s)) for s in servers ])
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
    _write_config(f_out, DIR_PROJECT, obj)

_REUSE_PW = False
def set_password_reuse(reuse_pw):
    global _REUSE_PW
    _REUSE_PW = reuse_pw

_GLOBAL_PASSWORD = None
_ALL_PWS = {}
_ASK_REUSE = True
_ASK_REUSE_PRIMED = None
def ask_password(user, address):
    global _GLOBAL_PASSWORD
    global _ASK_REUSE
    global _ASK_REUSE_PRIMED
    pw_id = (user, address)
    if pw_id not in _ALL_PWS:
        if _ASK_REUSE_PRIMED is not None and _ask_yesno("Do you want to reuse this password for other servers"):
            set_password_reuse(True)
            res = _ASK_REUSE_PRIMED
            _ASK_REUSE_PRIMED = None
            _ASK_REUSE = False
            auto = True
        elif _REUSE_PW and _GLOBAL_PASSWORD is not None:
            res = _GLOBAL_PASSWORD
            auto = True
        elif os.path.exists(PW_FILE):
            with open(PW_FILE, 'rb') as f:
                res = f.read().strip()
            auto = True
        else:
            res = getpass.getpass("password for {0}@{1}:".format(user, address))
            if _ASK_REUSE_PRIMED is not None:
                _ASK_REUSE_PRIMED = None
                _ASK_REUSE = False
            elif _ASK_REUSE:
                _ASK_REUSE_PRIMED = res
            auto = False
        if _REUSE_PW and _GLOBAL_PASSWORD is None:
            _GLOBAL_PASSWORD = res
        if auto:
            msg("Password for {0}@{1} is known", user, address)
        _ALL_PWS[pw_id] = res
    return _ALL_PWS[pw_id]

def _setup_tunnel(s, server):
    with MAIN_LOCK:
        tunnel = parse_ssh_destination(server["tunnel"])
        if "password" in tunnel:
            raise ValueError("tunnel password should not be stored in config! {0}@{1}:{2}".format(tunnel["username"], tunnel["hostname"], tunnel["port"]))
        if server.get("needs_tunnel_pw", False):
            tunnel["password"] = ask_password(tunnel["username"], tunnel["hostname"])
        start_tunnel(s, tunnel, _get_destination_obj(server, False), server["tunnel_port"])

def _get_destination_obj(dest, front):
    res = dict([
        it for it in dest.items() if it[0] not in SERVER_SKIP_KEYS
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

ALL_REMOTES = {}
def get_remote(s):
    with MAIN_LOCK:
        server = _get_server(s)
        if "tunnel" in server and not check_tunnel(s):
            _setup_tunnel(s, server)
        if s not in ALL_REMOTES:
            if server.get("needs_pw", False) and "password" not in server:
                raise ValueError("no password found in {0}".format(server))
            remote_dir = "{0}_{1}".format(DIR_REMOTE_TEJ, s)
            dest = _get_destination_obj(server, True)
            runs = 0
            while s not in ALL_REMOTES:
                try:
                    runs += 1
                    ALL_REMOTES[s] = TunnelableRemoteQueue(dest, remote_dir, is_tunnel=("tunnel" in server))
                except (paramiko.SSHException, paramiko.ssh_exception.NoValidConnectionsError) as e:
                    time.sleep(1)
        return ALL_REMOTES[s]

def test_connection(s):
    server = _get_server(s)
    if server.get("needs_pw", False):
        server["password"] = ask_password(server["username"], server["hostname"])
    msg("Checking connectivity of {0}", s)
    conn = get_remote(s)
    conn.check_call("hostname")

def init_passwords():
    with MAIN_LOCK:
        for s in get_servers():
            test_connection(s)

def _check_project(name):
    path_local, command, env, servers, s_conn = read_project(name)
    for s in servers:
        test_connection(s)
    _write_project(name, path_local, command, env, servers, s_conn)

def _getline(line):
    return raw_input(line).rstrip("\r\n")

def _ask(line, default=None, must=True):
    line = "{0}{1}: ".format(line, '' if default is None else " ({0})".format(default))
    while True:
        res = _getline(line)
        if res != '':
            break
        if default is not None:
            res = default
            break
        if not must:
            break
    return res

def _ask_yesno(line):
    line = "{0} (yes|no): ".format(line)
    while True:
        res = _getline(line)
        if res == 'yes' or res == 'y':
            res = True
            break
        if res == 'no' or res == 'n':
            res = False
            break
    return res

PORT_LOWER = 1
PORT_UPPER = 65535
def _ask_port(line, default=None):
    while True:
        res = _ask(line, default)
        try:
            res = int(res)
            if res >= PORT_LOWER and res <= PORT_UPPER:
                break
        except ValueError:
            pass
        msg("Must be integer in the range of {0}--{1}".format(PORT_LOWER, PORT_UPPER))
    return res

def _ask_choice(line, of=[], special={}):
    num_of = len(of)
    num_special = len(special.keys())
    if not num_of and not num_special:
        raise ValueError("no choices!")
    if num_of + num_special == 1:
        return (0, of[0], True) if num_of else tuple(list(special.items()[0]) + [ False ])
    while True:
        msg("{0}:", line)
        for (ix, o) in enumerate(of):
            msg("  ({0}): {1}", ix, o)
        for (k, v) in special.items():
            msg("  ({0}): {1}", k, v)
        res = _getline("Please select: ")
        if res in special:
            res = (res, special[res], False)
            break
        try:
            res = int(res)
            if res >= 0 and res < len(of):
                res = (res, of[res], True)
                break
        except ValueError:
            pass
    return res

def _ask_server_list():
    servers = []
    while True:
        opt_list = [ s for s in get_servers() if s not in servers ]
        opt_cmds = {
            "a": "..add new server",
            "l": "..list selection",
        }
        if servers:
            opt_cmds["d"] = "..done"
        cmd, el, is_name = _ask_choice("Add server", opt_list, opt_cmds)
        if is_name:
            servers.append(el)
        elif cmd == "a":
            msg("Adding new server..")
            name, okay = add_server()
            if okay:
                servers.append(name)
            else:
                msg("Creating server failed..")
        elif cmd == "d":
            break
        elif cmd == "l":
            msg("Currently selected servers:")
            for s in servers:
                msg("  {0}", s)
    return servers

VALID_NAME_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ" \
                             "abcdefghijklmnopqrstuvwxyz" \
                             "0123456789_-+=@%:.,")
def _check_name(name):
    return all(c in VALID_NAME_CHARS for c in name)

def _get_bad_chars(name):
    return [ c for c in name if c not in VALID_NAME_CHARS ]

def add_project(name):
    if not _check_name(name):
        msg("Invalid character {0} in project name '{1}'", _get_bad_chars(name)[0], name)
        return False
    if name in get_projects():
        msg("Project '{0}' already exists!", name)
        return False
    msg("Create project '{0}'.", name)
    project = {}
    project["local"] = _ask("Project root", default=os.path.join(DIR_PROJECT, name))
    project["cmd"] = _ask("Run command")
    _, env, _ = _ask_choice("Environment", of=get_envs())
    project["env"] = env
    project["servers"] = _ask_server_list()
    _write_config(name, DIR_PROJECT, project)
    msg("Checking project configuration")
    _check_project(name)
    msg("Successfully created project '{0}'!", name)
    return True

def add_server():
    name = _ask("Server name")
    if not _check_name(name):
        msg("Invalid character {0} in server name '{1}'", _get_bad_chars(name)[0], name)
        return None, False
    if name in get_servers():
        msg("Server '{0}' already exists!", name)
        return None, False
    try:
        server = {}
        server["hostname"] = _ask("Hostname")
        server["username"] = _ask("Username")
        server["port"] = _ask_port("Port", default=22)
        server["needs_pw"] = _ask_yesno("Is a password required?")
        if _ask_yesno("Is a tunnel needed?"):
            tunnel_host = _ask("Tunnel hostname")
            tunnel_user = _ask("Tunnel username")
            tport_final = None
            while tport_final is None:
                tport = 11111
                blocked = set(_get_tunnel_ports())
                while tport in blocked:
                    tport += 1
                    if tport > PORT_UPPER:
                        raise ValueError("All ports are blocked?")
                tport_final = _ask_port("Unique tunnel port", default=tport)
                if tport_final in blocked:
                    msg("Port {0} is not unique!", tport_final)
                    tport_final = None
            server["tunnel_port"] = tport_final
            tunnel_port = _ask_port("Standard tunnel port", default=22)
            server["tunnel"] = "{0}@{1}{2}".format(
                tunnel_user,
                tunnel_host,
                ":{0}".format(tunnel_port) if tunnel_port != 22 else ""
            )
            server["needs_tunnel_pw"] = _ask_yesno("Is a tunnel password required?")
        _write_server(name, server)
        msg("Checking server configuration")
        test_connection(name)
        msg("Successfully created server '{0}'!", name)
    except (KeyboardInterrupt, SystemExit):
        raise
    except:
        msg("Error creating server {0}:\n{1}", name, traceback.format_exc())
        return None, False
    return name, True
