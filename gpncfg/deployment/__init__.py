import asyncio
import logging
import threading
import time

import netmiko

log = logging.getLogger(__name__)


# like SystemExit and asyncio.exceptions.CancelledError, inherit from
# BaseException. This way, the shutdown can not be confused with an error.
class ShutdownCommencing(BaseException):
    pass


def netcon_cmd(log, netcon, command, **kwargs):
    DeployDispatcher.honor_exit(log)
    log.debug(f"sending command `{command}`:")
    log.debug(netcon.send_command(command, **kwargs))


def netcon_cfg_mode(log, netcon):
    DeployDispatcher.honor_exit(log)
    log.debug("entering configuration mode")
    # log.debug(netcon_cfg_mode(log, netcon))
    log.debug(netcon.config_mode())


class DeployDispatcher:
    lock = threading.Event()

    @classmethod
    def shutdown(cls):
        log.info(
            "dispatcher received shutdown request, workers may take up to a minute to cleanly exit."
        )
        cls.lock.set()

    @classmethod
    def honor_exit(cls, log=None):
        if cls.lock.is_set():
            if log:
                log.debug("honoring shutdown request")
            raise ShutdownCommencing()

    def __init__(self, cfg):
        self.cfg = cfg

    def deploy_device(self, cwc):
        device = cwc.context["device"]
        usecase = device["usecase"]

        log = logging.getLogger(__name__).getChild("deploy#{nodename}".format(**device))
        log.debug("deploying device {name} ({serial})".format(**device))

        if (
            usecase == "access-switch_juniper_ex3300-24p"
            or usecase == "access-switch_juniper_ex3300-48p"
        ):
            return self.deploy_junos(log, cwc)
        else:
            log.error(f"no deploymen method for {usecase}")
            return False

    def connect_junos(self, log, device):
        DeployDispatcher.honor_exit(log)

        for addr in device["addresses"]:
            try:
                log.debug(f"attempting to connect to address {addr}")
                return netmiko.ConnectHandler(
                    device_type="juniper_junos",
                    host=device["addresses"][0],
                    username=self.cfg.deploy_user,
                    key_file=self.cfg.deploy_key,
                )
            except netmiko.exceptions.NetmikoTimeoutException:
                log.debug(f"failed to contact {addr}, trying next address if possible")
        return None

    def deploy_junos(self, log, cwc):
        device = cwc.context["device"]

        log.debug("starting deployment")

        netcon = self.connect_junos(log, device)
        if not netcon:
            log.error(
                "failed to deploy because addresses are unreachable {addresses}".format(
                    **device
                )
            )
            return False

        log.debug("connected, now uploading config")
        if not self.cfg.dry_deploy:
            DeployDispatcher.honor_exit(log)
            netmiko.file_transfer(
                netcon,
                source_file=cwc.path,
                dest_file="gpncfg-upload.cfg",
                overwrite_file=True,
            )

        log.debug("config uploaded, entering configuration mode")
        log.debug(netcon_cfg_mode(log, netcon))

        log.debug("applying config")
        if not self.cfg.dry_deploy:
            netcon_cmd(log, netcon, "load override /var/tmp/gpncfg-upload.cfg")
        netcon_cmd(log, netcon, "show | compare")
        if not self.cfg.dry_deploy:
            netcon_cmd(
                log,
                netcon,
                "commit confirmed {}".format(self.cfg.rollback_timeout),
                read_timeout=120,
            )
        log.info("config uploaded and commited, now reconnecting to confirm")

        log.debug("disconnecting")
        netcon.disconnect()

        netcon = self.connect_junos(log, device)
        log.debug("sucessfuly reconnected")
        if not netcon:
            log.error(
                "failed connecting to commit configuration, no more addresses to try"
            )
            return False

        log.debug("device is still reachable, committing configuration")
        netcon_cfg_mode(log, netcon)
        if not self.cfg.dry_deploy:
            netcon_cmd(log, netcon, "commit", read_timeout=120)

        log.debug("all done, disconnecting")
        netcon.disconnect()
        log.info("config fully deployed")
