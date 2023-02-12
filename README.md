# unitconfig

More convenient management of nginx-unit than socket+http

## install

A good choice is to place the script `unitconfig.py` (or symlink) in `/usr/local/bin` (e.g. `/usr/local/bin/unitconfig`),
in most linux distribution, it is included to system paths.

## help

usage: unitconfig.py [-h] [--sock SOCK] [--verbose {0,1,2}] {applyconfig,restart,show} ...

More convenient management of nginx-unit than socket+http

options:
  -h, --help            show this help message and exit
  --sock SOCK           nginx-unit socket path (defaulf try to find)
  --verbose {0,1,2}     0 - silent, 1 - normal, 2 - debug

commands:
  see <command> --help

  {applyconfig,restart,show}
                        commands
    applyconfig         apply file configs
    restart             restart app
    show                show current config

### applyconfig

usage: unitconfig.py applyconfig [-h] [--configs CONFIGS_PATH]

options:
  -h, --help            show this help message and exit
  --configs CONFIGS_PATH
                        app config files dir path (defaulf /etc/nginx-unit.d)

### restart

usage: unitconfig.py restart [-h] app_name

positional arguments:
  app_name    app name

options:
  -h, --help  show this help message and exit

### show                  

usage: unitconfig.py show [-h] [path]

positional arguments:
  path        config url/path (defaulf /config)

options:
  -h, --help  show this help message and exit
