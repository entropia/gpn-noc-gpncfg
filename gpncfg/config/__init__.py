#!/usr/bin/env python3
import logging
import os
import sys
from dataclasses import dataclass

import configargparse
import toml
from danoan.toml_dataclass import TomlDataClassIO

# REMEMBER: only WARNING and higher levels are shown until logging is fully set
# up later in `assemble`.
log = logging.getLogger(__name__)


@dataclass
class RootInfo(TomlDataClassIO):
    md5: str
    sha256: str
    sha512: str


@dataclass
class UserInfo(TomlDataClassIO):
    uid: int
    name: str
    ecdsa: [str]
    ed25519: [str]
    rsa: [str]


@dataclass
class LoginInfo(TomlDataClassIO):
    root: RootInfo
    user: str


def get_cache_path():
    if "XDG_CACHE_HOME" in os.environ:
        cache_home = os.environ["XDG_CACHE_HOME"]
    else:
        cache_home = os.path.join(os.environ["HOME"], ".cache")
    cache_path = os.path.join(cache_home, "gpncfg")

    return cache_path


def get_config_path(file):
    if "XDG_CONFIG_HOME" in os.environ:
        config_home = os.environ["XDG_CONFIG_HOME"]
    else:
        config_home = os.path.join(os.environ["HOME"], ".config")

    config_home = os.path.join(config_home, "gpncfg")

    return os.path.join(config_home, file)


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


class ConfigProvider:
    def __init__(self):
        self.config = ()

    def collect(self):
        config_path = get_config_path("gpncfg.toml")

        parser = configargparse.ArgumentParser(
            # personal config file overrides event config
            default_config_files=[get_eventtoml_path(), config_path],
            config_file_parser_class=configargparse.TomlConfigParser(["gpncfg"]),
        )

        parser.add_argument(
            "--cache-dir",
            default=get_cache_path(),
            help="directory in which to cache nautobot data",
        )
        parser.add_argument(
            "-c",
            "--config",
            help="path to the config file",
            is_config_file=True,
            # required=True,
        )
        parser.add_argument(
            "--autoupdate-interval",
            help="how frequently the devices try to update their configuration",
            required=True,
        )
        parser.add_argument(
            "--dry-deploy",
            action="store_true",
            default=False,
            help="generate configs and connect to devices but do not commit configs",
        )
        parser.add_argument(
            "--deploy-key",
            help="path to a private ssh key file which is used to log in to switches to deploy configs",
            required=True,
        )
        parser.add_argument(
            "--deploy-user",
            default="gpncfg",
            help="what user to authenticate as when deploying configs",
        )
        parser.add_argument(
            "--gateway",
            help="the default gateway for all devices",
            required=True,
        )
        parser.add_argument(
            "--login-file",
            default=get_config_path("login.toml"),
            help="path to the login file, which contains the root passwords and the user definitions",
        )
        parser.add_argument(
            "--log-level", default="INFO", help="verbosity of the logger"
        )
        parser.add_argument(
            "--motd",
            help="message of the day to be displayed on switch login",
            required=True,
        )
        parser.add_argument(
            "--nautobot-tenant",
            help="only generate configs for devices assigned to this tenant. uses the nautobot name, not the id",
            required=True,
        )
        parser.add_argument(
            "--nautobot-url", required=True, help="url to the nautobot instance"
        )
        parser.add_argument(
            "--nautobot-token",
            required=True,
            help="authorization token for the nautobot apis. as a secret, it must not be provided on the cli",
        )
        parser.add_argument(
            "--offline", help="run in offline mode", action="store_true"
        )
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
            "--populate-cache",
            action="store_true",
            default=False,
            help="only populate the cache, do not generate any configs",
        )
        parser.add_argument(
            "--rollback-timeout",
            help="number of minutes devices should wait for confirmation before rolling back their config",
            required=True,
        )
        parser.add_argument(
            "--snmp-community",
            help="what snmp community the devices shall join. as a secret, it must not be provided on the cli",
            required=True,
        )
        parser.add_argument(
            "--snmp-contact",
            help="the snmp contact address of the devices",
            required=True,
        )

        options = parser.parse_args()

        args = parser.get_source_to_settings_dict().get("command_line", {"": [[], []]})[
            ""
        ][1]

        refuse_secret_on_cli(args, "--nautobot-token")
        refuse_secret_on_cli(args, "--snmp-community")

        self.options = options

    def assemble(self):
        self.options.log_level = self.options.log_level.upper()
        try:
            self.options.log_level = getattr(logging, self.options.log_level)
        except AttributeError:
            log.error(
                "cannot configure invalid log level '{}'".format(self.options.log_level)
            )
            exit(1)
        logging.getLogger("gpncfg").setLevel(self.options.log_level)

        self.options.cache_dir = os.path.expanduser(self.options.cache_dir)
        self.options.deploy_key = os.path.expanduser(self.options.deploy_key)
        self.options.login_file = os.path.expanduser(self.options.login_file)

        with open(self.options.login_file, "r") as f:
            self.options.login = LoginInfo.read(f)
