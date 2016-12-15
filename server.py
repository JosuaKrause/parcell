#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import division

import os
import sys
import logging
import argparse

from connector import get_envs, get_servers, get_projects, get_connector, init_passwords, set_password_reuse, set_msg

from quick_server import create_server, msg, setup_restart
from quick_cache import QuickCache

set_msg(msg)

def get_server(addr, port, cache):
    server = create_server((addr, port))

    server.bind_path('/parcell/', 'www')
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
            "servers": get_servers() if project is None else get_connector(project).get_servers(),
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

    @server.json_worker(prefix + '/status')
    def json_status(args):
        project = args["project"]
        server = args["server"]
        job = args["job"]
        conn = get_connector(project)
        return {
            "project": project,
            "server": server,
            "job": job,
            "status": conn.get_job_status(server, job),
        }

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

if __name__ == '__main__':
    setup_restart()

    parser = argparse.ArgumentParser(description='Parcell Server')
    parser.add_argument('--reuse-pw', action='store_true', dest='reuse_pw', help="only ask for one password")
    parser.add_argument('--quota', default=4096, help="set cache quota")
    parser.add_argument('--ram-quota', default=1024, help="set RAM cache quota")
    parser.add_argument('-a', type=str, default="localhost", help="specifies the server address")
    parser.add_argument('-p', type=int, default=8080, help="specifies the server port")
    parser.add_argument('-v', '--verbose', action='count', default=1, dest='verbosity', help="augments verbosity level")
    args = parser.parse_args()

    levels = [ logging.CRITICAL, logging.WARNING, logging.INFO, logging.DEBUG ]
    logging.basicConfig(level=levels[min(args.verbosity, 3)])

    addr = args.a
    port = args.p
    cache_quota = args.quota
    ram_quota = args.ram_quota

    cache_temp = "tmp"
    if os.path.exists("cache_path.txt"):
        with open("cache_path.txt") as cp:
            cache_temp = cp.read().strip()

    msg("{0}", " ".join(sys.argv))
    msg("initializing passwords -- please type as prompted")
    set_password_reuse(args.reuse_pw)
    init_passwords()

    server = get_server(addr, port, QuickCache(quota=cache_quota, ram_quota=ram_quota, temp=cache_temp, warnings=msg))
    msg("starting server at {0}:{1}", addr if addr else 'localhost', port)
    server.serve_forever()
    msg("shutting down..")
    server.server_close()
