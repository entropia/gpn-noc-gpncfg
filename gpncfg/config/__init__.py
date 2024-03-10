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
    config_path = os.path.join(config_home, "gpncfg.toml")

    return config_path


def get_eventtoml_path():
    cur_dir = os.path.dirname(__file__)
    epath = os.path.join(cur_dir, "event.toml")
    return epath


def refuse_secret_on_cli(args, name):
    if name in args:
        print(
            f"error: secret found in cli args, refusing to cooperate: '{name}'. do not provide secrets via the command line. instead use the config file to specify secrets.",
            file=sys.stderr,
        )
        exit(1)


def assemble():
    config_path = get_config_path()

    print(get_eventtoml_path())
    parser = configargparse.ArgumentParser(
        # personal config file overrides event config
        default_config_files=[get_eventtoml_path(), config_path],
        config_file_parser_class=configargparse.TomlConfigParser(["gpncfg"]),
    )

    parser.add_argument(
        "--cache-file",
        default=os.path.join(get_cache_path(), "netbox.json"),
        help="where to store cached data",
    )
    parser.add_argument(
        "--autoupdate-interval",
        help="how frequently the devices try to update their configuration",
        required=True,
    )
    parser.add_argument(
        "--default-hostname-prefix",
        help="use this prefix to generate device hostanmes if there is none configured in the netbox",
        required=True,
    )
    parser.add_argument(
        "--gateway",
        help="the default gateway for all devices",
        required=True,
    )
    parser.add_argument("--log-level", default="INFO", help="verbosity of the logger")
    parser.add_argument(
        "--motd",
        help="message of the day to be displayed on switch login",
        required=True,
    )
    parser.add_argument(
        "--netbox-tenant",
        help="only generate configs for devices assigned to this tenant. uses the netbox slug, not the id",
        required=True,
    )
    parser.add_argument(
        "--netbox-url", required=True, help="url to the netbox instance"
    )
    parser.add_argument(
        "--netbox-token", required=True, help="authorization token for the netbox apis"
    )
    parser.add_argument("--offline", help="run in offline mode", action="store_true")
    parser.add_argument(
        "-o",
        "--output-dir",
        # default="./generated-configs",
        help="where to output the configs",
        required=True,
    )
    parser.add_argument(
        "--override-fan-speed",
        help="the default fan speed of all the devices",
        required=True,
    )
    parser.add_argument(
        "--snmp-community",
        help="what snmp community the devices shall join",
        required=True,
    )
    parser.add_argument(
        "--snmp-contact",
        help="the snmp contact address of the devices",
        required=True,
    )
    parser.add_argument(
        "--snmp-location",
        help="the snmp location of the devices",
        required=True,
    )

    options = parser.parse_args()

    args = parser.get_source_to_settings_dict().get("command_line", {"": [[], []]})[""][
        1
    ]

    refuse_secret_on_cli(args, "--netbox-token")
    refuse_secret_on_cli(args, "--snmp-community")

    options.cache_file = os.path.expanduser(options.cache_file)
    options.log_level = options.log_level.upper()
    try:
        options.log_level = getattr(logging, options.log_level)
    except AttributeError:
        print(
            "error: '%s' is not a valid log level" % options.log_level, file=sys.stderr
        )
        exit(1)

    return options
