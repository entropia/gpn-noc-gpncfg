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
        "router": {
            "bgp": {
                "enable": "enabled",
            },
            "policy": {
                "prefix-list": {
                    "EVENTNET4": {
                        "rule": {
                            "10": {
                                "action": "permit",
                                "match": {
                                    "151.216.64.0/19": {
                                        "max-prefix-len": 32,
                                        "min-prefix-len": 20,
                                    }
                                },
                            }
                        },
                        "type": "ipv4",
                    },
                    "EVENTNET6": {
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
                        "type": "ipv6",
                    },
                },
                "route-map": {
                    "EVENTNET": {
                        "rule": {
                            "10": {
                                "action": {"permit": {}},
                                "match": {
                                    "ip-prefix-list": "EVENTNET4",
                                    "type": "ipv4",
                                },
                            },
                            "11": {
                                "action": {"permit": {}},
                                "match": {
                                    "ip-prefix-list": "EVENTNET6",
                                    "type": "ipv6",
                                },
                            },
                        }
                    }
                },
            },
        },
    },
    "vrf": {
        "default": {
            "loopback": {"ip": {"address": {}}},
            "router": {
                "bgp": {
                    "address-family": {
                        "ipv4-unicast": {
                            "enable": "on",
                            "redistribute": {
                                "connected": {"enable": "on", "route-map": "EVENTNET"}
                            },
                        },
                        "ipv6-unicast": {
                            "enable": "on",
                            "redistribute": {
                                "connected": {"enable": "on", "route-map": "EVENTNET"}
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
