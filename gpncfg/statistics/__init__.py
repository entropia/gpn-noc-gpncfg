import logging
from enum import Enum
from threading import Thread
from typing import Dict, Optional

from prometheus_client import Gauge, start_http_server

log = logging.getLogger(__name__)


class StatisticsType(Enum):
    CONTACT = 1
    ANSWER = 2
    UPDATE = 3
    COMMIT = 4
    CONFIRM = 5


class Statistics(object):
    _instance = None
    _data: Dict[StatisticsType, Gauge] = {}
    _fetch: Gauge = None
    _server = None
    _server_thread: Optional[Thread] = None

    def __new__(cls):
        if not isinstance(cls._instance, cls):
            cls._instance = super(Statistics, cls).__new__(cls)
            for st in StatisticsType:
                cls._instance._data[st] = Gauge(
                    f"gpncfg_{st.name.lower()}",
                    f"Last time {st.name.lower()} has been performed on a given device",
                    ["device"],
                )
            cls._instance._fetch = Gauge(
                "gpncfg_fetch", "Last time data was fetched from nautobot"
            )
        return cls._instance

    def start_http_server(self, port: int) -> None:
        if not self._server:
            self._server, self._server_thread = start_http_server(port)
        else:
            logging.warning(f"HTTP server already started, not starting a second time")

    def stop_http_server(self, wait: bool) -> None:
        if not self._server:
            logging.warning(f"HTTP not started, ignoring stop request")
        else:
            self._server.shutdown()
            if wait and self._server_thread:
                self._server_thread.join()

    def update(self, device_slug: str, action: StatisticsType) -> None:
        self._data[action].labels(device_slug).set_to_current_time()

    def set_fetch(self) -> None:
        self._fetch.set_to_current_time()
