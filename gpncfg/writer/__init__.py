import json
import logging
import os
import queue
from pprint import pprint

from ..threadaction import Action

log = logging.getLogger(__name__)


class Writer(Action):
    def __init__(self, *args):
        self.name = "action-writer"
        super().__init__(*args, self.name)

    def worker_loop(self, q):
        self.log.debug("starting loop")
        while True:
            # wait for new updates to come in. if there are multiple, ignore the latest
            self.log.debug("waiting for new config")
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

    def write_config(self, cwc):
        device = cwc.device
        serial = device["serial"]
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
                os.remote(islink)
            except FileNotFoundError:
                pass
        try:
            os.symlink(name_serial, by_name)
        except FileExistsError:
            pass
