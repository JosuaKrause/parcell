#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import division

import os
import sys
import math
import logging
import argparse
import threading
from rpaths import PosixPath
from tej import RemoteQueue, JobNotFound, RemoteCommandFailure, JobAlreadyExists

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
    SCRIPT_FILE = "_start"

    _ALL_CONNECTORS = {}

    def __init__(self, p):
        self._lock = threading.RLock()
        self._job_number = 0
        self._project = loading.get_project(p)
        self._rqs = dict([ (s.name, loading.get_remote(s)) for s in self._project["servers"] ])
        Connector._ALL_CONNECTORS[p] = self

    def get_path(self):
        return self._project.path_local

    def get_commands(self):
        return self._project.commands

    def get_env(self):
        return self._project["env"].name

    def _get_env(self, rq, chk):
        if len(chk) == 4:
            name, cmd, regex, line = chk
        else:
            name, cmd, regex, line, _ = chk
        output = rq.check_output(cmd)
        oarr = output.split("\n")
        if line >= len(oarr):
            raise ValueError("line {0} not in:\n{1}".format(line, oarr))
        m = regex.search(oarr[line])
        if m is None:
            raise ValueError("unexpected mismatch {0} not in:\n{1}".format(regex.pattern, oarr[line]))
        return name, m.group(1)

    def get_vital_value(self, rq, chk):
        name, c = self._get_env(rq, chk)
        asc = chk[4]
        if c:
            try:
                return name, float(c), asc
            except TypeError:
                pass
        return name, float('nan'), asc

    def get_vitals(self, rq):
        return [ self.get_vital_value(rq, b) for b in self._project["env"]["vital"] ]

    def get_servers(self):
        return [ s.name for s in self._project["servers"] ]

    def get_servers_info(self):
        return [ {
            "server": s,
            "vital": self.get_vital_value(self._rqs[s], self._project["env"]["vital"][0])[1],
        } for s in self.get_servers() ]

    def get_server_stats(self, s):
        server = self._project.servers[s]
        rq = self._rqs[s]
        return {
            "name": server["hostname"],
            "versions": [ self._get_env(rq, chk) for chk in self._project["env"]["versions"] ],
            "vitals": self.get_vitals(self._rqs[s]),
        }

    def get_all_vitals(self):
        return [ (s, self.get_vitals(self._rqs[s])) for s in self.get_servers() ]

    def get_best_server(self):
        servers = self.get_servers()
        if len(servers) < 2:
            return servers[0] if servers else None
        all_vitals = self.get_all_vitals()
        cur_ix = 0
        best_s = []
        best_num = float('nan')
        while len(best_s) < 2 and cur_ix < len(all_vitals[0][1]):
            for (s, cur) in all_vitals:
                _, num, asc = cur[cur_ix]
                if math.isnan(best_num):
                    best_s = [ s ]
                    best_num = num
                elif num == best_num:
                    best_s.append(s)
                else:
                    if asc:
                        if num < best_num:
                            best_s = [ s ]
                            best_num = num
                    else:
                        if num > best_num:
                            best_s = [ s ]
                            best_num = num
            cur_ix += 1
        return best_s[0] if len(best_s) > 0 else None

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
        prefix = "{0}_".format(self._project.name)
        rq = self._rqs[s]
        return [ ji for ji in loading.list_jobs(rq) if ji[0].startswith(prefix) ]

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

    def submit_job(self, s, cmd):
        if not cmd.strip():
            raise ValueError("cannot execute empty command: {0}".format(cmd))
        with self._lock:
            rq = self._rqs[s]
            path = self._project.path_local
            self._project.add_cmd(cmd)

            with open(os.path.join(path, Connector.SCRIPT_FILE), 'wb') as f:
                print(cmd, file=f)

            while True:
                try:
                    job_name = "{0}_{1}".format(self._project.name, self._job_number)
                    call = "sh -l ./{0}".format(Connector.SCRIPT_FILE)
                    return rq.submit(job_name, path, call)
                except JobAlreadyExists:
                    pass
                finally:
                    self._job_number += 1

    def delete_job(self, s, j):
        with self._lock:
            rq = self._rqs[s]
            loading.kill_job(rq, s, j)

    def delete_all_jobs(self):
        with self._lock:
            for (s, j, _) in self.get_all_jobs():
                self.delete_job(s, j)


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
        path = PosixPath(loading.DIR_TEMP) / s / j
        res = str(path / req_file)
        path_str = os.path.dirname(res)
        if not os.path.exists(path_str):
            os.makedirs(path_str)
        if not os.path.exists(res) or status == RemoteQueue.JOB_RUNNING:
            try:
                rq.download(j, [ req_file ], destination=path_str)
            except JobNotFound:
                return None
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
