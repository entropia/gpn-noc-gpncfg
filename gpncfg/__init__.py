#!/usr/bin/env python3

import logging

import colorlog

from .main_action import run

log = logging.getLogger(__name__)


def color_handler():
    handler = colorlog.StreamHandler()
    handler.setFormatter(
        colorlog.ColoredFormatter(
            "%(log_color)s%(levelname)s:%(name)s:%(reset)s%(message_log_color)s%(message)s",
            log_colors={
                "DEBUG": "light_black",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "red",
            },
            secondary_log_colors={
                "message": {
                    "DEBUG": "light_black",
                    "CRITICAL": "red",
                }
            },
        )
    )
    return handler
