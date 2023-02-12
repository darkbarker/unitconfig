#!/usr/bin/python3

# version: 2023-02-12

import argparse
import json
import os
import re
import socket
import stat
from typing import Tuple


DEFAULT_CONFIGS_PATH = "/etc/nginx-unit.d"
sock_path = None
DEFAULT_SHOW_PATH = "/config"


def command_applyconfig(args):
    if not os.path.isdir(args.configs_path):
        exit("config files path \"%s\" dont exist or isnt directory" % args.configs_path)
    do_apply_config(args.configs_path)


def command_restart(args):
    app_restart(args.app_name)


def command_show(args):
    show_config(args.path or DEFAULT_SHOW_PATH)


parser_0 = argparse.ArgumentParser(description="More convenient management of nginx-unit than socket+http")
parser_0.add_argument("--sock", help="nginx-unit socket path (defaulf try to find)")
parser_0.add_argument("--verbose", help="0 - silent, 1 - normal (default), 2 - debug", type=int, choices=[0, 1, 2], default=1)
subparsers = parser_0.add_subparsers(help="commands", title="commands", description="see <command> --help")
# applyconfig [--configs] [--sock]
parser_1 = subparsers.add_parser("applyconfig", help="apply file configs")
parser_1.add_argument("--configs", dest="configs_path", default=DEFAULT_CONFIGS_PATH, help="app config files dir path (defaulf %s)" % DEFAULT_CONFIGS_PATH)
parser_1.set_defaults(func=command_applyconfig)
# restart app_name [--sock]
parser_2 = subparsers.add_parser("restart", help="restart app")
parser_2.add_argument("app_name", help="app name")
parser_2.set_defaults(func=command_restart)
# show [path] [--sock]
parser_3 = subparsers.add_parser("show", help="show current config")
parser_3.add_argument("path", help="config url/path (defaulf %s)" % DEFAULT_SHOW_PATH, nargs="?")
parser_3.set_defaults(func=command_show)
args = parser_0.parse_args()


SOCK_F = [
    "/var/run/unit/control.sock",  # from docs
    "/run/nginx-unit.control.sock",  # arch aur
    "/run/control.unit.sock",  # debian
]


def issock(path):
    """Test whether a path is a socket file (based on the os.path.isxxx)"""
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return False
    return stat.S_ISSOCK(st.st_mode)


if args.sock:
    sock_path = args.sock
    if not issock(sock_path):
        exit("sock path \"%s\" dont exist or isnt socket" % sock_path)
else:
    for f in SOCK_F:
        if issock(f):
            sock_path = f
            break
    else:
        exit("sock path not found or isnt socket (try %s)" % (", ".join(SOCK_F)))


# print from verbose_level
def _print(verbose_level: int, value: str):
    if args.verbose >= verbose_level:
        print(value)


def _str_unique(param_name, file_data, total_data):
    if param_name in total_data and total_data[param_name] != file_data:  # if duplicate (but: duplicate the same is ok)
        exit("error file config: config key \"%s\" repeats in different config (%s vs %S)" % (param_name, total_data[param_name], file_data))
    total_data[param_name] = file_data


def _dict_unique_key(param_name, file_data, total_data):
    if param_name not in total_data:
        total_data[param_name] = {}
    for k, v in file_data.items():
        if k in total_data[param_name]:
            exit("error file config: config key \"%s/%s\" repeats in different config" % (param_name, k))
        total_data[param_name][k] = v


def _list_append(param_name, file_data, total_data):
    if param_name not in total_data:
        total_data[param_name] = []
    total_data[param_name] += file_data


def __dict_settings_http(param_name, file_data_settings_http, total_data_settings_http):
    for k, v in file_data_settings_http.items():
        if k not in total_data_settings_http:
            total_data_settings_http[k] = v
        else:
            if k in ["header_read_timeout", "body_read_timeout", "send_timeout", "idle_timeout", "max_body_size"]:
                total_data_settings_http[k] = max(total_data_settings_http[k], v)
            elif k in ["discard_unsafe_fields", "static"]:  # union of "static" can be realized in future
                exit("error file config: config key \"%s/%s\" repeats in different config" % (param_name, k))


def _dict_settings(param_name, file_data, total_data):
    if param_name not in total_data:
        total_data[param_name] = {}
    for k_sett, v_sett in file_data.items():
        if k_sett == "http":
            if "http" not in total_data[param_name]:
                total_data[param_name]["http"] = {}
            __dict_settings_http("%s/http" % param_name, v_sett, total_data[param_name]["http"])
        else:
            exit("error file config: config key \"%s/%s\" isnt supported" % (param_name, k_sett))


# config schema (type, merge func, depth of atomic PUT)
SCHEMA_CONFIG_KEYS = {
    "settings": (dict, _dict_settings, 0),
    "listeners": (dict, _dict_unique_key, 1),
    "routes": (list, _list_append, 0),
    "applications": (dict, _dict_unique_key, 1),
    "upstreams": (dict, _dict_unique_key, 1),
    "access_log": (str, _str_unique, 0),
}


# check, read and merge json-files config
def get_filesconfig(configs_path) -> dict:
    _print(2, "get files config (%s)..." % configs_path)
    filesconfig = {}
    for fn in sorted(os.listdir(configs_path)):  # sorted is for unambiguity
        fna = os.path.join(configs_path, fn)
        with open(fna, "rb") as f:
            try:
                fdata = json.load(f)
            except Exception as e:
                exit("error load file config \"%s\": %s" % (fna, repr(e)))
            if not isinstance(fdata, dict):
                exit("error file config \"%s\": json is not dict" % (fna))
            for conf_k, conf_v in fdata.items():
                if conf_k not in SCHEMA_CONFIG_KEYS:
                    exit("error file config \"%s\": config key \"%s\" unknown" % (fna, conf_k))
                c_type, c_func_merge, _ = SCHEMA_CONFIG_KEYS[conf_k]
                if not isinstance(conf_v, c_type):
                    exit("error file config \"%s\": config key \"%s\" is type %s, not %s" % (fna, conf_k, type(conf_v), c_type))
                c_func_merge(conf_k, conf_v, filesconfig)
    return filesconfig


# take current unit config
# curl --unix-socket /run/control.unit.sock http://localhost/config
def get_serverconfig() -> dict:
    _print(2, "get server config...")
    return json_request("GET", "/config")


RE_HTTP_FIRST = re.compile("HTTP/[\d\.]+\s+(\d+)\s+")


def http_request(http_method: str, http_path: str, data: str=None) -> Tuple[int, str]:
    _print(2, f"http {http_method} {http_path}...")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        _print(2, f"http connect {sock_path}...")
        client.connect(sock_path)
        http_request = "%s %s HTTP/1.0\nHost: none\nConnection: close\n\n%s" % (http_method, http_path, data or "")
        _print(2, "http client send...")
        client.sendall(http_request.encode("utf-8"))
        data = bytearray()
        _print(2, "http client recv...")
        while True:
            part = client.recv(4096)
            if not part:
                break
            data.extend(part)
    data = data.decode("utf-8")
    _print(2, f"http receive {len(data)} bytes")
    # HTTP/1.1 200 OK
    # HTTP/1.1 404 Not Found
    # {
    # "error": "Value doesn't exist."
    # }
    m = RE_HTTP_FIRST.search(data)
    if not m:
        exit("error http response %s %s? %s" % (http_method, http_path, data))
    http_code = int(m.group(1))
    body_idx = data.find("\r\n\r\n")
    _print(2, "http code: %d" % http_code)
    return http_code, data[body_idx + 4:]


def json_request(http_method: str, http_path: str, data=None):
    if data is not None:
        data = json.dumps(data)
    code, body = http_request(http_method, http_path, data)
    if code != 200:
        exit("error http response %s %s: http code is %s: %s" % (http_method, http_path, code, body))
    return json.loads(body)


def do_apply_config(configs_path):
    server_config = get_serverconfig()
    files_config = get_filesconfig(configs_path)

    _print(2, "apply config...")
    for files_config_k, files_config_v in files_config.items():
        _, _, c_depth = SCHEMA_CONFIG_KEYS[files_config_k]
        if c_depth == 0:  # is 1st level config
            if files_config_v != server_config.get(files_config_k, None):
                _print(1, "update %s" % files_config_k)
                json_request("PUT", "/config/%s" % files_config_k, files_config_v)
            else:
                _print(1, "not changed %s" % files_config_k)
            server_config.pop(files_config_k, None)
        elif c_depth == 1:  # is 2nd level config (always dict)
            for files_config_k2, files_config_v2 in files_config_v.items():
                if files_config_v2 != server_config.get(files_config_k, {}).get(files_config_k2, None):
                    if files_config_k not in server_config:
                        _print(1, "add %s/*" % (files_config_k))
                        json_request("PUT", "/config/%s" % (files_config_k), {})
                    _print(1, "update %s/%s" % (files_config_k, files_config_k2))
                    json_request("PUT", "/config/%s/%s" % (files_config_k, files_config_k2), files_config_v2)
                else:
                    _print(1, "not changed %s/%s" % (files_config_k, files_config_k2))
                if files_config_k in server_config:
                    server_config[files_config_k].pop(files_config_k2, None)

    # deleting from the server thing is missing for file-configs
    for server_config_k, server_config_v in server_config.items():
        _, _, c_depth = SCHEMA_CONFIG_KEYS[server_config_k]
        if c_depth == 0:  # is 1st level config
            _print(1, "delete %s" % server_config_k)
            json_request("DELETE", "/config/%s" % server_config_k)
        elif c_depth == 1:  # is 2nd level config (always dict)
            for server_config_k2, _server_config_v2 in server_config_v.items():
                _print(1, "delete %s/%s" % (server_config_k, server_config_k2))
                json_request("DELETE", "/config/%s/%s" % (server_config_k, server_config_k2))

    _print(2, "ok apply config")


# curl -X GET --unix-socket /path/to/control.unit.sock http://localhost/control/applications/app_name/restart
# {"error": "Value doesn't exist."}
# {"success": "Ok"}
def app_restart(app_name):
    _print(1, "restart %s..." % app_name)
    repl = json_request("GET", "/control/applications/%s/restart" % app_name)
    _print(1, "restart-success: %s" % repl.get("success", "?"))


# print config
def show_config(path):
    print(json.dumps(json_request("GET", path), indent=2, ensure_ascii=False))


# apply command func
args.func(args)
