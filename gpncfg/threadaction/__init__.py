import logging
import queue

log = logging.getLogger(__name__)


# like SystemExit and asyncio.exceptions.CancelledError, inherit from
# BaseException. This way, the shutdown can not be confused with an error.
class ShutdownCommencing(BaseException):
    pass


class Action:
    def __init__(self, cfg, exit, name):
        self.cfg = cfg
        self.exit = exit
        self.log = logging.getLogger(__name__).getChild(f"action#{name}")
        self.name = name

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

    def worker_loop(self, q):
        raise NotImplementedError()
