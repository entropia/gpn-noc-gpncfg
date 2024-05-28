#!/usr/bin/env python3

import logging
import os
import queue
import shutil
import threading
import time
from concurrent import futures
from pprint import pprint

import gpncfg

from .. import deployment, threadaction
from ..config import ConfigProvider
from ..data_provider import DataProvider
from ..fiddle import Fiddler
from ..render import Renderer
from ..writer import Writer

log = logging.getLogger(__name__)


def run():
    MainAction().run()


def get_id_from_cwc(cwc):
    return cwc.device["id"]


def shall_deploy(cwc):
    return cwc.device["status"]["name"] in {"Active", "Staged"}


def log_worker_result(task):
    name = f"worker thread {task.id}"
    if exc := task.exception(0):
        if isinstance(exc, threadaction.ShutdownCommencing):
            log.debug(f"{name} finished early after receiving a shutdown request")
        else:
            log.error(f"{name} encountered an error", exc_info=exc)
    else:
        log.debug(f"{name} completed with result {task.result(0)}")


def log_action_result(task):
    name = f"action thread {task.id}"
    if exc := task.exception(0):
        log.error(f"{name} encountered an error", exc_info=exc)
    else:
        log.error(f"{name} finished unexpectedly with result {task.result(0)}")


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
        self.writer = Writer(self.cfg, self.exit)

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

        futs_device = set()
        futs_action = set()
        queues = dict()
        pool = futures.ThreadPoolExecutor()
        try:
            self.writer.spawn(pool, futs_action, queues)
            while True:
                # wait for new data from nautobot
                configs = self.fetch_data()

                queues["action-writer"].put(configs.values())

                # create a set of device ids that we have threads for
                current = set(fut.id for fut in futs_device)

                # create a set of device ids that are supposed to be deployed
                if self.cfg.limit:
                    active = set(self.cfg.limit)
                else:
                    active = set(
                        get_id_from_cwc(cwc)
                        for cwc in configs.values()
                        if shall_deploy(cwc)
                    )

                # start worker routines for new devices
                new = active - current
                missing_usecases = set()
                if new:
                    log.info(f"spawning workers for new devices {new}")
                for id in new:
                    queues[id] = queue.Queue()
                    usecase = configs[id].device["usecase"]

                    driver = deployment.DRIVERS.get(usecase)
                    if driver:
                        task = pool.submit(
                            driver(self.cfg, self.exit, queues[id], id).worker_loop
                        )
                        task.id = id
                        futs_device.add(task)
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
                        finished = futs_device.remove(id)

                # send new configs to devices
                for cwc in configs.values():
                    id = get_id_from_cwc(cwc)
                    try:
                        queues[id].put(cwc)
                    except KeyError:
                        text = "no deploy worker for device {nodename} serial {serial} id {id}".format(
                            **cwc.device
                        )
                        if self.cfg.limit or not shall_deploy(cwc):
                            log.debug(text)
                        else:
                            log.error(text)

                # handle finished or crashed threads
                done_device, futs_device = futures.wait(futs_device, timeout=0)
                for fut in done_device:
                    log_worker_result(fut)
                    del queues[fut.id]
                done_action, futs_action = futures.wait(futs_action, timeout=0)
                for fut in done_action:
                    log_action_result(fut)
                    del queues[fut.id]
                if done_action:
                    ids = set(fut.id for fut in done_action)
                    raise Exception(f"some action threads finished unexpectedly {ids}")

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
            for fut in futures.as_completed(futs_device):
                log_worker_result(fut)

            shutil.rmtree("/var/tmp/gpncfg")
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
                futs = futs_device
                futs.update(futs_action)
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
