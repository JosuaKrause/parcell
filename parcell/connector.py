#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import division

import os
import sys
import math
import shutil
import logging
import argparse
import threading
from rpaths import PosixPath
from tej import RemoteQueue, QueueDoesntExist, JobNotFound, RemoteCommandFailure, JobAlreadyExists

import loading

def msg(message, *args, **kwargs):
    print(message.format(*args, **kwargs), file=sys.stdout)

def set_msg(m):
    global msg
    msg = m
    loading.set_msg(m)

def get_envs():
    return loading.get_envs()

def get_servers():
    return loading.get_servers()

def get_projects():
    return loading.get_projects()

def set_password_reuse(reuse_pw):
    loading.set_password_reuse(reuse_pw)

def init_passwords():
    loading.init_passwords()

def get_connector(project):
    with loading.MAIN_LOCK:
        if project not in Connector._ALL_CONNECTORS:
            Connector(project) # adds itself to the list
        return Connector._ALL_CONNECTORS[project]

class Connector(object):
    DIR_TEMP = "temp_files"
    SCRIPT_FILE = "_start"

    _ALL_CONNECTORS = {}

    def __init__(self, p):
        self._lock = threading.RLock()
        self._name = p
        self._job_number = 0
        project = loading.read_project(p)
        self._path_local, self._command, self._env, self._servers, self._s_conn = project
        self._rqs = dict([ (s, loading.get_remote(s)) for s in self._servers ])
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

    def get_servers_info(self):
        return [ {
            "server": s,
            "cpu": self.get_cpu(self._rqs[s]),
        } for s in self.get_servers() ]

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

    _STATUS = dict([
        (RemoteQueue.JOB_DONE, "done"),
        (RemoteQueue.JOB_RUNNING, "running"),
        (RemoteQueue.JOB_INCOMPLETE, "incomplete"),
        (RemoteQueue.JOB_CREATED, "created"),
        ("missing", "missing"),
        ("error", "error"),
    ])
    def get_all_jobs(self):

        def desc(s, j, info):
            if i["status"] == RemoteQueue.JOB_DONE:
                if "result" not in i: # FIXME: hack for tej without result in list
                    return self.get_job_status(s, j)[0]
                if int(i["result"]) != 0:
                    return Connector._STATUS["error"]
            return Connector._STATUS.get(i["status"], "?")

        return [ (s, j, desc(s, j, i)) for s in self.get_servers() for (j, i) in self.get_job_list(s) ]

    def get_job_list(self, s):
        prefix = "{0}_".format(self._name)
        try:
            rq = self._rqs[s]
            return [ ji for ji in rq.list() if ji[0].startswith(prefix) ]
        except QueueDoesntExist:
            return []

    def get_job_status(self, s, j):
        rq = self._rqs[s]
        try:
            status, _, result = rq.status(j)
            if status == RemoteQueue.JOB_DONE and int(result) != 0:
                status = "error"
        except JobNotFound:
            status = "missing"
            result = "?"
        except RemoteCommandFailure as rcf:
            status = "error"
            result = rcf.ret
        return Connector._STATUS.get(status, "?"), result

    def submit_job(self, s):
        with self._lock:
            rq = self._rqs[s]

            with open(os.path.join(self._path_local, Connector.SCRIPT_FILE), 'wb') as f:
                print("if [ -f ~/.bashrc ]; then\n" \
                      "  . ~/.bashrc\n" \
                      "fi", file=f)
                print(self._command, file=f)

            while True:
                try:
                    job_name = "{0}_{1}".format(self._name, self._job_number)
                    return rq.submit(job_name, self._path_local, Connector.SCRIPT_FILE)
                except JobAlreadyExists:
                    pass
                finally:
                    self._job_number += 1

    def delete_job(self, s, j):
        with self._lock:
            rq = self._rqs[s]
            try:
                rq.kill(j)
            except (RemoteCommandFailure, JobNotFound):
                pass
            try:
                rq.delete(j)
            except JobNotFound:
                pass
            path = str(PosixPath(Connector.DIR_TEMP) / s / j)
            if os.path.exists(path):
                shutil.rmtree(path)

    def get_job_files(self, s, j, rel_path):
        rq = self._rqs[s]
        status, path, result = rq.status(j)
        rel_path = PosixPath(rel_path)
        if rel_path.is_absolute:
            rel_path = PosixPath(".")
        res = rq.check_output("ls -p1t {0}".format(str(path / rel_path))).split("\n")
        if rel_path != ".":
            res.insert(0, "../")
        return res

    def get_job_file(self, s, j, req_file):
        rq = self._rqs[s]
        status, path, result = rq.status(j)
        path = PosixPath(Connector.DIR_TEMP) / s / j
        res = str(path / req_file)
        path_str = os.path.dirname(res)
        if not os.path.exists(path_str):
            os.makedirs(path_str)
        if not os.path.exists(res) or status == RemoteQueue.JOB_RUNNING:
            rq.download(j, [ req_file ], destination=path_str)
        return res

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parcell Connector')
    parser.add_argument('--reuse-pw', action='store_true', dest='reuse_pw', help="only ask for one password")
    parser.add_argument('-v', '--verbose', action='count', default=1, dest='verbosity', help="augments verbosity level")
    parser.add_argument('project', type=str, nargs='?', help="project file")
    args = parser.parse_args()

    levels = [ logging.CRITICAL, logging.WARNING, logging.INFO, logging.DEBUG ]
    logging.basicConfig(level=levels[min(args.verbosity, 3)])

    if not args.project:
        for p in loading.get_projects():
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
