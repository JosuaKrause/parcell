#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import division

import os
import sys
import time
import threading
import webbrowser

from connector import get_envs, get_servers, get_projects, get_connector, init_passwords, set_password_reuse, set_msg

from quick_server import create_server, msg, setup_restart, has_been_restarted, is_original
from quick_cache import QuickCache

set_msg(msg)

PARCEL_MNT = '/parcell/'
def get_server(addr, port, cache):
    server = create_server((addr, port))

    server.bind_path(PARCEL_MNT, os.path.join(os.path.dirname(__file__), 'www'))
    prefix = '/parcell'

    server.directory_listing = False
    server.add_default_white_list()
    server.link_empty_favicon_fallback()

    server.suppress_noise = True
    server.report_slow_requests = True

    server.link_worker_js(prefix + '/js/worker.js')
    server.cache = cache

    def optional(key, args, default=None):
        return args[key] if key in args else default

    def optional_bool(key, args, default):
        return bool(args[key]) if key in args else default

    @server.json_get(prefix + '/envs')
    def json_get_envs(req, args):
        return {
            "envs": get_envs(),
        }

    @server.json_get(prefix + '/projects')
    def json_get_projects(req, args):
        return {
            "projects": get_projects(),
        }

    @server.json_get(prefix + '/servers')
    def json_get_servers(req, args):
        project = optional("project", args["query"])
        return {
            "servers": [ {
                "server": s,
                "cpu": float('nan'),
            } for s in get_servers_info() ] if project is None else get_connector(project).get_servers_info(),
        }

    @server.json_get(prefix + '/project_info')
    def json_get_project_info(req, args):
        project = args["query"]["project"]
        conn = get_connector(project)
        return {
            "project": project,
            "path": conn.get_path(),
            "command": conn.get_command(),
            "env": conn.get_env(),
        }

    @server.json_worker(prefix + '/stats')
    def json_status(args):
        project = args["project"]
        server = args["server"]
        conn = get_connector(project)
        return {
            "project": project,
            "server": server,
            "stats": conn.get_server_stats(server),
        }

    @server.json_worker(prefix + '/best_server')
    def json_best_server(args):
        project = args["project"]
        conn = get_connector(project)
        return {
            "project": project,
            "server": conn.get_best_server(),
        }

    @server.json_worker(prefix + '/start')
    def json_start(args):
        project = args["project"]
        server = args["server"]
        conn = get_connector(project)
        return {
            "project": project,
            "server": server,
            "job": conn.submit_job(server),
        }

    @server.json_worker(prefix + '/jobs')
    def json_jobs(args):
        project = args["project"]
        conn = get_connector(project)
        return {
            "project": project,
            "jobs": conn.get_all_jobs(),
        }

    @server.json_worker(prefix + '/kill_job')
    def json_jobs(args):
        project = args["project"]
        server = args["server"]
        job = args["job"]
        conn = get_connector(project)
        conn.delete_job(server, job)
        return {
            "project": project,
            "server": server,
            "job": job,
        }

    @server.json_worker(prefix + '/status')
    def json_status(args):
        project = args["project"]
        server = args["server"]
        job = args["job"]
        conn = get_connector(project)
        status, result = conn.get_job_status(server, job)
        return {
            "project": project,
            "server": server,
            "job": job,
            "status": status,
            "result": result,
        }

    @server.json_worker(prefix + '/ls')
    def json_status(args):
        project = args["project"]
        server = args["server"]
        job = args["job"]
        path = args["path"]
        conn = get_connector(project)
        return {
            "project": project,
            "server": server,
            "job": job,
            "path": path,
            "files": conn.get_job_files(server, job, path),
        }

    @server.text_get(prefix + '/file')
    def text_get(req, args):
        args = args["query"]
        project = args["project"]
        server = args["server"]
        job = args["job"]
        req_file = args["file"]
        conn = get_connector(project)
        with open(conn.get_job_file(server, job, req_file), 'rb') as f:
            return f.read()

    def complete_cache_clear(args, text):
        if args:
            return []
        return [ section for section in cache.list_sections() if section.startswith(text) ]

    @server.cmd(complete=complete_cache_clear)
    def cache_clear(args):
        if len(args) > 1:
          msg("too many extra arguments! expected one got {0}", ' '.join(args))
          return
        msg("clear {0}cache{1}{2}", "" if args else "all ", " " if args else "s", args[0] if args else "")
        cache.clean_cache(args[0] if args else None)

    return server

def is_child():
    return not is_original()

def enable_restart():
    setup_restart()

def start_server(addr, port, cache_quota, ram_quota, reuse_pw):
    cache_temp = "tmp"
    if os.path.exists("cache_path.txt"):
        with open("cache_path.txt") as cp:
            cache_temp = cp.read().strip()

    msg("{0}", " ".join(sys.argv))
    msg("initializing passwords -- please type as prompted")
    set_password_reuse(reuse_pw)
    init_passwords()
    msg("initializing passwords -- done")

    server = get_server(addr, port, QuickCache(quota=cache_quota, ram_quota=ram_quota, temp=cache_temp, warnings=msg))
    urlstr = "http://{0}:{1}{2}".format(addr if addr else 'localhost', port, PARCEL_MNT)

    def browse():
        time.sleep(1)
        msg("browsing to {0}", urlstr)
        webbrowser.open(urlstr, new=0, autoraise=True)

    if not has_been_restarted():
        t = threading.Thread(target=browse, name="Browser")
        t.daemon = True
        t.start()
    else:
        msg("please browse to {0}", urlstr)

    msg("starting web interface..")
    server.serve_forever()
    msg("shutting down..")
    server.server_close()
