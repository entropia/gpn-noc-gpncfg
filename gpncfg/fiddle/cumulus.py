#!/usr/bin/env python3

CUMULUS_CONFIG = {
    "bridge": {"domain": {"br_default": {"vlan": {}}}},
    "interface": {},
    "system": {
        "aaa": {"user": {}},
        "config": {
            "auto-save": {"enable": "on"},
            "snippet": {
                "neighmgr": {
                    "content": "[main]\nsetsrcipv4: 100.64.0.1\n",
                    "file": "/etc/cumulus/neighmgr.conf",
                    "services": {
                        "neighmgr": {"action": "restart", "service": "neighmgrd"}
                    },
                }
            },
        },
        "control-plane": {
            "acl": {
                "acl-default-dos": {"inbound": {}},
                "acl-default-whitelist": {"inbound": {}},
            }
        },
        "reboot": {"mode": "cold"},
        "ssh-server": {},
        "wjh": {
            "channel": {"forwarding": {"trigger": {"l2": {}, "l3": {}, "tunnel": {}}}},
            "enable": "on",
        },
    },
    "vrf": {
        "default": {"loopback": {"ip": {"address": {}}}},
    },
}
