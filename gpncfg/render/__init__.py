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


class ConfigWithContext:
    config: str
    context: dict()

    def __init__(self):
        self.config = None
        self.context = dict()


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
            cwc = ConfigWithContext()
            cwc.context["config"] = self.cfg.__dict__
            cwc.context["vlans"] = data["vlans"]
            cwc.context["device"] = device

            if usecase == "core-switch_mellanox_sn2410":
                cwc.config = json.dumps(
                    [{"set": device["config"]}], indent=2, sort_keys=True
                )
            else:
                try:
                    template_usecase = usecase if not usecase.startswith("access-switch_juniper_ex3300") else "access-switch_juniper_ex3300-48p"
                    template = self.j2.get_template(template_usecase + ".j2")
                    cwc.config = template.render(cwc.context)
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
