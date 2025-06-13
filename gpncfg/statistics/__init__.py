import logging
from typing import Dict

from prometheus_client import Gauge

log = logging.getLogger(__name__)


class Statistics(object):
    _instance = None
    _data: Dict[str, Gauge] = {}

    def __new__(cls):
        if not isinstance(cls._instance, cls):
            cls._instance = super(Statistics, cls).__new__(cls)
        return cls._instance

    def update(self, device_slug: str, action: str) -> None:
        if action not in self._data:
            self._data[action] = Gauge(
                f"gpncfg_{action}",
                f"Last time {action} has been performed on a given device",
                ["device"],
            )
        self._data[action].labels(device_slug).set_to_current_time()
