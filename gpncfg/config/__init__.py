#!/usr/bin/env python3
import logging
import os
import sys
from dataclasses import dataclass
from typing import List

import configargparse
from danoan.toml_dataclass import TomlDataClassIO

from ..logger import JsonFormatter

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
    password: str
    ecdsa: List[str]
    ed25519: List[str]
    rsa: List[str]


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
        self.options = None
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
            "--config-age",
            default=60 * 10,
            help="how long to keep config files in the output directory",
        )
        parser.add_argument(
            "--daemon",
            action="store_true",
            default=False,
            help="continually fetch data from nautobot and deploy devices",
        )
        parser.add_argument(
            "--dns-parent",
            help="combined with the nodename to assemble a device's fqdn. used to verify tls certs for the nvue api",
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
            "--graphql-timeout",
            default="240",
            help="how log to wait for the graphql query to complete before timing out",
        )
        parser.add_argument(
            "--limit",
            default=[],
            help="comma separated list of nautobot device ids. deploy workers are started only for those devices.",
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
            "--log-json-file",
            default=False,
            help="file to write json logs to",
        )
        parser.add_argument(
            "--motd",
            help="message of the day to be displayed on switch login",
            required=True,
        )
        parser.add_argument(
            "--nautobot-tenant",
            default=False,
            help="only generate configs for devices assigned to this tenant. uses the nautobot name, not the id",
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
            "--no-deploy",
            action="store_true",
            default=False,
            help="only generate and write configs, do not deploy them to devices",
        )
        parser.add_argument(
            "--nvue-pass",
            help="password for the deploy user to authenticate to the nvue api",
            required=True,
        )
        parser.add_argument(
            "--nvue-port",
            default=8765,
            help="what port the nvue api is listening on",
        )
        parser.add_argument(
            "-o",
            "--output-dir",
            # default="./generated-configs",
            help="where to output the configs",
            required=True,
        )
        parser.add_argument(
            "--populate-cache",
            action="store_true",
            default=False,
            help="only populate the cache, do not generate any configs",
        )
        parser.add_argument(
            "--prometheus-port",
            default=9753,
            help="port to use for prometheus metrics endpoint, only used in daemon mode",
        )
        parser.add_argument(
            "--rollback-timeout",
            help="number of minutes devices should wait for confirmation before rolling back their config",
            required=True,
        )
        parser.add_argument(
            "--session-log-dir",
            help="for deploy drivers that support this, write session logs to this directory",
            default=False,
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
        parser.add_argument(
            "--syslog-server",
            help="the syslog server for the devices",
        )
        parser.add_argument(
            "--use-cache",
            help="do not fetch new data from nautobot",
            action="store_true",
            default=False,
        )
        parser.add_argument(
            "--use-cache-file",
            help="do not fetch new data from nautobot and instead use this file as cache. implies --use-cache",
            default=False,
        )

        options = parser.parse_args()

        args = parser.get_source_to_settings_dict().get("command_line", {"": [[], []]})[
            ""
        ][1]

        refuse_secret_on_cli(args, "--nautobot-token")
        refuse_secret_on_cli(args, "--nvue-pass")
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
        logging.getLogger().setLevel(self.options.log_level)
        logging.getLogger("gql").setLevel(logging.WARNING)
        logging.getLogger("netmiko").setLevel(logging.INFO)
        logging.getLogger("paramiko").setLevel(logging.WARNING)
        if self.options.log_json_file:
            self.options.log_json_file = os.path.expanduser(self.options.log_json_file)
            logHandler = logging.FileHandler(self.options.log_json_file)
            logHandler.setFormatter(
                JsonFormatter(
                    fmt_dict={
                        "level": "levelname",
                        "message": "message",
                        "loggerName": "name",
                        "processName": "processName",
                        "processID": "process",
                        "threadName": "threadName",
                        "threadID": "thread",
                        "timestamp": "asctime",
                    }
                )
            )
            logging.getLogger().addHandler(logHandler)

        self.options.cache_dir = os.path.expanduser(self.options.cache_dir)
        self.options.deploy_key = os.path.expanduser(self.options.deploy_key)
        self.options.login_file = os.path.expanduser(self.options.login_file)

        with open(self.options.login_file, "r") as f:
            self.options.login = LoginInfo.read(f)

        has_deploy_user = False
        for user in self.options.login.user:
            if user["name"] == self.options.deploy_user:
                has_deploy_user = True
                break

        if not has_deploy_user:
            log.warning("deploy user not found in users list")

        if self.options.use_cache_file:
            self.options.use_cache = True

        if self.options.populate_cache and self.options.use_cache:
            log.fatal("cannot populate cache in offline mode")
            exit(1)

        if isinstance(self.options.limit, str):
            self.options.limit = self.options.limit.split(",")

        self.options.graphql_timeout = int(self.options.graphql_timeout)
        self.options.config_age = int(self.options.config_age)
