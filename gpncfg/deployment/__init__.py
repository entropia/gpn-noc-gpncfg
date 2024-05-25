import asyncio
import logging
import os
import queue
import sys
import time

import netmiko

log = logging.getLogger(__name__)


# like SystemExit and asyncio.exceptions.CancelledError, inherit from
# BaseException. This way, the shutdown can not be confused with an error.
class ShutdownCommencing(BaseException):
    pass


class IntangibleDeviceError(Exception):
    pass


class DeployDriver:
    def __init__(self, cfg, exit, queue, id):
        self.cfg = cfg
        self.exit = exit
        self.queue = queue
        self.id = id
        self.usecase = None
        self.log = logging.getLogger(__name__).getChild(f"worker#{id}")

    def honor_exit(self):
        if self.exit.is_set():
            self.log.debug("honoring shutdown request")
            raise ShutdownCommencing()

    def assert_prop(self, device, name):
        old = self.__getattribute__(name)
        if not old:
            return
        new = device[name]
        if new != old:
            raise IntangibleDeviceError(
                f"my {name} changed from '{old}' to '{new}', refusing to continue"
            )

    def worker_loop(self):
        cwc = None
        while True:
            # wait for new updates to come in. if there are multiple, ignore the latest
            self.log.debug("waiting for new config")
            while True:
                try:
                    cwc = self.queue.get(timeout=1)
                    break
                except (TimeoutError, queue.Empty):
                    pass
                finally:
                    self.honor_exit()

            # check if there are more up to date configs
            for i in range(sys.maxsize):
                try:
                    cwc = self.queue.get_nowait()
                except queue.Empty:
                    self.log.debug(f"skipped {i} outdated configs")
                    break

            self.log.debug(f"received new config: {cwc}")

            self.assert_prop(cwc.context["device"], "usecase")
            # assert self.usecase == cwc.context["device"]["usecase"]
            # assert self.id == cwc.context["device"]["id"]

            serial = cwc.context["device"]["serial"]
            self.log.debug("writing config for serial " + serial)
            cwc.path = os.path.abspath(
                os.path.join(self.cfg.output_dir, "config-" + serial)
            )
            with open(cwc.path, "w+") as file:
                print(cwc.config, file=file)

            if self.cfg.no_deploy:
                self.log.debug("as commanded, gpncfg shall not deploy to devices")
            else:
                self.deploy(cwc)

            if not self.cfg.daemon:
                return True


class DeployJunos(DeployDriver):
    def netcon_cmd(self, netcon, command, **kwargs):
        self.honor_exit()
        netcon.send_command(command, **kwargs)

    def netcon_cfg_mode(self, netcon):
        self.honor_exit()
        netcon.config_mode()

    def connect_junos(self, device):
        self.honor_exit()

        for addr in device["addresses"]:
            try:
                self.log.debug(f"attempting to connect to address {addr}")
                session_log = None
                if self.cfg.session_log_dir:
                    os.makedirs(self.cfg.session_log_dir, exist_ok=True)
                    session_log = os.path.join(
                        self.cfg.session_log_dir, "{id}.txt".format(**device)
                    )
                return netmiko.ConnectHandler(
                    device_type="juniper_junos",
                    host=addr,
                    username=self.cfg.deploy_user,
                    key_file=self.cfg.deploy_key,
                    session_log=session_log,
                    session_log_file_mode="append",
                )
            except netmiko.exceptions.NetmikoTimeoutException:
                self.log.debug(
                    f"failed to contact {addr}, trying next address if possible"
                )
        return None

    def deploy(self, cwc):
        device = cwc.context["device"]
        self.log.debug("starting deployment")

        netcon = self.connect_junos(device)
        if not netcon:
            self.log.error(
                "failed to deploy because addresses are unreachable {addresses}".format(
                    **device
                )
            )
            return False

        self.log.debug("connected, now uploading config")
        if not self.cfg.dry_deploy:
            self.honor_exit()
            netmiko.file_transfer(
                netcon,
                source_file=cwc.path,
                dest_file="gpncfg-upload.cfg",
                overwrite_file=True,
            )

        self.log.debug("config was successfuly uploaded, applying configuration")
        self.netcon_cfg_mode(netcon)

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

        netcon.disconnect()

        netcon = self.connect_junos(device)
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


class DeployCumuls(DeployDriver):
    def deploy(self, cwc):
        name = "config-{nodename}".format(**cwc.context["device"])
        self.log.debug("writing config for " + name)
        cwc.path = os.path.abspath(os.path.join(self.cfg.output_dir, name))


DRIVERS = {
    "access-switch_juniper_ex3300-24p": DeployJunos,
    "access-switch_juniper_ex3300-48p": DeployJunos,
    "core-switch_mellanox_sn2410": DeployCumuls,
}
