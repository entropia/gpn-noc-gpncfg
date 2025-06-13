import logging
from enum import Enum
from typing import Dict

from prometheus_client import Gauge

log = logging.getLogger(__name__)


class StatisticsType(Enum):
    CONTACT = 1
    ANSWER = 2
    UPDATE = 3
    COMMIT = 4
    CONFIG = 5


class Statistics(object):
    _instance = None
    _data: Dict[StatisticsType, Gauge] = {}

    def __new__(cls):
        if not isinstance(cls._instance, cls):
            cls._instance = super(Statistics, cls).__new__(cls)
            for st in StatisticsType:
                cls._instance._data[st] = Gauge(
                    f"gpncfg_{st.name.lower()}",
                    f"Last time {st.name.lower()} has been performed on a given device",
                    ["device"],
                )
        return cls._instance

    def update(self, device_slug: str, action: StatisticsType) -> None:
        self._data[action].labels(device_slug).set_to_current_time()
