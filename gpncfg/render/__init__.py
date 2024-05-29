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


class Conglomerate:
    config: str
    context: dict()
    device: dict()
    path: str
    config: str

    def __init__(self, cfg, vlans, device):
        self.cfg = cfg
        self.device = device
        self.context = dict()
        self.context["config"] = self.cfg.__dict__
        self.context["vlans"] = vlans
        self.context["device"] = device
        self.config = None

    def set_config(self, config):
        self.config = config


class Renderer:
    def __init__(self, cfg):
        self.cfg = cfg

        self.j2 = jinja2.Environment(
            loader=jinja2.FileSystemLoader(searchpath=[get_template_path()]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, data):
        log.info("rendering configs")

        configs = dict()

        missing_templates = []

        for device in data["devices"]:
            usecase = device["usecase"]

            log.debug(
                "rendering config for serial {serial}".format(
                    name=device["name"],
                    serial=device["serial"],
                    usecase=usecase,
                )
            )
            cwc = Conglomerate(self.cfg, data["vlans"], device)

            if usecase == "core-switch_mellanox_sn2410":
                cwc.set_config(
                    json.dumps([{"set": device["config"]}], indent=2, sort_keys=True)
                )
            else:
                try:
                    template = self.j2.get_template(usecase + ".j2")
                    cwc.set_config(template.render(cwc.context))
                except jinja2.TemplateNotFound as e:
                    log.warn(
                        "failed to find template {} for device {}".format(
                            usecase, device["serial"]
                        )
                    )
                    if not usecase in missing_templates:
                        missing_templates.append(usecase)

            configs[device["id"]] = cwc

        if missing_templates != []:
            log.error(
                "failed to load templates for these usecases: {}".format(
                    ", ".join(missing_templates)
                )
            )

        return configs
