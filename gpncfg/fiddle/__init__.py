#!/usr/bin/env python3

import copy
import datetime
import ipaddress
import json
import logging
import re

from .cumulus import CUMULUS_CONFIG, UNNUMBERED_BGP

log = logging.getLogger(__name__)


TRANS_SLUG = str.maketrans({"ß": "ss", "ö": "oe", "ä": "ae", "ü": "ue"})


def slugify(text):
    """
    Juniper requires VLAN names to be at least two characters long, starting with a letter.
    Allowed characters are letters, numbers, dashes, and underscores.
    """
    lower_text = text.lower()
    umlaut_free_text = lower_text.translate(TRANS_SLUG)
    # we need to map " " to "-" in order to stay compatible with older slugs such as the usecase ones
    compat_text = re.sub(r"\s", "-", umlaut_free_text)
    clean_text = re.sub("r[^0-9a-zA-Z_-]+", "_", compat_text)
    dup_free_text = re.sub("_+", "_", clean_text)
    if not re.match("^[a-z]", dup_free_text):
        dup_free_text = "z" + dup_free_text
    if len(dup_free_text) < 2:
        dup_free_text = "x" + dup_free_text
    return dup_free_text


def sanitize_vlans(data):
    for vlan in data["vlans"]:
        vlan["name"] = slugify(vlan["name"])
    return data


class Fiddler:
    def __init__(self, cfg):
        self.cfg = cfg

    def fiddle(self, data):
        log.info("fiddling data")
        ts = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0, tzinfo=datetime.timezone.utc)
            .isoformat()
        )
        data = sanitize_vlans(data)
        data = self.fiddle_devices(data, ts)
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

            # log what we are doing
            log.debug("fiddling config for serial {}'".format(device["serial"]))

            # add general stuff
            if (name := device["name"]) is not None:
                device["nodename"] = slugify(name)
            else:
                device["nodename"] = "device-" + device["id"]

            request_id = data["object_changes"][0]["request_id"]
            device["motd"] = self.cfg.motd.format(timestamp=ts, request_id=request_id)

            device["deploy"] = device["status"]["name"] in {"Active", "Staged"}
            for tag in device["tags"]:
                if tag["name"] == "gpncfg-no-deploy":
                    device["deploy"] = False

            try:
                device["gateway"] = device["primary_ip4"]["parent"]["rel_gateway"][
                    "host"
                ]
            except TypeError:
                if device["role"]["name"] == "access":
                    log.warning(
                        "access device has no gateway {nodename} {serial})".format(
                            **device
                        )
                    )
                device["gateway"] = None

            device["addresses"] = {6: [], 4: []}
            if addr := device.get("primary_ip6"):
                device["addresses"][6].append(addr["host"])
            if addr := device.get("primary_ip4"):
                device["addresses"][4].append(addr["host"])

            log.debug(
                "found management addreses {addresses} for device {name} ({serial})".format(
                    **device
                )
            )

            # add data based on usecase
            if (
                device["role"]["name"] == "access switch"
                and device["device_type"]["manufacturer"]["name"] == "Juniper"
            ):
                # use json to escape special characters
                device["motd"] = json.dumps(device["motd"])

                # sort interfaces into physical and virtual ones as they are
                # treated very differently.
                device["physical_interfaces"] = list()
                device["virtual_interfaces"] = list()
                device["vids"] = list()

                for iface in device["interfaces"]:
                    iface = copy.deepcopy(iface)

                    if iface["type"] == "VIRTUAL":
                        if iface["untagged_vlan"] is None:
                            log.warning(
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

                        if (
                            device["device_type"]["model"].startswith("EX2300C")
                            and iface["untagged_vlan"]
                        ):
                            tagged.append(slugify(iface["untagged_vlan"]["name"]))

                        tagged.append("]")
                        iface["tagged_vlans_text"] = " ".join(tagged)

                        if (
                            iface["mode"] == "TAGGED"
                            and iface["tagged_vlans_text"] == "[ ]"
                        ):
                            iface["mode"] = None

                        # slugify the untagged vlan name
                        if iface["untagged_vlan"] is not None:
                            iface["untagged_vlan"]["name"] = slugify(
                                iface["untagged_vlan"]["name"]
                            )

                        device["physical_interfaces"].append(iface)

            elif usecase in [
                "core-switch_mellanox_sn2410",
                "core-switch_mellanox_sn3420",
            ]:
                config = copy.deepcopy(CUMULUS_CONFIG)

                config["system"]["hostname"] = device["nodename"]
                config["system"]["message"] = {"pre-login": device["motd"]}
                osnmp = {self.cfg.snmp_community: {"access": {"any": {}}}}
                config["system"]["snmp-server"]["readonly-community"] = osnmp
                config["system"]["snmp-server"]["readonly-community-v6"] = osnmp

                if device["nodename"] == "cumulus-test":
                    config["system"]["ssh-server"]["strict"] = "disabled"

                ifaces = dict()
                oneigh = dict()
                vlans = set()
                dhcp_relay_count = 0
                for iif in device["interfaces"]:
                    oif = {}
                    vlancfg = dict()
                    vlans.update(vlan["vid"] for vlan in iif["tagged_vlans"])
                    if vlan := iif["untagged_vlan"]:
                        vlans.add(vlan["vid"])
                        vlancfg["untagged"] = vlan["vid"]
                    if iif["tagged_vlans"]:
                        vlanstr = ",".join(
                            str(vlan["vid"]) for vlan in iif["tagged_vlans"]
                        )
                        vlancfg["vlan"] = {vlanstr: dict()}

                    if vlancfg and iif["type"] != "VIRTUAL":
                        oif["bridge"] = {"domain": {"br_default": vlancfg}}

                    if iaddrs := iif["ip_addresses"]:
                        oif["ip"] = {"address": {}}

                        if iif["vrf"]:
                            oif["ip"]["vrf"] = iif["vrf"]["name"]
                        elif iif["name"].startswith("eth"):
                            oif["ip"]["vrf"] = "mgmt"

                        if iif["_custom_field_data"].get("dhcp_client", False):
                            oif["ip"]["address"] = {"dhcp": {}}
                        else:
                            oaddrs = dict()
                            ogateways = {4: [], 6: []}
                            for addr in iaddrs:
                                oaddrs[addr["address"]] = dict()
                                try:
                                    g = addr["parent"]["rel_gateway"]
                                    ogateways[g["ip_version"]].append(g["host"])
                                except TypeError:
                                    pass

                            if iif["_custom_field_data"].get("set_gateway", False):
                                for ver in ogateways.values():
                                    if ver:
                                        oif["ip"]["gateway"] = {ver[0]: {}}

                            oif["ip"]["address"] = oaddrs
                    elif iif["vrf"]:
                        oif["ip"] = {"vrf": iif["vrf"]["name"]}
                    elif iif["name"].startswith("eth"):
                        oif["ip"] = {"vrf": "mgmt"}

                    if iif["type"] == "LAG":
                        oif["type"] = "bond"
                        obond = dict()
                        for iface in iif["member_interfaces"]:
                            obond[iface["name"]] = dict()
                        oif["bond"] = {"member": obond, "mode": "lacp"}
                    elif iif["type"] == "VIRTUAL":
                        oif["type"] = "svi"
                        if vlan := iif["untagged_vlan"]:
                            oif["vlan"] = vlan["vid"]

                    if iif["name"] == "lo":
                        for addr in iif["ip_addresses"]:
                            if addr["ip_version"] == 4:
                                config["router"]["bgp"]["router-id"] = addr["host"]
                        oif["type"] = "loopback"

                    for tag in iif["tags"]:
                        if tag["name"] == "unnumbered bgp":
                            oneigh[iif["name"]] = UNNUMBERED_BGP
                        elif tag["name"] == "send router advertisements":
                            oif["ip"]["neighbor-discovery"] = {
                                "router-advertisement": {"enable": "on"},
                                "rdnss": {
                                    "2a0e:c5c1:0:10::7": {},
                                    "2a0e:c5c1:0:10::8": {},
                                },
                            }
                        elif tag["name"] == "dhcp relay":
                            dhcp_relay_count += 1
                            config["service"]["dhcp-relay"]["default"]["interface"][
                                iif["name"]
                            ] = {}

                    ifaces[slugify(iif["name"])] = oif

                config["interface"] = ifaces
                if vlans:
                    vlanstr = ",".join(str(vlan) for vlan in vlans)
                    config["bridge"]["domain"]["br_default"]["vlan"][vlanstr] = {}
                else:
                    del config["bridge"]["domain"]["br_default"]["vlan"]

                stp_priority = device["_custom_field_data"].get(
                    "spanning_tree_priority"
                )
                if not stp_priority:
                    stp_priority = 4
                # no, .get alone is not enough, since nautobot can also contain a Null value here

                config["bridge"]["domain"]["br_default"]["stp"]["priority"] = (
                    stp_priority * 4096
                )

                if dhcp_relay_count == 0:
                    config["service"].pop("dhcp-relay")

                ousers = dict()

                for user in self.cfg.login.user:
                    okeys = dict()
                    for i, key in enumerate(
                        user["ed25519"] + user["ecdsa"] + user["rsa"]
                    ):
                        parts = key.split(" ")
                        okeys[user["name"] + str(i)] = {
                            "type": parts[0],
                            "key": parts[1],
                        }
                    ousercfg = {
                        "role": "system-admin",
                        "ssh": {"authorized-key": okeys},
                    }
                    if user["password"]:
                        ousercfg["hashed-password"] = user["password"]
                    else:
                        ousercfg["hashed-password"] = self.cfg.login.root.sha512
                    ousers[user["name"]] = ousercfg

                ousers["cumulus"] = {
                    "role": "system-admin",
                    "hashed-password": self.cfg.login.root.sha512,
                }

                for routing in device["bgp_routing_instances"]:
                    config["router"]["bgp"]["autonomous-system"] = routing[
                        "autonomous_system"
                    ]["asn"]
                    for endpoint in routing["endpoints"]:
                        peer = endpoint["peer"]
                        oneigh[peer["source_ip"]["host"]] = {
                            "address-family": {
                                "ipv{}-unicast".format(
                                    peer["source_ip"]["ip_version"]
                                ): {"enable": "on"}
                            },
                            "remote-as": peer["autonomous_system"]["asn"],
                            "type": "numbered",
                        }
                config["vrf"]["default"]["router"]["bgp"]["neighbor"] = oneigh
                if not oneigh:
                    log.warning(
                        "routing instance has no neighbors {nodename} {serial}".format(
                            **device
                        )
                    )

                ostatic = dict()

                for prefix in device["rel_reject_routes"]:
                    ostatic[prefix["prefix"]] = {
                        "via": {"reject": {"type": "reject"}},
                        "address-family": f"ipv{prefix['ip_version']}-unicast",
                    }

                config["vrf"]["default"]["router"]["static"] = ostatic

                config["system"]["aaa"]["user"] = ousers
                device["config"] = config
                # [{"set": config}]

            elif usecase == "switch_arista_sampelModel":
                for iface in device["interfaces"]:
                    tagged = [str(vlan["vid"]) for vlan in iface["tagged_vlans"]]
                    if len(tagged) != 0:
                        iface["tagged_vlans"] = ",".join(tagged)
                    else:
                        iface["tagged_vlans"] = "none"
            elif usecase == "switch_arista_1234":
                print("doing other stuff")

        return data
