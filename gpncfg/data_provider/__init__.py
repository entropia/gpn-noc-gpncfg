#!/usr/bin/env python3

import datetime
import glob
import hashlib
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
        self.last_hash = None

    def fetch_nautobot_graphql(self):
        log.info(f"fetching device information from api at {self.cfg.nautobot_url}")
        transport = AIOHTTPTransport(
            url=self.cfg.nautobot_url + "/api/graphql/",
            headers={"Authorization": "Token %s" % self.cfg.nautobot_token},
        )

        # Create a GraphQL client using the defined transport
        client = gql.Client(transport=transport, fetch_schema_from_transport=True)

        tenant = ""
        if self.cfg.nautobot_tenant:
            tenant = 'tenant:"{}"'.format(self.cfg.nautobot_tenant)

        # Provide a GraphQL query
        query = gql.gql(
            """
            query {
                devices(
                    status__n: "Offline"
                    role: ["access switch" "core switch" "Router"]
                    %(tenant)s
                ) {
                    name,
                    id,
                    serial,
                    location{name},
                    device_type{
                        manufacturer{
                            name,
                        },
                        model,
                    },
                    role {
                        name,
                    },
                    primary_ip4 {
                      address
                      host
                      parent {
                        rel_gateway {
                          host
                        }
                      }
                    }
                    interfaces {
                        name,
                        ip_addresses { address },
                        description,
                        id,
                        type,
                        mode,
                        tagged_vlans{name,vid},
                        untagged_vlan{name,vid},
                        _custom_field_data,
                    }
                },
                vlans(
                    status:"Active"
                    %(tenant)s
                ) {
                    name,
                    vid
                }
            }
            """
            % {"tenant": tenant}
        )

        # Execute the query on the transport
        result = client.execute(query)

        self.data = result

    def fetch_nautobot(self):
        # make sure the cache directory is good before doing possibly expensive
        # api calls
        self.assert_cache_writeable()
        self.hash_last()
        # contact graphql api
        self.fetch_nautobot_graphql()
        # save cache
        self.save_cache()

    def save_cache(self):
        log.debug("saving device information to cache")
        self.assert_cache_writeable()

        cur_hash = self.hash_data()
        log.debug("data returned from nautobot hashes to {}".format(cur_hash))

        # if no hash was provided fetch it now
        self.hash_last()
        log.debug(" most recently chached data hashes to {}".format(self.last_hash))

        if cur_hash == self.last_hash:
            log.debug("cache is up to date")
        else:
            name = "nautobot-{}.json".format(
                datetime.datetime.utcnow()
                .replace(microsecond=0, tzinfo=datetime.timezone.utc)
                .isoformat()
            )
            log.info(
                "most recent cache is outdated, saving new cache to {}".format(name)
            )
            self.save_cache_to(name)

    def save_cache_to(self, name):
        path = os.path.join(self.cfg.cache_dir, name)
        with open(path, "w") as file:
            json.dump(self.data, file, indent=4, sort_keys=True)
            file.write("\n")

    def fetch_cache(self):
        self.assert_cache_readable()
        cache_file = self.get_latest_cache_path()
        log.info(f"fetching device information from cache at '{cache_file}'")

        if cache_file == None:
            log.fatal(
                "running in offline mode but no cached queries were found, exiting"
            )
            exit(1)

        with open(cache_file, "r") as file:
            self.data = json.load(file)

    def get_latest_cache_path(self):
        pattern = os.path.join(self.cfg.cache_dir, "nautobot-*.json")
        files = glob.glob(pattern)
        if files == []:
            log.debug("no previous cache files found")
            return None
        else:
            files.sort()
            file = files[-1]
            log.debug("found previous cache file {}".format(file))
            return file

    def hash_data(self):
        text = json.dumps(self.data, indent=4, sort_keys=True) + "\n"
        return hashlib.sha256(text.encode()).hexdigest()

    def hash_last(self):
        if self.last_hash != None:
            log.debug("data provider's last_hash already populated, skipping")
            return

        log.debug("data provider's last_hash not yet populated, hashing latest cache")
        last_path = self.get_latest_cache_path()
        if last_path == None:
            log.debug("no previous cache found, therefore not hashing it")
            self.last_hash = False
            return

        size = os.path.getsize(last_path)
        with open(last_path, "r") as f:
            # specify size to prevent waiting indefinitely on empty files
            text = f.read(size)

        self.last_hash = hashlib.sha256(text.encode()).hexdigest()

    def assert_cache_readable(self):
        log.debug(f"making sure cache directory at '{self.cfg.cache_dir}' is readable")

        assert os.access(
            self.cfg.cache_dir, os.R_OK
        ), f"cache directory at '{self.cfg.cache_dir}' is not readable"

    def assert_cache_writeable(self):
        log.debug(
            f"making sure cache directory at '{self.cfg.cache_dir}' exists and is both readable and writeable"
        )

        os.makedirs(self.cfg.cache_dir, exist_ok=True)

        assert os.access(
            self.cfg.cache_dir, os.R_OK
        ), f"cache directory at '{self.cfg.cache_dir}' is not readable"
        assert os.access(
            self.cfg.cache_dir, os.W_OK
        ), f"cache directory at '{self.cfg.cache_dir}' is not writeable"
