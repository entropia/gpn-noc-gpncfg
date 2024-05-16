#!/usr/bin/env python3

import logging
import os
import queue
import time
from concurrent import futures
from pprint import pprint as pp
from threading import Lock

import gpncfg

from ..config import ConfigProvider
from ..data_provider import DataProvider
from ..deployment import DeployDispatcher
from ..fiddle import Fiddler
from ..render import Renderer

log = logging.getLogger(__name__)


def run():
    MainAction().run()


def handle_completed_future(id, fut):
    if exc := fut.exception(0):
        log.error("thread raised exception", exc_info=exc)
    log.debug("thread {} finished with result {}".format(id, fut.result(0)))


class MainAction:
    def __init__(self):
        logging.getLogger().addHandler(gpncfg.color_handler())

        cfgp = ConfigProvider()
        cfgp.collect()
        cfgp.assemble()
        self.cfg = cfgp.options

        # this lock guards self.configs. while dict.get() should be atomic,
        # there are edge cases where it is not. one example is, if the hash
        # function is not atomic, which happens when it is written in python
        self.configs_access = Lock()

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

        if self.cfg.use_cache:
            dp.fetch_cache()
        else:
            dp.fetch_nautobot()

        if self.cfg.populate_cache:
            return

        data = self.fiddler.fiddle(dp.data)
        return self.renderer.render(data)

    def worker_deploy_device(self, key, q):
        log = logging.getLogger(__name__).getChild(f"worker#{key}")
        log.debug("hewwo")
        cwc = None
        while True:
            # wait for new updates to come in. if there are multiple, ignore the latest
            if q.empty():
                log.debug("waiting for new configs")
                log.debug("no config in que, waiting for new one")
                cwc = q.get()
                log.debug(f"got config: {cwc}")
            else:
                try:
                    log.debug("ignoring outdated configs")
                    while new := q.get_nowait():
                        cwc = new
                        log.debug(f"got config: {cwc}")
                except queue.Empty:
                    pass
            log.debug(f"received new config: {cwc}")

            if cwc == "exit":
                log.info("no data to deploy for this device, exiting worker thread")
                return True

            serial = cwc.context["device"]["serial"]
            log.debug("writing config for serial " + serial)
            cwc.path = os.path.abspath(
                os.path.join(self.cfg.output_dir, "config-" + serial)
            )
            with open(cwc.path, "w+") as file:
                print(cwc.config, file=file)

            self.dispatch.deploy_device(cwc)

    def run(self):
        if self.cfg.daemon:
            self.run_daemon()
        else:
            self.run_once()

    def run_daemon(self):
        self.data = dict()
        with futures.ThreadPoolExecutor() as pool:
            futs = dict()
            queues = dict()
            try:
                while True:
                    # wait for new data
                    configs = self.fetch_data()

                    # get list of currently relevant devices
                    active = set(configs.keys())

                    # start worker threads for new devices
                    new = active - set(futs)
                    if new:
                        log.info(f"spawning workers for new devices {new}")
                    for id in new:
                        queues[id] = queue.Queue()
                        futs[id] = pool.submit(
                            self.worker_deploy_device, id, queues[id]
                        )

                    # shut down worker threads of devices that were relevant before
                    # but are not included in this update
                    old = set(futs) - active
                    if old:
                        log.debug(f"these devices are not deployed anymore: {old}")
                        for id in old:
                            queues[id].put("exit")
                            del queues[id]
                            finished = futs.remove(id)

                    # send new configs to devices
                    for id, cwc in configs.items():
                        queues[id].put(cwc)

                    # handle finished or crashed threads
                    for id, fut in list(futs.items()):
                        if fut.done():
                            handle_completed_future(id, fut)
                            del queues[id]
                            del futs[id]

                    # in offline mode fetching data is very quick. take a moment
                    # to relax
                    if self.cfg.use_cache:
                        time.sleep(10)

            except BaseException as e:
                try:
                    if isinstance(e, Exception):
                        log.fatal(
                            "main thread encountered error, shutting down workers and exiting",
                            exc_info=e,
                        )
                    else:
                        log.info(
                            f"main thread received signal, shutting down workers and exiting: {e}"
                        )
                    log.info("shutting down the threadpool and cancelling workers")

                    # tell workers to exit
                    for id, q in queues.items():
                        log.debug(f"shutting down worker {id}")
                        q.put("exit")

                    # handle finished or crashed threads
                    log.info("workers cancelled, waiting for them to exit")
                    while futs:
                        for id, fut in list(futs.items()):
                            if fut.done():
                                handle_completed_future(id, fut)
                                del queues[id]
                                del futs[id]
                        log.debug(f"remaining futures: {futs}")

                    # exit with non zero code if the main loop got interrupted by an error
                    if isinstance(e, Exception):
                        exit(1)
                except BaseException as e:
                    log.fatal(
                        "main thread encountered error while handling previous error, force exiting now",
                        exc_info=e,
                    )
                    os._exit(1)

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
