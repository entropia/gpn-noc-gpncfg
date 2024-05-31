#!/usr/bin/env python3

import json
import logging
import os

import jinja2

log = logging.getLogger(__name__)

TEMPLATE_MAP = {
    "access-switch_juniper_ex2200c-12t": "access-juniper-ex3300.j2",
    "access-switch_juniper_ex2300c-12p": "access-juniper-ex2_00c.j2",
    "access-switch_juniper_ex3300-24t": "access-juniper-ex3300.j2",
    "access-switch_juniper_ex3300-48p": "access-juniper-ex3300.j2",
    "core-switch_mellanox_sn2410": "json",
}


def get_template_path():
    cur_dir = os.path.dirname(__file__)
    epath = os.path.join(cur_dir, "templates")
    return epath


class Conglomerate:
    config: str | None
    context: dict
    device: dict
    path: str

    def __init__(self, cfg, data, device):
        self.cfg = cfg
        self.device = device
        self.context = dict()
        self.context["config"] = self.cfg.__dict__
        self.context["vlans"] = data["vlans"]
        self.context["device"] = device
        self.config = None
        self.data = data

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

        missing_usecases = set()

        for device in data["devices"]:
            usecase = device["usecase"]

            log.debug(
                "rendering config for serial {serial}".format(
                    serial=device["serial"],
                )
            )
            cwc = Conglomerate(self.cfg, data, device)

            template_name = TEMPLATE_MAP.get(usecase)
            if not template_name:
                log.warning(
                    "failed to find template for usecase {} when rendering {nodename} {serial}".format(
                        usecase, **device
                    )
                )
                missing_usecases.add(usecase)
            elif template_name == "json":
                cwc.set_config(
                    json.dumps([{"set": device["config"]}], indent=2, sort_keys=True)
                )
            else:
                try:
                    template = self.j2.get_template(template_name)
                    cwc.set_config(template.render(cwc.context))
                except jinja2.TemplateNotFound as e:
                    raise Exception(
                        "failed to find jinja2 template {} for usecase {} for device {serial} {nodename}".format(
                            template_name, usecase, **device
                        )
                    )

            configs[device["id"]] = cwc

        if missing_usecases:
            log.error(
                f"failed to load templates for these usecases: {missing_usecases}"
            )

        return configs
