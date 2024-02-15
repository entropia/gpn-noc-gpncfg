#!/usr/bin/env python3

import logging

from .. import config

log = logging.getLogger(__name__)


class MainAction:
    def __init__(self):
        self.config = config.assemble()

        logging.basicConfig(level=self.config.log_level)

        log.info("gpncfg greets garry gulaschtopf")
