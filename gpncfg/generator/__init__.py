#!/usr/bin/env python3

import copy
import datetime
import json
import logging
import os
from pprint import pprint

import jinja2

log = logging.getLogger(__name__)


def get_template_path():
    cur_dir = os.path.dirname(__file__)
    epath = os.path.join(cur_dir, "templates")
    return epath


TRANS_SLUG = str.maketrans(" ", "-", "()")


def slugify(text):
    return text.lower().translate(TRANS_SLUG)


class Generator:
    def __init__(self, cfg, data):
        self.configs = {}

        self.cfg = cfg
        self.data = data

        self.j2 = jinja2.Environment(
            loader=jinja2.FileSystemLoader(searchpath=[get_template_path()]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def fiddle(self):
        log.info("fiddling data")
        ts = (
            datetime.datetime.utcnow()
            .replace(microsecond=0, tzinfo=datetime.timezone.utc)
            .isoformat()
        )
        self.sanetize_vlans()
        self.fiddle_devices(ts)

    def sanetize_vlans(self):
        for vlan in self.data["vlans"]:
            vlan["name"] = slugify(vlan["name"])

    def fiddle_devices(self, ts):
        for device in self.data["devices"]:
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
            if (name := device["name"]) != None:
                device["hostname"] = name
            else:
                device["hostname"] = "device-" + device["id"]

            device["motd"] = self.cfg.motd.format(timestamp=ts)

            for iface in device["interfaces"]:
                tagged = [str(vlan["vid"]) for vlan in iface["tagged_vlans"]]
                if len(tagged) != 0:
                    iface["tagged_vlans"] = ",".join(tagged)
                else:
                    iface["tagged_vlans"] = "none"

            # add data based on usecase
            if usecase == "switch_arista_sampelModel":
                print("doing some stuff")

            elif usecase == "switch_arista_1234":
                print("doing other stuff")

    def generate(self):
        log.info("generating configs")

        missing_templates = []

        for device in self.data["devices"]:
            usecase = device["usecase"]

            log.debug(
                "generating config for serial {serial}".format(
                    name=device["name"],
                    serial=device["serial"],
                    usecase=usecase,
                )
            )

            context = dict()
            context["config"] = self.cfg.__dict__
            context["vlans"] = self.data["vlans"]
            context["device"] = device

            try:
                template = self.j2.get_template(usecase + ".j2")
                self.configs[device["serial"]] = template.render(context)
            except jinja2.TemplateNotFound as e:
                log.warn(
                    "failed to find template {} for device {}".format(
                        usecase, device["serial"]
                    )
                )
                if not usecase in missing_templates:
                    missing_templates.append(usecase)

        if missing_templates != []:
            log.error(
                "failed to load templates for these usecases: {}".format(
                    ", ".join(missing_templates)
                )
            )
