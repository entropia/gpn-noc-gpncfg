#!/usr/bin/env python3
import logging
import os
import sys

import configargparse


def get_cache_path():
    if "XDG_CACHE_HOME" in os.environ:
        cache_home = os.environ["XDG_CACHE_HOME"]
    else:
        cache_home = os.path.join(os.environ["HOME"], ".cache")
    cache_path = os.path.join(cache_home, "gpncfg")

    return cache_path


def get_config_path():
    if "XDG_CONFIG_HOME" in os.environ:
        config_home = os.environ["XDG_CONFIG_HOME"]
    else:
        config_home = os.path.join(os.environ["HOME"], ".config")
    config_path = os.path.join(config_home, "gpncfg.cfg")

    return config_path


def assemble():
    config_path = get_config_path()

    parser = configargparse.ArgumentParser(
        default_config_files=[config_path],
    )

    parser.add_argument(
        "--cache-dir", default=get_cache_path(), help="where to store cached data"
    )
    parser.add_argument("--log-level", default="INFO", help="verbosity of the logger")
    parser.add_argument(
        "--netbox-url", required=True, help="url to the netbox instance"
    )
    parser.add_argument(
        "--netbox-token", required=True, help="authorization token for the netbox apis"
    )
    parser.add_argument("--offline", help="run in offline mode", action="store_true")
    parser.add_argument("-o", "--output-dir", help="where to output the configs")

    options = parser.parse_args()

    if (
        "--netbox-token"
        in parser.get_source_to_settings_dict().get("command_line", {"": [[], []]})[""][
            1
        ]
    ):
        print(
            "error: netbox-token found in cli args, refusing to cooperate. do not provide secrets via the command line. instead use the config file to specify secrets.",
            file=sys.stderr,
        )
        exit(1)

    options.cache_dir = os.path.expanduser(options.cache_dir)
    options.log_level = options.log_level.upper()
    try:
        options.log_level = getattr(logging, options.log_level)
    except AttributeError:
        print(
            "error: '%s' is not a valid log level" % options.log_level, file=sys.stderr
        )
        exit(1)

    return options
