#!/usr/bin/env python3

import logging
from pprint import pprint as pp

from .. import config
from ..data_provider import DataProvider

log = logging.getLogger(__name__)


class MainAction:
    def __init__(self):
        self.cfg = config.assemble()

        logging.basicConfig()
        logging.getLogger("gpncfg").setLevel(self.cfg.log_level)

        log.info("gpncfg greets garry gulaschtopf")

        dp = DataProvider(
            self.cfg.netbox_url + "/graphql/",
            self.cfg.netbox_token,
            self.cfg.cache_dir + "/devicelist.json",
        )

        dp.fetch_netbox()
        pp(dp.data)

        dp.data = None

        dp.fetch_cache()
        pp(dp.data)
