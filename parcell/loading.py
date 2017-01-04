#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import division

import os
import re
import sys
import json
import time
import atexit
import base64
import shutil
import getpass
import hashlib
import binascii
import paramiko
import threading
import traceback
from rpaths import PosixPath
from tej import RemoteQueue, parse_ssh_destination, QueueDoesntExist, RemoteCommandFailure, JobNotFound

from tunnel import start_tunnel, check_tunnel, check_permission_denied

def simple_msg(message, *args, **kwargs):
    print(message.format(*args, **kwargs), file=sys.stdout)

msg = simple_msg
def set_msg(m):
    global msg
    msg = m

MAIN_LOCK = threading.RLock()

DEFAULT_BASE = os.path.dirname(__file__)
DIR_ENV_DEFAULT = os.path.join(DEFAULT_BASE, "default_envs")
DIR_ENV = "envs"
DIR_SERVER = "servers"
DIR_PROJECT = "projects"
DIR_TEMP = "temp_files"
EXT = ".json"

DIR_REMOTE_TEJ = "~/.parcell"

LOCALHOST = "127.0.0.1"

DEFAULT_REGEX = "(.*)"
DEFAULT_LINE = 0

UPGRADE_ENV = []
UPGRADE_SERVER = []
UPGRADE_PROJECT = []

def upgrade(array, version):
    def wrapper(func):
        if len(array) != version:
            raise ValueError("upgrade definition in wrong order {0} != {1}".format(len(array), version))
        array.append(func)
        return func
    return wrapper

def _get_config_list(config, default=None, no_default=False):
    if not os.path.exists(config):
        if no_default:
            return []
        os.makedirs(config)
    res = [ c[:-len(EXT)] for c in os.listdir(config) if c.endswith(EXT) ]
    if default is not None and not no_default:
        res += [ c[:-len(EXT)] for c in os.listdir(default) if c.endswith(EXT) ]
        res = list(set(res))
    return res

def get_envs(no_default=False):
    return _get_config_list(DIR_ENV, DIR_ENV_DEFAULT, no_default=no_default)

def get_servers(no_default=False):
    return _get_config_list(DIR_SERVER, no_default=no_default)

def get_projects(no_default=False):
    return _get_config_list(DIR_PROJECT, no_default=no_default)

def _get_path(path, name):
    return os.path.join(path, "{0}{1}".format(name, EXT))

def _write_json(path, obj):
    with open(path, 'wb') as f:
        json.dump(obj, f, indent=2, sort_keys=True)

def _rm_json(config, path):
    if os.path.exists(path):
        os.remove(path)
    if not _get_config_list(config, no_default=True):
        os.rmdir(config)

CONFIG_LOG = threading.RLock()
ALL_CONFIG = {}
CONFIG_NUM = 0
def _close_all_config():
    with CONFIG_LOG:
        for c in list(ALL_CONFIG.values()):
            c.close()

atexit.register(_close_all_config)

class Config(object):

    def __init__(self, name):
        global CONFIG_NUM
        if not _check_name(name):
            raise ValueError("bad character '{0}' in name '{1}'".format(_get_bad_chars(name)[0], name))
        self._name = name
        self._chg = False
        self._closed = True
        self._deleted = False
        with CONFIG_LOG:
            self._config_num = CONFIG_NUM
            CONFIG_NUM += 1
        self._reopen()

    def is_deleted(self):
        return self._deleted

    def _reopen(self):
        if not self.is_closed():
            return
        with CONFIG_LOG:
            if self.is_deleted():
                return
            self._obj = self._read()
            self._closed = False
            ALL_CONFIG[self._config_num] = self

    def close(self):
        with CONFIG_LOG:
            if self._config_num in ALL_CONFIG:
                del ALL_CONFIG[self._config_num]
            if self._chg and not self.is_closed() and not self.is_deleted():
                self._chg = False
                self._write(self.write_object(self._obj))
            self._closed = True

    def is_closed(self):
        return self._closed

    def _get_config_path(self, config):
        return _get_path(config, self._name)

    def _read(self):
        if self.is_deleted():
            raise ValueError("server description does not exist!")
        config = self.get_config_dir()
        if not os.path.exists(config):
            os.makedirs(config)
        path = self._get_config_path(config)
        is_new = False
        if not os.path.exists(path) and default is not None:
            path = self._get_config_path(default)
            msg("{0}", path)
            is_new = True
        with open(path, 'rb') as f:
            res = json.load(f)
        res, chg = self._check_version(res)
        if chg or is_new:
            if not is_new:
                os.rename(path, path + ".old")
            self._write(res)
        return self.read_object(res)

    def _check_version(self, obj):
        upgrade = self.get_upgrade_list()
        v = int(obj.get("version", 0))
        chg = False
        while v < len(upgrade):
            obj = upgrade[v](obj)
            v += 1
            obj["version"] = v
            chg = True
        return obj, chg

    def _write(self, obj):
        if self.is_deleted():
            return
        config = self.get_config_dir()
        if not os.path.exists(config):
            os.makedirs(config)
        obj["version"] = len(self.get_upgrade_list())
        _write_json(self._get_config_path(config), obj)

    def delete_file(self):
        with CONFIG_LOG:
            self._deleted = True
            self.close()
            config = self.get_config_dir()
            _rm_json(config, self._get_config_path(config))

    def get_config_dir(self):
        raise NotImplementedError("get_config_dir")

    def get_default_dir(self):
        return None

    def get_upgrade_list(self):
        raise NotImplementedError("get_upgrade_list")

    def set_change(self, chg):
        self._chg = chg
        if chg:
            self._reopen()

    def has_change(self):
        return self._chg

    def read_object(self, obj):
        return obj

    def write_object(self, obj):
        return obj

    def __getitem__(self, key):
        self._reopen()
        return self._obj[key]

    def __setitem__(self, key, value):
        self._reopen()
        if key not in self._obj or self._obj[key] != value:
            self._obj[key] = value
            self.set_change(True)

    def __contains__(self, key):
        self._reopen()
        return key in self._obj

    def get(self, key, default=None):
        if key not in self:
            return default
        return self[key]

    @property
    def name(self):
        return self._name

    def get_obj(self, skip=None):
        self._reopen()
        return dict(
            it for it in self._obj.items() if skip is None or it[0] not in skip
        )

class EnvConfig(Config):

    def __init__(self, name):
        super(EnvConfig, self).__init__(name)

    def get_config_dir(self):
        return DIR_ENV

    def get_default_dir(self):
        return DIR_ENV_DEFAULT

    def get_upgrade_list(self):
        return UPGRADE_ENV

    def read_object(self, obj):

        def get(field, version):
            res = []
            if field in obj:
                for e in obj[field]:
                    name = e["name"]
                    cmd = e["cmd"]
                    regex = re.compile(e.get("regex", DEFAULT_REGEX))
                    line = int(e.get("line", DEFAULT_LINE))
                    if not version:
                        asc = e.get("asc", True)
                        res.append((name, cmd, regex, line, asc))
                    else:
                        res.append((name, cmd, regex, line))
            return res

        return {
            "versions": get("versions", True),
            "vital": get("vital", False),
        }

    def write_object(self, obj):

        def conv(e, version):
            if not version:
                name, cmd, regex, line, asc = e
                res = {
                    "name": name,
                    "cmd": cmd,
                    "asc": asc,
                }
            else:
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

        return {
            "versions": [ conv(e, True) for e in obj["versions"] ],
            "vital": [ conv(e, False) for e in obj["vital"] ],
        }

@upgrade(UPGRADE_ENV, 0)
def up_e0(obj):
    obj["vital"] = obj["cpus"]
    del obj["cpus"]
    for o in obj["vital"]:
        o["asc"] = True
    return obj

ALL_ENVS = {}
def get_env(e):
    with MAIN_LOCK:
        if e not in ALL_ENVS:
            ALL_ENVS[e] = EnvConfig(e)
        return ALL_ENVS[e]

SERVER_SKIP_KEYS = frozenset([
    "needs_pw",
    "tunnel",
    "tunnel_port",
    "needs_tunnel_pw",
    "key",
    "version",
])
class ServerConfig(Config):

    def __init__(self, name):
        super(ServerConfig, self).__init__(name)

    def get_config_dir(self):
        return DIR_SERVER

    def get_upgrade_list(self):
        return UPGRADE_SERVER

    def read_object(self, obj):
        if "password" in obj:
            raise ValueError("password should not be stored in config! {0}".format(self._name))
        return obj

    def write_object(self, obj):
        return dict((k, v) for (k, v) in obj.items() if k != "password")

    def get_destination_obj(self, front):
        res = self.get_obj(SERVER_SKIP_KEYS)
        if front and "tunnel_port" in self:
            res["hostname"] = LOCALHOST
            res["port"] = self["tunnel_port"]
        return res

    def __setitem__(self, key, value):
        chg = self.has_change()
        super(ServerConfig, self).__setitem__(key, value)
        if key == "password":
            self.set_change(chg)

    def check_key(self, hostname, key_type, key_base64, key_fp):
        if hostname != self["hostname"]:
            raise ValueError("mismatching hostname '{0}' != '{1}'".format(hostname, self["hostname"]))
        kobj = self.get("key", {})
        known_base64 = kobj.get("base64", None)
        if known_base64 is None:
            replay_fp = hashlib.md5(base64.decodestring(key_base64)).hexdigest()
            if replay_fp != key_fp:
                raise ValueError("Error encoding fingerprint of '{0}'! {1} != {2}\n{3}: {4}".format(hostname, replay_fp, key_fp, key_type, key_base64))
            msg("The authenticity of host '{0}' can't be established.", hostname)
            pretty_fp = ':'.join(a + b for (a, b) in zip(key_fp[::2], key_fp[1::2]))
            msg("{0} key fingerprint is {1}.", key_type, pretty_fp)
            if not _ask_yesno("Are you sure you want to continue connecting?"):
                sys.exit(1)
            self["key"] = {
                "type": key_type,
                "base64": key_base64,
            }
        # FIXME: there might be a better way
        if key_type != self["key"]["type"]:
            raise ValueError("mismatching key type for '{0}'. '{1}' != '{2}'".format(hostname, key_type, self["key"]["type"]))
        if key_base64 != self["key"]["base64"]:
            raise ValueError("mismatching {0} key for '{1}'. '{2}' != '{3}'".format(key_type, hostname, key_base64, self["key"]["base64"]))

@upgrade(UPGRADE_SERVER, 0)
def up_s0(obj):
    obj["key"] = {
        "type": None,
        "base64": None,
    }
    return obj

ALL_SERVERS = {}
def get_server(s):
    with MAIN_LOCK:
        if s not in ALL_SERVERS:
            ALL_SERVERS[s] = ServerConfig(s)
        return ALL_SERVERS[s]

class ProjectConfig(Config):

    def __init__(self, name):
        super(ProjectConfig, self).__init__(name)
        if not os.path.exists(self.path_local):
            os.makedirs(self.path_local)

    def get_config_dir(self):
        return DIR_PROJECT

    def get_upgrade_list(self):
        return UPGRADE_PROJECT

    def read_object(self, obj):
        return {
            "local": obj["local"],
            "cmds": obj["cmds"],
            "env": get_env(obj["env"]),
            "servers": [ get_server(s) for s in obj["servers"] ],
        }

    def write_object(self, obj):
        return {
            "local": obj["local"],
            "cmds": obj["cmds"],
            "env": obj["env"].name,
            "servers": [ s.name for s in obj["servers"] ],
        }

    @property
    def path_local(self):
        return self["local"]

    @property
    def commands(self):
        return self["cmds"]

    def remove_server(self, server):
        self["servers"] = [ s for s in self["servers"] if s.name != server ]

    def add_cmd(self, cmd):
        cmd = cmd.strip()
        if not cmd:
            return
        if cmd in self["cmds"] and cmd == self["cmds"][0]:
            return
        self["cmds"] = [ cmd ] + [ c for c in self["cmds"] if c != cmd ]

    @property
    def servers(self):
        return dict( (s.name, s) for s in self["servers"] )

@upgrade(UPGRADE_PROJECT, 0)
def up_p0(obj):
    obj["cmds"] = [ obj["cmd"] ]
    del obj["cmd"]
    return obj

ALL_PROJECTS = {}
def get_project(p):
    with MAIN_LOCK:
        if p not in ALL_PROJECTS:
            ALL_PROJECTS[p] = ProjectConfig(p)
        return ALL_PROJECTS[p]

def _get_tunnel_ports():
    sobjs = [ get_server(n) for n in get_servers() ]
    return [ int(s["tunnel_port"]) for s in sobjs if "tunnel_port" in s ]

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
        else:
            res = _getpass("password for {0}@{1}:".format(user, address))
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

def _setup_tunnel(server):
    with MAIN_LOCK:
        s = server.name
        tunnel = parse_ssh_destination(server["tunnel"])
        if "password" in tunnel:
            raise ValueError("tunnel password should not be stored in config! {0}@{1}:{2}".format(tunnel["username"], tunnel["hostname"], tunnel["port"]))
        if server.get("needs_tunnel_pw", False):
            tunnel["password"] = ask_password(tunnel["username"], tunnel["hostname"])
        start_tunnel(s, tunnel, server.get_destination_obj(False), server["tunnel_port"])

class LocalAddPolicy(paramiko.client.MissingHostKeyPolicy):

    def __init__(self, s_obj):
        self.s_obj = s_obj
        super(LocalAddPolicy, self).__init__()

    def missing_host_key(self, client, hostname, key):
        server = self.s_obj
        if "tunnel_port" in server and hostname == "[{0}]:{1}".format(LOCALHOST, server["tunnel_port"]):
            hostname = server["hostname"]
        server.check_key(hostname, key.get_name(), key.get_base64(), binascii.hexlify(key.get_fingerprint()))

class TunnelableRemoteQueue(RemoteQueue):

    def __init__(self, *args, **kwargs):
        # needs to be before actual constructor because
        # _ssh_client is called from within
        self.s_obj = kwargs.pop("s_obj")
        super(TunnelableRemoteQueue, self).__init__(*args, **kwargs)

    def _ssh_client(self):
         ssh = super(TunnelableRemoteQueue, self)._ssh_client()
         ssh.set_missing_host_key_policy(LocalAddPolicy(self.s_obj))
         return ssh

ALL_REMOTES = {}
def get_remote(server):
    with MAIN_LOCK:
        s = server.name
        if "tunnel" in server and not check_tunnel(s):
            _setup_tunnel(server)
        if s not in ALL_REMOTES:
            if server.get("needs_pw", False) and "password" not in server:
                raise ValueError("no password found in {0}".format(s))
            remote_dir = "{0}_{1}".format(DIR_REMOTE_TEJ, s)
            dest = server.get_destination_obj(True)
            while s not in ALL_REMOTES:
                try:
                    ALL_REMOTES[s] = TunnelableRemoteQueue(dest, remote_dir, s_obj=server)
                except paramiko.ssh_exception.NoValidConnectionsError as e:
                    if e.errno is None:
                        if "tunnel" in server:
                            if check_permission_denied(s):
                                msg("Incorrect password for {0}.", server["tunnel"])
                                sys.exit(1)
                            if not check_tunnel(s):
                                msg("Error starting tunnel! Re-run with -vv for more information.")
                                sys.exit(1)
                            time.sleep(1)
                    else:
                        raise e
        return ALL_REMOTES[s]

def test_connection(server, save):
    s = server.name
    if server.get("needs_pw", False):
        server["password"] = ask_password(server["username"], server["hostname"])
    msg("Checking connectivity of {0}", s)
    conn = get_remote(server)
    conn.check_call("hostname")
    if save:
        server.set_change(True)
        server.close()

def init_passwords():
    with MAIN_LOCK:
        for s in get_servers():
            test_connection(get_server(s), False)

def _check_project(name):
    p = get_project(name)
    for s in p["servers"]:
        test_connection(s, True)
    p.set_change(True)
    p.close()

def list_jobs(rq):
    try:
        return [ ji for ji in rq.list() ]
    except QueueDoesntExist:
        return []

def kill_job(rq, s, j):
    try:
        rq.kill(j)
    except (RemoteCommandFailure, JobNotFound):
        pass
    try:
        rq.delete(j)
    except JobNotFound:
        pass
    path = str(PosixPath(DIR_TEMP) / s / j)
    if os.path.exists(path):
        shutil.rmtree(path)

def remove_server(s):
    with MAIN_LOCK:
        msg("removing server '{0}' from projects", s)
        for p in get_projects(no_default=True):
            get_project(p).remove_server(s)
        msg("stopping all jobs on '{0}'", s)
        server = get_server(s)
        test_connection(server, False)
        rq = get_remote(server)
        for (j, _) in list_jobs(rq):
            kill_job(rq, s, j)
        rpath = str(rq.queue)
        msg("removing server side files '{0}'", rpath)
        rq.check_call("rm -rf -- {0}".format(rpath))
        msg("removing server description '{0}'", s)
        server.delete_file()

def remove_all():
    with MAIN_LOCK:
        msg("removing all servers")
        for s in get_servers(no_default=True):
            remove_server(s)
        msg("removing all projects")
        for p in get_projects(no_default=True):
            msg("removing project '{0}'", p)
            get_project(p).delete_file()
        msg("removing all environments")
        for e in get_envs(no_default=True):
            msg("removing environment '{0}'", p)
            get_env(e).delete_file()
        msg("Successfully removed all local and remote data!")

ALLOW_ASK = True
def allow_ask(allow):
    global ALLOW_ASK
    ALLOW_ASK = allow

def _getline(line):
    if not ALLOW_ASK:
        msg("Not allowed to use prompt! Terminating!\n{0}--", line)
        sys.exit(1)
    return raw_input(line).rstrip("\r\n")

def _getpass(line):
    if not ALLOW_ASK:
        msg("Not allowed to use prompt! Terminating!\n{0}--", line)
        sys.exit(1)
    return getpass.getpass(line)

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

def confirm_critical(line, expect):
    msg("{0}", line)
    res = _getline("Type '{0}' to confirm: ".format(expect))
    return res == expect

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
    project = {
        "cmds": [],
    }
    project["local"] = _ask("Project root", default=os.path.join(DIR_PROJECT, name))
    _, env, _ = _ask_choice("Environment", of=get_envs())
    project["env"] = env
    project["servers"] = _ask_server_list()
    _write_json(_get_path(DIR_PROJECT, name), project)
    msg("Checking project configuration")
    _check_project(name)
    msg("Successfully created project '{0}'!", name)
    return True

def _infer_server_name(hostname):
    if not _check_name(hostname):
        return None
    cur_host = hostname
    name = ''
    while '.' in cur_host:
        dot = cur_host.index('.')
        name = "{0}{1}{2}".format(name, '.' if name != '' else '', cur_host[:dot])
        if name not in get_servers():
            return name
        cur_host = cur_host[dot+1:]
    return None if hostname in get_servers() else hostname

def add_server():
    hostname = _ask("Hostname")
    name = _ask("Server name", default=_infer_server_name(hostname))
    if not _check_name(name):
        msg("Invalid character {0} in server name '{1}'", _get_bad_chars(name)[0], name)
        return None, False
    if name in get_servers():
        msg("Server '{0}' already exists!", name)
        return None, False
    try:
        server = {}
        server["hostname"] = hostname
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
        _write_json(_get_path(DIR_SERVER, name), server)
        msg("Checking server configuration")
        test_connection(get_server(name), True)
        msg("Successfully created server '{0}'!", name)
    except (KeyboardInterrupt, SystemExit):
        raise
    except:
        msg("Error creating server {0}:\n{1}", name, traceback.format_exc())
        return None, False
    return name, True
