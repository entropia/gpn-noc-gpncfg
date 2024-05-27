#!/usr/bin/env python3

import logging
import os
import queue
import threading
import time
from concurrent import futures
from pprint import pprint

import gpncfg

from .. import deployment
from ..config import ConfigProvider
from ..data_provider import DataProvider
from ..fiddle import Fiddler
from ..render import Renderer

log = logging.getLogger(__name__)


def run():
    MainAction().run()


def get_id_from_cwc(cwc):
    return cwc.context["device"]["id"]


def log_worker_result(task):
    name = f"worker thread {task.id}"
    if exc := task.exception(0):
        if isinstance(exc, deployment.ShutdownCommencing):
            log.debug(f"{name} finished early after receiving a shutdown request")
        else:
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

    def wait_for_workers(self, workers):
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

    def run(self):
        if self.cfg.populate_cache:
            return self.fetch_data()

        futs = set()
        queues = dict()
        pool = futures.ThreadPoolExecutor()
        try:
            while True:
                # wait for new data from nautobot
                configs = self.fetch_data()

                # create a set of device ids that we have threads for
                current = set(fut.id for fut in futs)

                # create a set of device ids that are supposed to be deployed
                if self.cfg.limit:
                    active = set(self.cfg.limit)
                else:
                    active = set(get_id_from_cwc(cwc) for cwc in configs.values())

                # start worker routines for new devices
                new = active - current
                missing_usecases = set()
                if new:
                    log.info(f"spawning workers for new devices {new}")
                for id in new:
                    queues[id] = queue.Queue()
                    usecase = configs[id].context["device"]["usecase"]

                    driver = deployment.DRIVERS.get(usecase)
                    if driver:
                        task = pool.submit(
                            driver(self.cfg, self.exit, queues[id], id).worker_loop
                        )
                        task.id = id
                        futs.add(task)
                    else:
                        missing_usecases.add(usecase)

                if missing_usecases:
                    log.error(
                        f"unable to find deployment driver for {missing_usecases}"
                    )

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
                    try:
                        queues[get_id_from_cwc(cwc)].put(cwc)
                    except KeyError:
                        text = "no deploy worker for device {nodename} serial {serial} id {id}".format(
                            **cwc.context["device"]
                        )
                        if self.cfg.limit:
                            log.debug(text)
                        else:
                            log.warn(text)

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
                "deployments are commencing. this ritual may take multiple minutes."
            )
            pool.shutdown(wait=False, cancel_futures=False)
            # wait for workers to finish and log their result
            for fut in futures.as_completed(futs):
                log_worker_result(fut)
        except (Exception, KeyboardInterrupt) as e:
            try:
                # log why the main thread was interrupted
                if isinstance(e, Exception):
                    log.fatal(
                        "main thread encountered error",
                        exc_info=e,
                    )
                else:
                    log.info("received ^C, attempting clean shutdown.")

                # tell worker threads to exit
                pool.shutdown(wait=False, cancel_futures=True)
                self.exit.set()

                log.info(
                    "waiting for worker threads to exit. this might take up to a minute"
                )

                # wait for workers to finish and log their result
                for fut in futures.as_completed(futs):
                    log_worker_result(fut)

                log.info(
                    "all workers exited cleanly. gpncfg knows it will join them soon"
                )

                # exit with non zero code if the main loop got interrupted by an error
                if isinstance(e, Exception):
                    exit(1)
            except (Exception, KeyboardInterrupt) as e:
                log.fatal(
                    "main thread encountered error while trying to exit, force exiting now",
                    exc_info=e,
                )
                os._exit(1)
