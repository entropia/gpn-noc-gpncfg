#!/usr/bin/env python3

import copy
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

        # TODO is this really how we want to do things? maybe load them via
        # configargparse, maybe load them somewhere else?
        with open("./db/event-config.json", "rb") as file:
            self.context["event"] = json.load(file)

        self.j2 = jinja2.Environment(
            loader=jinja2.FileSystemLoader(searchpath=["./templates/"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate(self):
        log.info("generating configs")
        template = self.j2.get_template("switch_arista.j2")

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
                extra["snmp_location"] = self.context["event"]["snmp_location"]
            else:
                extra["snmp_location"] = netbox["location"]["name"]

            ctx = copy.deepcopy(self.context)
            ctx["netbox"] = netbox
            ctx["extra"] = extra

            self.configs[extra["serial"]] = template.render(ctx)
