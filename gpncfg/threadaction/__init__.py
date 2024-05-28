import json
import logging
import os
import queue
from pprint import pprint

log = logging.getLogger(__name__)


# like SystemExit and asyncio.exceptions.CancelledError, inherit from
# BaseException. This way, the shutdown can not be confused with an error.
class ShutdownCommencing(BaseException):
    pass


class Action:
    def __init__(self, cfg, exit, name):
        self.exit = exit
        self.cfg = cfg
        self.log = logging.getLogger(__name__).getChild(f"action#{name}")

    def honor_exit(self):
        if self.exit.is_set():
            self.log.debug("honoring shutdown request")
            raise ShutdownCommencing()

    def spawn(self, pool, futs_action, queues):
        q = queue.Queue()
        task = pool.submit(self.worker_loop, q)
        task.id = self.name
        queues[self.name] = q
        futs_action.add(task)
