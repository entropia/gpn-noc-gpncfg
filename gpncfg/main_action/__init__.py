#!/usr/bin/env python3

import logging
import os
from pprint import pprint as pp

import gpncfg

from ..config import ConfigProvider
from ..data_provider import DataProvider
from ..fiddle import Fiddler
from ..render import Renderer

log = logging.getLogger(__name__)


def run():
    MainAction()


class MainAction:
    def __init__(self):
        logging.getLogger().addHandler(gpncfg.color_handler())

        cfgp = ConfigProvider()
        cfgp.collect()
        cfgp.assemble()
        self.cfg = cfgp.options

        log.info("gpncfg greets gulli gulasch")

        os.makedirs(self.cfg.output_dir, exist_ok=True)
        assert os.access(
            self.cfg.output_dir, os.W_OK
        ), f"output directory at '{self.cfg.output_dir}' is not writeable"

        dp = DataProvider(self.cfg)

        if self.cfg.populate_cache:
            if self.cfg.offline:
                log.fatal("cannot populate cache in offline mode")
                exit(1)
            dp.fetch_nautobot()
            return

        if self.cfg.offline:
            dp.fetch_cache()
        else:
            dp.fetch_nautobot()

        fiddler = Fiddler(self.cfg)
        data = fiddler.fiddle(dp.data)

        renderer = Renderer(self.cfg)
        configs = renderer.render(data)

        if not configs:
            log.info("no configs to write, exiting")
            return

        log.info("writing configs")
        for serial, cwc in configs.items():
            cwc.path = os.path.abspath(
                os.path.join(self.cfg.output_dir, "config-" + serial)
            )
            with open(cwc.path, "w+") as file:
                log.debug("writing config for serial " + serial)
                print(cwc.config, file=file)
