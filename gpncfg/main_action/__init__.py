#!/usr/bin/env python3

import logging
import os
from pprint import pprint as pp

from .. import config
from ..data_provider import DataProvider
from ..generator import Generator

log = logging.getLogger(__name__)


def run():
    MainAction()


class MainAction:
    def __init__(self):
        self.cfg = config.assemble()

        logging.basicConfig()
        logging.getLogger("gpncfg").setLevel(self.cfg.log_level)

        log.info("gpncfg greets garry gulaschtopf")

        os.makedirs(self.cfg.output_dir, exist_ok=True)
        assert os.access(
            self.cfg.output_dir, os.W_OK
        ), f"output directory at '{self.cfg.output_dir}' is not writeable"

        dp = DataProvider(self.cfg)

        if self.cfg.offline:
            dp.fetch_cache()
        else:
            dp.fetch_nautobot()

        gen = Generator(self.cfg, dp.data)
        gen.fiddle()
        gen.generate()

        log.info("writing configs")
        for key in gen.configs:
            with open(os.path.join(self.cfg.output_dir, "config-" + key), "w+") as file:
                log.debug("writing config for serial " + key)
                print(gen.configs[key], file=file)
