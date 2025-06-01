#!/usr/bin/env python3

CUMULUS_CONFIG = {
    "bridge": {"domain": {"br_default": {"vlan": {}, "stp": {}}}},
    "interface": {},
    "system": {
        "aaa": {"user": {}},
        "api": {
            "state": "enabled",
            "certificate": "web",
        },
        "config": {
            "auto-save": {"state": "enabled"},
            "snippet": {
                "neighmgr": {
                    "content": "[main]\nsetsrcipv4: 100.64.0.1\n",
                    "file": "/etc/cumulus/neighmgr.conf",
                    "services": {
                        "neighmgr": {"action": "restart", "service": "neighmgrd"}
                    },
                },
                "sudoers": {
                    "content": "%sudo ALL=(ALL:ALL) NOPASSWD: ALL",
                    "file": "/etc/sudoers.d/nopasswd",
                    "permissions": "0440",
                },
            },
        },
        "reboot": {"mode": "cold"},
        "security": {
            "encryption": {
                "db": {
                    "state": "disabled",
                },
            },
        },
        "ssh-server": {},
        "snmp-server": {
            "state": "enabled",
            "listening-address": {
                "all": {},
                "all-v6": {},
            },
        },
        "ssh-server": {
            "state": "enabled",
        },
        "syslog": {
            "server": {
                "logging.noc.gulas.ch": {},
            },
        },
        "wjh": {
            "channel": {"forwarding": {"trigger": {"l2": {}, "l3": {}, "tunnel": {}}}},
            "enable": "on",
        },
    },
    "service": {
        "dns": {
            "default": {
                "search": {
                    "noc.gulas.ch": {},
                },
                "server": {
                    "151.216.64.55": {},
                    "151.216.64.56": {},
                    "2a0e:c5c1:0:10::7": {},
                    "2a0e:c5c1:0:10::8": {},
                },
            }
        },
        "dhcp-relay": {
            "default": {
                "server": {
                    "45.140.180.227": {},
                    "45.140.180.228": {},
                },
                "interface": {},
            },
        },
        "ntp": {
            "default": {
                "server": {
                    "0.cumulusnetworks.pool.ntp.org": {},
                    "1.cumulusnetworks.pool.ntp.org": {},
                    "2.cumulusnetworks.pool.ntp.org": {},
                    "3.cumulusnetworks.pool.ntp.org": {},
                },
            },
        },
    },
    "router": {
        "bgp": {
            "enable": "on",
        },
        "policy": {
            "prefix-list": {
                "EVENTNET4": {
                    "type": "ipv4",
                    "rule": {
                        "10": {
                            "action": "permit",
                            "match": {
                                "151.218.0.0/18": {
                                    "max-prefix-len": 32,
                                    "min-prefix-len": 19,
                                }
                            },
                        },
                        "20": {
                            "action": "permit",
                            "match": {
                                "45.140.180.0/24": {
                                    "max-prefix-len": 32,
                                    "min-prefix-len": 25,
                                }
                            },
                        },
                    },
                },
                "EVENTNET6": {
                    "type": "ipv6",
                    "rule": {
                        "10": {
                            "action": "permit",
                            "match": {
                                "2a0e:c5c1::/48": {
                                    "max-prefix-len": 128,
                                    "min-prefix-len": 49,
                                }
                            },
                        }
                    },
                },
            },
            "route-map": {
                "EVENTNET": {
                    "rule": {
                        "10": {
                            "action": {"permit": {}},
                            "match": {
                                "type": "ipv4",
                                "ip-prefix-list": "EVENTNET4",
                            },
                        },
                        "11": {
                            "action": {"permit": {}},
                            "match": {
                                "type": "ipv6",
                                "ip-prefix-list": "EVENTNET6",
                            },
                        },
                    }
                },
            },
        },
    },
    "vrf": {
        "default": {
            "router": {
                "bgp": {
                    "address-family": {
                        "ipv4-unicast": {
                            "enable": "on",
                            "redistribute": {
                                "connected": {"enable": "on", "route-map": "EVENTNET"},
                                "static": {"enable": "on"},
                            },
                        },
                        "ipv6-unicast": {
                            "enable": "on",
                            "redistribute": {
                                "connected": {"enable": "on", "route-map": "EVENTNET"},
                                "static": {"enable": "on"},
                            },
                        },
                    },
                    "enable": "on",
                    "neighbor": {},
                },
            },
        },
    },
}

UNNUMBERED_BGP = {
    "address-family": {
        "ipv4-unicast": {"enable": "on"},
        "ipv6-unicast": {"enable": "on"},
    },
    "remote-as": "external",
    "type": "unnumbered",
}
