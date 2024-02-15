#!/usr/bin/env python3

import json
import logging
import os

import gql
from gql.transport.aiohttp import AIOHTTPTransport

log = logging.getLogger(__name__)


class DataProvider:
    def __init__(self, cfg):
        self.data = None
        self.cfg = cfg

    def fetch_netbox_graphql(self):
        transport = AIOHTTPTransport(
            url=self.cfg.netbox_url + "/graphql/",
            headers={"Authorization": "Token %s" % self.cfg.netbox_token},
        )

        # Create a GraphQL client using the defined transport
        client = gql.Client(transport=transport, fetch_schema_from_transport=True)

        # Provide a GraphQL query
        query = gql.gql(
            """
            query {
                device_list(
                    status:"active"
                    tenant:"garry-gulaschtopf"
                ) {
                    name,
                    id,
                    serial,
                    location{name},
                    site{name},
                    interfaces {
                        name,
                        ip_addresses { address },
                        enabled,
                        description,
                        id,
                        type,
                        mode,
                        tagged_vlans{name,vid},
                        untagged_vlan{name,vid},
                        poe_mode
                    }
                },
                vlan_list(
                    tenant:"garry-gulaschtopf"
                ) {
                    name,
                    vid
                }
            }
            """
        )

        # Execute the query on the transport
        result = client.execute(query)

        self.data = result

    def fetch_netbox(self):
        log.info(f"fetching device information from api at {self.cfg.netbox_url}")
        # make sure the cache directory is good before doing possibly expensive
        # api calls
        self.assert_cache_writeable()
        self.fetch_netbox_graphql()
        self.save_cache()

    def save_cache(self):
        log.debug("saving device information to cache")
        self.assert_cache_writeable()
        with open(self.cfg.cache_file, "w") as file:
            json.dump(self.data, file)

    def fetch_cache(self):
        log.info(f"fetching device information from cache at '{self.cfg.cache_file}'")
        self.assert_cache_readable()
        with open(self.cfg.cache_file, "r") as file:
            self.data = json.load(file)

    def assert_cache_readable(self):
        log.debug(f"making sure cache directory at '{self.cfg.cache_file}' is readable")

        assert os.access(
            self.cfg.cache_file, os.R_OK
        ), f"cache directory at '{self.cfg.cache_file}' is not writeable"
        assert os.path.isfile(
            self.cfg.cache_file
        ), f"cache file at '{self.cfg.cache_file}' is not a file"

    def assert_cache_writeable(self):
        dirname = os.path.dirname(self.cfg.cache_file)

        log.debug(f"making sure cache directory at '{dirname}' exists and is writeable")

        os.makedirs(dirname, exist_ok=True)

        assert os.access(
            dirname, os.W_OK
        ), f"cache directory at '{dirname}' is not writeable"
        # if it doesn't exist, assume we can create it
        if os.path.exists(self.cfg.cache_file):
            assert os.path.isfile(
                self.cfg.cache_file
            ), f"cache file at '{self.cfg.cache_file}' is not a file"
            assert os.access(
                self.cfg.cache_file, os.W_OK
            ), f"cache file at '{self.cfg.cache_file}' is not writeable"
