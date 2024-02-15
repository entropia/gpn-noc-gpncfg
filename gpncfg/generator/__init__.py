#!/usr/bin/env python3

import copy
import datetime
import json
import logging
import os

import jinja2

log = logging.getLogger(__name__)


class Generator:
    def __init__(self, cfg, data):
        self.configs = {}

        self.cfg = cfg
        self.data = data

        self.context = {}
        self.context["config"] = self.cfg.__dict__
        self.context["vlan_list"] = data["vlan_list"]

        trans = str.maketrans(" ", "-", "()")
        for vlan in range(len(self.context["vlan_list"])):
            self.context["vlan_list"][vlan]["name"] = self.context["vlan_list"][vlan][
                "name"
            ].translate(trans)

        self.j2 = jinja2.Environment(
            loader=jinja2.FileSystemLoader(searchpath=["./templates/"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate(self):
        log.info("generating configs")
        template = self.j2.get_template("switch_arista.j2")

        ts = (
            datetime.datetime.utcnow()
            .replace(microsecond=0, tzinfo=datetime.timezone.utc)
            .isoformat()
        )

        for netbox in self.data["device_list"]:
            extra = dict()

            if (name := netbox["name"]) != None:
                extra["hostname"] = name
            else:
                extra["hostname"] = "device-" + netbox["id"]

            if netbox["serial"] == "":
                extra["serial"] = "fallback-serial-" + netbox["id"]
            else:
                extra["serial"] = netbox["serial"]

            if netbox["location"] == None:
                extra["snmp_location"] = self.cfg.snmp_location
            else:
                extra["snmp_location"] = netbox["location"]["name"]

            extra["motd"] = self.cfg.motd.format(timestamp=ts)

            ctx = copy.deepcopy(self.context)
            ctx["netbox"] = netbox
            ctx["extra"] = extra

            self.configs[extra["serial"]] = template.render(ctx)
