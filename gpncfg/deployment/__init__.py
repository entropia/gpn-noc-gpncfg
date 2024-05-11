import asyncio
import logging
import time

import netmiko

log = logging.getLogger(__name__)


def send_command(log, netcon, command, read_timeout=None):
    kwargs = dict()
    if read_timeout:
        kwargs["read_timeout"] = read_timeout

    log.debug(f"sending command `{command}`:")
    log.debug(netcon.send_command(command, **kwargs))


class DeployDispatcher:
    def __init__(self, cfg):
        self.cfg = cfg

    def deploy_device(self, cwc):
        device = cwc.context["device"]
        log.debug("deploying device {name} ({serial})".format(**device))

        usecase = device["usecase"]
        if (
            usecase == "access-switch_juniper_ex3300-24p"
            or usecase == "access-switch_juniper_ex3300-48p"
        ):
            return self.deploy_junos(cwc)
        else:
            log.error(
                "no deployment method for device {nodename} ({serial}) with usecase {usecase}".format(
                    **device
                )
            )
            return False

    def deploy_junos(self, cwc):
        device = cwc.context["device"]
        log = logging.getLogger(__name__).getChild("{nodename}".format(**device))
        log.debug("starting deployment")
        netcon = None
        for addr in device["addresses"]:
            try:
                netcon = netmiko.ConnectHandler(
                    device_type="juniper_junos",
                    host=device["addresses"][0],
                    username=self.cfg.deploy_user,
                    key_file=self.cfg.deploy_key,
                )
            except netmiko.exceptions.NetmikoTimeoutException:
                log.debug(f"failed to contact {addr}, trying next address if possible")
        if not netcon:
            log.error(
                "failed to deploy because addresses are unreachable {addresses}".format(
                    **device
                )
            )
            return False
        log.debug("connected, now uploading config")
        if not self.cfg.dry_deploy:
            netmiko.file_transfer(
                netcon,
                source_file=cwc.path,
                dest_file="gpncfg-upload.cfg",
                overwrite_file=True,
            )

        log.debug("config uploaded, entering configuration mode")
        log.debug(netcon.config_mode())
        log.debug("applying config")
        if not self.cfg.dry_deploy:
            send_command(log, netcon, "load override /var/tmp/gpncfg-upload.cfg")
        send_command(log, netcon, "show | compare")
        if not self.cfg.dry_deploy:
            send_command(log, netcon, "commit confirmed 10", read_timeout=120)
        log.info("config uploaded and commited with automatic rollback")
