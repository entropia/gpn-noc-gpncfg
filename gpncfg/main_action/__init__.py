#!/usr/bin/env python3

import logging
import os
import queue
import shutil
import sys
import threading
import time
from concurrent import futures

import gpncfg

from .. import deployment, threadaction
from ..config import ConfigProvider
from ..data_provider import DataProvider
from ..fiddle import Fiddler
from ..render import Renderer
from ..statistics import Statistics
from ..writer import Cleaner, Writer

log = logging.getLogger(__name__)


def run():
    MainAction().run()


def get_id_from_cwc(cwc):
    return cwc.device["id"]


def log_worker_result(task):
    name = f"worker thread {task.id}"
    if exc := task.exception(0):
        if isinstance(exc, threadaction.ShutdownCommencing):
            log.debug(f"{name} finished early after receiving a shutdown request")
        else:
            log.error(f"{name} encountered an error", exc_info=exc)
    else:
        log.debug(f"{name} completed with result {task.result(0)}")


def handle_worker_exits(pending, timeout):
    start = time.time()
    end = start + timeout
    log.info(f"waiting {timeout} seconds for worker threads to exit")
    # handle both lists and sets
    while end - time.time() > 0:
        (done, pending) = futures.wait(
            pending,
            timeout=end - time.time(),
            return_when=futures.FIRST_COMPLETED,
        )
        for result in done:
            log_worker_result(result)

        if len(pending) == 0:
            break

    if len(pending) > 0:
        raise TimeoutError("not all worker threads exited in time.")


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
        self.cleaner = Cleaner(self.cfg, self.exit)

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
            if self.cfg.daemon:
                sts = Statistics()
                sts.set_fetch()

        if self.cfg.populate_cache:
            return None

        data = self.fiddler.fiddle(dp.data)
        return self.renderer.render(data)

    def run(self):
        if self.cfg.daemon:
            statistics = Statistics()
            statistics.start_http_server(int(self.cfg.prometheus_port))

        if self.cfg.populate_cache:
            return self.fetch_data()

        futs_device = set()
        futs_action = set()
        queues = dict()
        pool = futures.ThreadPoolExecutor(max_workers=999)
        try:
            self.writer.spawn(pool, futs_action, queues)
            self.cleaner.spawn(pool, futs_action, queues)
            while True:
                # wait for new data from nautobot
                configs = self.fetch_data()

                if q := queues.get("action-writer"):
                    q.put(configs.values())

                # create a set of device ids that we have threads for
                current = set(fut.id for fut in futs_device)

                # create a set of device ids that are supposed to be deployed
                if self.cfg.limit:
                    active = set(self.cfg.limit)
                else:
                    active = set(
                        get_id_from_cwc(cwc)
                        for cwc in configs.values()
                        if cwc.device["deploy"]
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
                            driver(self.cfg, self.exit, queues[id], id).worker_loop,
                            None,
                        )
                        task.id = id
                        futs_device.add(task)
                    else:
                        missing_usecases.add(usecase)

                if missing_usecases:
                    log.error(
                        f"unable to find deployment driver for {missing_usecases}"
                    )

                # send new configs to devices
                for cwc in configs.values():
                    id = get_id_from_cwc(cwc)
                    try:
                        queues[id].put(cwc)
                    except KeyError:
                        text = "no deploy worker for device {nodename} serial {serial} id {id}".format(
                            **cwc.device
                        )
                        if self.cfg.limit or not cwc.device["deploy"]:
                            log.debug(text)
                        else:
                            log.error(text)

                log.debug("main thread queries finished device workers")

                # handle finished or crashed threads
                done_device, futs_device = futures.wait(futs_device, timeout=0)
                for fut in done_device:
                    log_worker_result(fut)
                    del queues[fut.id]

                log.debug("main thread queries finished action workers")
                done_action, futs_action = futures.wait(futs_action, timeout=0)
                for fut in done_action:
                    log_worker_result(fut)
                    del queues[fut.id]
                if self.cfg.daemon and done_action:
                    ids = []
                    for fut in done_action:
                        ids.append(fut.id)
                    log.error(
                        "raising exception to exit main thread because action workers existed early"
                    )
                    raise Exception(f"some action threads finished unexpectedly {ids}")

                ids = []
                for fut in futs_device:
                    ids.append(f"<id: {fut.id} fut {fut}>")

                log.debug(f"main thread knows about these device workers: {ids}")

                # only loop in daemon mode
                if not self.cfg.daemon:
                    break

                # in cache mode fetching data is very quick. take a moment
                # to relax
                if self.cfg.use_cache:
                    time.sleep(10)

            ## this is only executed when we are not doing continuous generation/deployments
            log.info(
                "deployments are commencing. this ritual may take multiple minutes."
            )
            pool.shutdown(wait=False, cancel_futures=False)

            # wait 10 minutes for worker threads to exit and log their results
            futs = futs_device
            futs.update(futs_action)
            handle_worker_exits(futs, 600)

            try:
                shutil.rmtree("/var/tmp/gpncfg")
            except FileNotFoundError:
                pass

            log.info("goodbye")

        except (Exception, KeyboardInterrupt) as e:
            try:
                # log why the main thread was interrupted
                if isinstance(e, KeyboardInterrupt):
                    log.info("received ^C, attempting clean shutdown.")
                else:
                    log.fatal(
                        "main thread encountered error",
                        exc_info=e,
                    )

                futs = futs_device
                futs.update(futs_action)

                for fut in futs:
                    if fut.running():
                        log.debug(f"remaining worker {fut} with id {fut.id}")

                log.debug("telling worker threads to stop")
                # no new threads/futures can spawn
                pool.shutdown(wait=False, cancel_futures=True)
                # indicate to workers that they must exit
                self.exit.set()

                # wait for workers to finish and log their result
                handle_worker_exits(futs, 360)

                log.info("all workers exited. gpncfg knows it will join them soon")

                # exit with non zero code if the main loop got interrupted by an error
                if isinstance(e, Exception):
                    sys.exit(1)
            except (Exception, KeyboardInterrupt) as e:
                log.fatal(
                    "main thread encountered error while trying to exit, force exiting now",
                    exc_info=e,
                )
                futs = futs_device
                futs.update(futs_action)
                if not futs:
                    log.debug("futs is empty")
                for fut in futs:
                    if fut.running():
                        log.info(f"remaining worker {fut} with id {fut.id}")
                    else:
                        log.debug(f"exited worker {fut} with id {fut.id}")

                log.info("forcing exit, goodbye")
                os._exit(1)
