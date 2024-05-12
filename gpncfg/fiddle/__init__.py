#!/usr/bin/env python3

import copy
import datetime
import json
import logging
import os
from pprint import pprint

import jinja2

log = logging.getLogger(__name__)


TRANS_SLUG = str.maketrans(" ", "-", "()")


def slugify(text):
    return text.lower().translate(TRANS_SLUG)


class Fiddler:
    def __init__(self, cfg):
        self.cfg = cfg

    def fiddle(self, data):
        log.info("fiddling data")
        ts = (
            datetime.datetime.utcnow()
            .replace(microsecond=0, tzinfo=datetime.timezone.utc)
            .isoformat()
        )
        data = self.sanetize_vlans(data)
        data = self.fiddle_devices(data, ts)
        return data

    def sanetize_vlans(self, data):
        for vlan in data["vlans"]:
            vlan["name"] = slugify(vlan["name"])
        return data

    def fiddle_devices(self, data, ts):
        for device in data["devices"]:
            # set usecase and device id
            if device["serial"] == "":
                device["serial"] = "fallback-serial-" + device["id"]

            device["usecase"] = "_".join(
                slugify(x)
                for x in [
                    device["role"]["name"],
                    device["device_type"]["manufacturer"]["name"],
                    device["device_type"]["model"],
                ]
            )
            usecase = device["usecase"]

            # add general stuff
            if (name := device["name"]) != None:
                device["nodename"] = slugify(name)
            else:
                device["nodename"] = "device-" + device["id"]

            # log what we are doing
            log = logging.getLogger(__name__).getChild(device["nodename"])
            log.debug("fiddling config for serial {}'".format(device["serial"]))

            # use json to escape special characters
            device["motd"] = json.dumps(self.cfg.motd.format(timestamp=ts))

            try:
                device["gateway"] = device["primary_ip4"]["parent"]["rel_gateway"][
                    "host"
                ]
            except TypeError as e:
                log.warn(
                    "device has no gateway (name '{}' serial '{}')".format(
                        device["name"], device["serial"]
                    )
                )
                device["gateway"] = None

            device["addresses"] = list()
            for key in ["primary_ip6", "primary_ip4"]:
                if addr := device.get(key):
                    device["addresses"].append(addr["host"])

            log.debug("found management addreses {addresses}".format(**device))

            # add data based on usecase
            if (
                usecase == "access-switch_juniper_ex3300-24p"
                or usecase == "access-switch_juniper_ex3300-48p"
            ):
                # sort interfaces into physical and virtual ones as they are
                # treated very differently.
                device["physical_interfaces"] = list()
                device["virtual_interfaces"] = list()
                device["vids"] = list()

                for iface in device["interfaces"]:
                    iface = copy.deepcopy(iface)

                    if iface["type"] == "VIRTUAL":
                        if iface["untagged_vlan"] is None:
                            log.warn(
                                "virtual interface '{}' with no untagged vid on device '{}' serial '{}'".format(
                                    iface["name"],
                                    device["name"],
                                    device["serial"],
                                )
                            )
                            continue
                        device["vids"].append(iface["untagged_vlan"]["vid"])
                        # set ip addresses assigned in nautobot, if there are
                        # none then do dhcp
                        if len(iface["ip_addresses"]) > 0:
                            iface["do_dhcp"] = False
                        else:
                            iface["do_dhcp"] = True
                        device["virtual_interfaces"].append(iface)

                    else:
                        # format the list of tagged vlans to a string
                        tagged = ["["]
                        tagged.extend(
                            slugify(vlan["name"]) for vlan in iface["tagged_vlans"]
                        )
                        tagged.append("]")
                        iface["tagged_vlans_text"] = " ".join(tagged)

                        # slugify the untagged vlan name
                        if iface["untagged_vlan"] is not None:
                            iface["untagged_vlan"]["name"] = slugify(
                                iface["untagged_vlan"]["name"]
                            )

                        device["physical_interfaces"].append(iface)

            elif usecase == "router_juniper_mx204":
                try:
                    groups = device["bgp_routing_instances"][0]["peer_groups"]
                except IndexError:
                    groups = []

                device["bgp_groups"] = dict()
                for group in groups:
                    name = slugify(group["name"])
                    device["bgp_groups"][name] = group["endpoints"]

                for iface in device["interfaces"]:
                    iface["inet4"] = list()
                    iface["inet6"] = list()
                    for addr in iface["ip_addresses"]:
                        if addr["ip_version"] == 4:
                            iface["inet4"].append(addr)
                        elif addr["ip_version"] == 6:
                            iface["inet6"].append(addr)
                        else:
                            log.error(
                                "encountered unknown ip family: {} on device {} serial '{}'".format(
                                    addr["ip_version"], device["name"], device["serial"]
                                )
                            )

        return data
