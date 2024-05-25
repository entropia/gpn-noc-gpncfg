import asyncio
import json
import logging
import os
import queue
import sys
import time
from pprint import pprint

import netmiko
import requests
from requests_toolbelt.adapters.host_header_ssl import HostHeaderSSLAdapter

log = logging.getLogger(__name__)

# all nvue trainsitions that are valid
NT_VALID = {
    "applied",
    "applied_and_saved",
    "apply",
    "apply_error",
    "apply_fail",
    "auto_save",
    "auto_saving",
    "ays",
    "ays_fail",
    "ays_no",
    "ays_yes",
    "checked",
    "checking",
    "confirm",
    "confirm_fail",
    "confirm_no",
    "confirm_yes",
    "detached",
    "ignore_fail",
    "ignore_fail_no",
    "ignore_fail_yes",
    "inactive",
    "invalid",
    "pending",
    "ready",
    "ready_error",
    "readying",
    "reloaded",
    "reloading",
    "verified",
    "verify_error",
    "verifying",
}
# nvue states that indicate the revision is waiting on other revisions to be handled
NT_WAIT_FOR_TURN = {
    "apply",
}
# nvue states that indicate the device is preprocessing a new revision
NT_PREPROCESS = {
    "checked",
    "checking",
    "pending",
    "ready",
    "readying",
    "verified",
    "verifying",
}
# nvue states that indicate the device is reloading
NT_RELOADING = {
    "reloading",
    "reloaded",
}
# nvue states that indicate the device is waiting for a confirm
NT_CONFIRM = {
    "confirm",
}
# nvue states that indicate the revision has been applied successfully
NT_APPLIED = {
    "applied",
    "applied_and_saved",
    "auto_save",
}
# nvue states that indicate the revision has failed to apply
NT_FAIL = {
    "apply_error",
    "apply_fail",
    "ays_fail",
    "confirm_fail",
    "invalid",
    "ready_error",
    "verify_error",
}
# nvue states that indicate that the revision is in the process of being activated
NT_BLOCKING = {
    "apply",
    "ays",
    "ays_no",
    "ays_yes",
    "confirm",
    "confirm_no",
    "confirm_yes",
    "detached",
    "ignore_fail",
    "ignore_fail_no",
    "ignore_fail_yes",
    "ready",
    "ready_error",
    "readying",
    "reloaded",
    "reloading",
    "verify_error",
    "verifying",
}


# like SystemExit and asyncio.exceptions.CancelledError, inherit from
# BaseException. This way, the shutdown can not be confused with an error.
class ShutdownCommencing(BaseException):
    pass


class IntangibleDeviceError(Exception):
    pass


class UnknownStateError(Exception):
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
        addrs = []
        addrs.extend(device["addresses"][4])
        addrs.extend(device["addresses"][6])
        for addr in addrs:
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeout = int(self.cfg.rollback_timeout) * 60

    def wait_for_state(self, session, url, good, target, timeout=60):
        self.log.debug(
            f"waiting {timeout} seconds for revision to change to state {target} or to stop being {good}"
        )
        self.honor_exit()

        start = time.time()
        while True:
            try:
                res = session.get(url)
                state = res.json()["state"]
                self.log.debug(f"received {res} ({state})")
                if state not in NT_VALID:
                    raise UnknownStateError(
                        f"nvue api returned unknown state for revision {rev}: '{state}'"
                    )
                elif state in target:
                    self.log.debug(f"reached target state {state}")
                    return ("ok", res, state)
                elif timeout and time.time() - start > timeout:
                    self.log.debug(f"reached timeout, latest state is '{state}'")
                    return ("timeout", res, state)
                elif state not in good:
                    self.log.debug(f"got new state '{state}'")
                    return ("new state", res, state)
            except requests.exceptions.ConnectionError as e:
                self.log.debug(
                    f"ignoring connection error while waiting for state changes: {e}"
                )
            finally:
                self.honor_exit()
                time.sleep(1)

    def cancel_revision(self, base, session, rev):
        self.log.debug(f"cancelling revision {rev}")
        res = session.patch(
            f"{base}/revision/{rev}",
            data=json.dumps(
                {
                    "state": "pending",
                    "auto-prompt": {"ays": "ays_yes"},
                }
            ),
        )
        res = session.patch(
            f"{base}/revision/{rev}",
            data=json.dumps(
                {
                    "state": "confirm_fail",
                    "auto-prompt": {"ays": "ays_yes"},
                }
            ),
        )

    def get_diff(self, base, session, rev):
        self.honor_exit()
        self.log.debug(f"getting diff between 'applied' and '{rev}'")
        res = session.get(f"{base}/", params={"rev": "applied", "diff": rev})
        if self.cfg.session_log_dir:
            ts = (
                datetime.datetime.utcnow()
                .replace(microsecond=0, tzinfo=datetime.timezone.utc)
                .isoformat()
            )
            path = os.path.join(self.cfg.session_log_dir, f"{name}-{rev}-{ts}.json")
            self.log.debug(f"writing revision diff to {path}")
            with open(path, "w") as f:
                print(res.text, file=f)
        return res.json()

    def apply_revision(self, base, session, rev):
        self.honor_exit()
        self.log.debug("applying revision")
        session.patch(
            f"{base}/revision/{rev}",
            data=json.dumps(
                {
                    "state": "apply",
                    "state-controls": {"confirm": int(self.cfg.rollback_timeout) * 60},
                    "auto-prompt": {"ays": "ays_yes"},
                }
            ),
        )

    def confirm_revision(self, base, session, rev, name):
        self.honor_exit()
        self.log.info(f"confirming revision {rev} on node {name}")
        session.patch(
            f"{base}/revision/{rev}",
            data=json.dumps(
                {
                    "state": "confirm_yes",
                    "auto-prompt": {"ays": "ays_yes"},
                }
            ),
        )

    def is_ready(self, base, session):
        self.honor_exit()
        res = session.get(f"{base}/revision")
        for id, rev in res.json().items():
            if rev["state"] in NT_BLOCKING:
                self.log.error(f"other revision {id} is blocking with state: {rev}")
                return False
        return True

    def find_addr(self, session, device):
        def contact(self, session, addr):
            url = f"https://{addr}:{self.cfg.nvue_port}/nvue_v1/"
            self.log.debug(f"attempting to connect to {url}")
            return session.get(url)

        for addr in device["addresses"][6]:
            addr = "[" + addr + "]"
            if contact(self, session, addr):
                return addr

        for addr in device["addresses"][4]:
            if contact(self, session, addr):
                return addr

        return None

    def deploy(self, cwc):
        device = cwc.context["device"]
        self.log.debug("starting deployment")

        session = requests.Session()
        session.auth = (self.cfg.deploy_user, self.cfg.nvue_pass)
        session.headers.update(
            {
                "Host": device["nodename"] + "." + self.cfg.dns_parent,
                "Content-Type": "application/json",
            }
        )
        session.mount("https://", HostHeaderSSLAdapter())

        addr = self.find_addr(session, device)
        if not addr:
            self.log.error("all addresses are unresponsive")
            return False
        base = f"https://{addr}:{self.cfg.nvue_port}/nvue_v1"

        if not self.is_ready(base, session):
            return False

        res = session.post(f"{base}/revision")
        rev = list(res.json().keys())[0]
        params = {"rev": rev}

        try:
            self.log.debug(f"deploying new revision {rev}")
            self.honor_exit()

            session.delete(f"{base}/", params=params)
            self.honor_exit()
            session.patch(f"{base}/", data=json.dumps(device["config"]), params=params)

            diff = self.get_diff(base, session, rev)
            try:
                if (
                    diff.keys() == {"system"}
                    and diff["system"].keys() == {"message"}
                    and diff["system"]["message"].keys() == {"pre-login"}
                ):
                    self.log.debug(
                        "not activating revision which only changes the pre-login message"
                    )
                    return True
                else:
                    self.log.debug(
                        "activating revision which changes more than pre-login message"
                    )
            except (KeyError, TypeError) as e:
                self.log.error(
                    f"encountered error while inspecting diff of revision {rev}",
                    exc_info=e,
                )
                pass

            if self.cfg.dry_deploy:
                self.log.debug(
                    f"not activating revision {rev} when running in dry-deploy mode"
                )
            else:
                self.apply_revision(base, session, rev)

                self.log.debug("sent commit request, waiting for acknowledgement")

                # give the server some time to react, then check if another revision
                # is already being commited
                self.wait_for_state(
                    session,
                    f"{base}/revision/{rev}",
                    good=NT_WAIT_FOR_TURN,
                    target={},
                    timeout=10,
                )
                self.honor_exit()
                res = session.get(f"{base}/revision/{rev}")
                if res.json()["state"] in NT_WAIT_FOR_TURN:
                    self.log.error(
                        f"revision {rev} is being blocked by earlier revision, waiting"
                    )
                    self.wait_for_state(
                        session,
                        f"{base}/revision/{rev}",
                        good=NT_WAIT_FOR_TURN,
                        target={},
                        timeout=None,
                    )

                self.log.debug("waiting for revision to be checked and verified")
                self.wait_for_state(
                    session, f"{base}/revision/{rev}", good=NT_PREPROCESS, target={}
                )
                self.log.debug("waiting for revision to be loaded")
                self.wait_for_state(
                    session,
                    f"{base}/revision/{rev}",
                    good=NT_RELOADING,
                    target=NT_CONFIRM,
                    timeout=self.timeout,
                )
            self.log.debug(f"reconnecting to confirming revision {rev}")
            addr = self.find_addr(session, device)
            if not addr:
                self.log.error("all addresses are unresponsive")
                return False
            base = f"https://{addr}:{self.cfg.nvue_port}/nvue_v1"
            if self.cfg.dry_deploy:
                self.log.debug(
                    f"not confirming revision {rev} when running in dry-deploy mode"
                )
            else:
                self.confirm_revision(base, session, rev, device["nodename"])

                self.wait_for_state(
                    session,
                    f"{base}/revision/{rev}",
                    good=NT_CONFIRM,
                    target=NT_APPLIED,
                )
            self.log.debug(f"successfully deployed revision {rev}")

        except (ShutdownCommencing, Exception) as e:
            self.cancel_revision(base, session, rev)
            raise e


DRIVERS = {
    "access-switch_juniper_ex3300-24t": DeployJunos,
    "access-switch_juniper_ex3300-48p": DeployJunos,
    "core-switch_mellanox_sn2410": DeployCumuls,
}
