#!/usr/bin/env python3

import logging
import os
from concurrent import futures
from pprint import pprint as pp

import gpncfg

from ..config import ConfigProvider
from ..data_provider import DataProvider
from ..deployment import DeployDispatcher
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

        self.fiddler = Fiddler(self.cfg)
        self.renderer = Renderer(self.cfg)
        self.dispatch = DeployDispatcher(self.cfg)

        log.info("gpncfg greets gulli gulasch")

    def fetch_data(self):
        os.makedirs(self.cfg.output_dir, exist_ok=True)
        assert os.access(
            self.cfg.output_dir, os.W_OK
        ), f"output directory at '{self.cfg.output_dir}' is not writeable"

        dp = DataProvider(self.cfg)

        if self.cfg.offline:
            dp.fetch_cache()
        else:
            dp.fetch_nautobot()

        if self.cfg.populate_cache:
            return

        data = self.fiddler.fiddle(dp.data)
        return self.renderer.render(data)

    def run_once(self):
        configs = self.fetch_data()

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

        if self.cfg.no_deploy:
            return

        log.info("deploying configs")
        dispatch = DeployDispatcher(self.cfg)
        with futures.ThreadPoolExecutor() as pool:
            futs = list()
            for serial, cwc in configs.items():
                log.debug(
                    "connecting to device {name} at {addresses}".format(
                        **cwc.context["device"]
                    )
                )
                futs.append(pool.submit(dispatch.deploy_device, cwc))

            for result in futures.as_completed(futs):
                if exc := result.exception(0):
                    log.error("thread raised exception", exc_info=exc)
                log.debug("thread finished with result {}".format(result.result(0)))
