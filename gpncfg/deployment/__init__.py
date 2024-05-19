import asyncio
import logging
import time

import netmiko

log = logging.getLogger(__name__)


# like SystemExit and asyncio.exceptions.CancelledError, inherit from
# BaseException. This way, the shutdown can not be confused with an error.
class ShutdownCommencing(BaseException):
    pass


class DeployDispatcher:
    def __init__(self, cfg, exit):
        self.cfg = cfg
        self.exit = exit

    def deploy_device(self, cwc):
        device = cwc.context["device"]
        usecase = device["usecase"]

        log = logging.getLogger(__name__).getChild("deploy#{nodename}".format(**device))
        log.debug("deploying device {name} ({serial})".format(**device))

        if (
            usecase == "access-switch_juniper_ex3300-24p"
            or usecase == "access-switch_juniper_ex3300-48p"
        ):
            return DeployJunos(self.cfg, self.exit, log, cwc).deploy()
        else:
            self.log.error(f"no deploymen method for {usecase}")
            return False


class DeployJunos:
    def __init__(self, cfg, exit, log, cwc):
        self.cfg = cfg
        self.exit = exit
        self.log = log
        self.cwc = cwc
        self.device = cwc.context["device"]

    def honor_exit(self):
        if self.exit.is_set():
            self.log.debug("honoring shutdown request")
            raise ShutdownCommencing()

    def netcon_cmd(self, netcon, command, **kwargs):
        self.honor_exit()
        self.log.debug(f"sending command `{command}`:")
        self.log.debug(netcon.send_command(command, **kwargs))

    def netcon_cfg_mode(self, netcon):
        self.honor_exit()
        self.log.debug("entering configuration mode")
        self.log.debug(netcon.config_mode())

    def connect_junos(self):
        self.honor_exit()

        for addr in self.device["addresses"]:
            try:
                self.log.debug(f"attempting to connect to address {addr}")
                return netmiko.ConnectHandler(
                    device_type="juniper_junos",
                    host=addr,
                    username=self.cfg.deploy_user,
                    key_file=self.cfg.deploy_key,
                )
            except netmiko.exceptions.NetmikoTimeoutException:
                self.log.debug(
                    f"failed to contact {addr}, trying next address if possible"
                )
        return None

    def deploy(self):
        self.log.debug("starting deployment")

        netcon = self.connect_junos()
        if not netcon:
            self.log.error(
                "failed to deploy because addresses are unreachable {addresses}".format(
                    **self.device
                )
            )
            return False

        self.log.debug("connected, now uploading config")
        if not self.cfg.dry_deploy:
            self.honor_exit()
            netmiko.file_transfer(
                netcon,
                source_file=self.cwc.path,
                dest_file="gpncfg-upload.cfg",
                overwrite_file=True,
            )

        self.log.debug("config uploaded, entering configuration mode")
        self.log.debug(self.netcon_cfg_mode(netcon))

        self.log.debug("applying config")
        if not self.cfg.dry_deploy:
            self.netcon_cmd(netcon, "load override /var/tmp/gpncfg-upload.cfg")
        self.netcon_cmd(netcon, "show | compare")
        if not self.cfg.dry_deploy:
            self.netcon_cmd(
                netcon,
                "commit confirmed {}".format(self.cfg.rollback_timeout),
                read_timeout=120,
            )
        self.log.info("config uploaded and commited, now reconnecting to confirm")

        self.log.debug("disconnecting")
        netcon.disconnect()

        netcon = self.connect_junos()
        self.log.debug("sucessfuly reconnected")
        if not netcon:
            self.log.error(
                "failed connecting to commit configuration, no more addresses to try"
            )
            return False

        self.log.debug("device is still reachable, committing configuration")
        self.netcon_cfg_mode(netcon)
        if not self.cfg.dry_deploy:
            self.netcon_cmd(netcon, "commit", read_timeout=120)

        self.log.debug("all done, disconnecting")
        netcon.disconnect()
        self.log.info("config fully deployed")
