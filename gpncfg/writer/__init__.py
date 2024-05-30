import logging
import os
import queue
import time

from ..threadaction import Action

log = logging.getLogger(__name__)


class Writer(Action):
    def __init__(self, *args):
        self.name = "action-writer"
        super().__init__(*args, self.name)

    def worker_loop(self, q):
        self.log.debug("starting loop")
        while True:
            self.log.debug("waiting for new configs")
            while True:
                try:
                    configs = q.get(timeout=1)
                    break
                except (TimeoutError, queue.Empty):
                    pass
                finally:
                    self.honor_exit()

            for config in configs:
                self.write_config(config)

            if not self.cfg.daemon:
                break

    def write_config(self, cwc):
        device = cwc.device
        serial = device["serial"]
        if not cwc.config:
            self.log.debug(
                "not writing config for serial {serial} because it is empty".format(
                    **device
                )
            )
            return

        self.log.debug("writing config for serial {serial}".format(**device))
        name_serial = "config-{serial}".format(**device)
        cwc.path = os.path.abspath(os.path.join(self.cfg.output_dir, name_serial))
        with open(cwc.path, "w+") as file:
            print(cwc.config, file=file)

        by_name = os.path.abspath(
            os.path.join(self.cfg.output_dir, "config-{nodename}".format(**device))
        )
        if os.path.islink(by_name):
            try:
                os.remove(by_name)
            except FileNotFoundError:
                pass
        try:
            os.symlink(name_serial, by_name)
        except FileExistsError:
            pass


class Cleaner(Action):
    def __init__(self, *args):
        self.name = "action-cleaner"
        super().__init__(*args, self.name)

    def worker_loop(self, _):
        self.log.debug("starting loop")
        while True:
            max_age = 0
            current = time.time()
            for file in os.listdir(self.cfg.output_dir):
                path = os.path.join(self.cfg.output_dir, file)
                mtime = os.lstat(path).st_mtime
                age = current - mtime
                if age > self.cfg.config_age:
                    self.log.debug(f"removing old config file {file} with age  {age}s")
                    os.remove(path)
                elif age > max_age:
                    max_age = age
            wait = self.cfg.config_age
            if wait > max_age:
                wait -= max_age
            else:
                raise Exception(
                    "oldest file ({max_age}s) is older than max config age ({self.cfg.config_age}s), deleting must have gone wrong"
                )

            if not self.cfg.daemon:
                break

            self.log.debug(f"sleeping for {wait} seconds")
            self.exit.wait(timeout=wait)
            self.honor_exit()
