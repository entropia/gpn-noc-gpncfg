#!/usr/bin/env python3

import logging
import os
import queue
import sys
import threading
import time
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
    MainAction().run()


def get_id_from_cwc(cwc):
    return cwc.context["device"]["id"]


def log_worker_result(task):
    name = f"worker {task.id}"
    if exc := task.exception(0):
        log.error(f"{name} encountered an error", exc_info=exc)
    else:
        log.debug(f"{name} completed with result {task.result(0)}")


class MainAction:
    def __init__(self):
        logging.getLogger().addHandler(gpncfg.color_handler())

        cfgp = ConfigProvider()
        cfgp.collect()
        cfgp.assemble()
        self.cfg = cfgp.options
        self.exit = threading.Event()

        self.fiddler = Fiddler(self.cfg)
        self.renderer = Renderer(self.cfg)
        self.dispatch = DeployDispatcher(self.cfg, self.exit)

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
        log = logging.getLogger(__name__).getChild(f"deploy#{key}")
        cwc = None
        while True:
            # wait for new updates to come in. if there are multiple, ignore the latest
            log.debug("waiting for new config")
            try:
                cwc = q.get(timeout=1)
            except TimeoutError:
                continue
            finally:
                if self.exit.is_set():
                    return True

            # check if there are more up to date configs
            for i in range(sys.maxsize):
                try:
                    cwc = q.get_nowait()
                except queue.Empty:
                    log.debug(f"skipped {i} outdated configs")
                    break

            log.debug(f"received new config: {cwc}")

            serial = cwc.context["device"]["serial"]
            log.debug("writing config for serial " + serial)
            cwc.path = os.path.abspath(
                os.path.join(self.cfg.output_dir, "config-" + serial)
            )
            with open(cwc.path, "w+") as file:
                print(cwc.config, file=file)

            if self.cfg.no_deploy:
                log.debug("as commanded, gpncfg shall not deploy to devices")
            else:
                self.dispatch.deploy_device(cwc)

            if not self.cfg.daemon:
                return True

    def run(self):
        futs = set()
        queues = dict()
        exc = None
        try:
            raise Exception()
            # because this with statement is inside the try/except block, the
            # thread pool gets automatically shut down if an exception is raised
            with futures.ThreadPoolExecutor() as pool:
                while True:
                    # wait for new data from nautobot
                    configs = self.fetch_data()

                    # create a set of device ids that we have threads for
                    current = set(fut.id for fut in futs)

                    # create a set of device ids that are supposed to be deployed
                    active = set(get_id_from_cwc(cwc) for cwc in configs.values())

                    # start worker routines for new devices
                    new = active - current
                    if new:
                        log.info(f"spawning workers for new devices {new}")
                    for id in new:
                        queues[id] = queue.Queue()
                        task = pool.submit(self.worker_deploy_device, id, queues[id])
                        task.id = id
                        futs.add(task)

                    # shut down worker routines of devices that were relevant before
                    # but are not included in this update
                    old = current - active
                    if old:
                        log.debug(
                            f"shutting down workers for no longer relevant devices: {old}"
                        )
                        for id in old:
                            del queues[id]
                            finished = futs.remove(id)

                    # send new configs to devices
                    for cwc in configs.values():
                        queues[get_id_from_cwc(cwc)].put(cwc)

                    # handle finished or crashed threads
                    done, futs = futures.wait(futs, timeout=0)
                    for fut in done:
                        del queues[fut.id]
                        log_worker_result(fut)

                    # only loop in daemon mode
                    if not self.cfg.daemon:
                        break

                    # in cache mode fetching data is very quick. take a moment
                    # to relax
                    if self.cfg.use_cache:
                        time.sleep(10)

                log.info(
                    "waiting for deployments to finish. workers might take a minute to exit"
                )
        except (Exception, KeyboardInterrupt) as e:
            exc = e
            # log why the main thread was interrupted
            if isinstance(e, Exception):
                log.fatal(
                    "main thread encountered error",
                    exc_info=e,
                )
            else:
                log.info("received ^C, attempting clean shutdown.")

            # tell worker threads to exit
            self.exit.set()

            log.info(
                "waiting for worker threads to exit. this might take up to a minute"
            )

        # wait for workers to finish and log their result
        try:
            for fut in futures.as_completed(futs):
                log_worker_result(fut)
        except (Exception, KeyboardInterrupt) as e:
            log.fatal(
                "main thread encountered error while trying to exit, force exiting now",
                exc_info=e,
            )
            os._exit(1)

        log.info("all workers exited cleanly. gpncfg knows it will join them soon")

        # exit with non zero code if the main loop got interrupted by an error
        if isinstance(exc, Exception):
            exit(1)
