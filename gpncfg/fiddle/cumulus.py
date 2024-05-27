#!/usr/bin/env python3

CUMULUS_CONFIG = {
    "bridge": {"domain": {"br_default": {"vlan": {}}}},
    "interface": {},
    "system": {
        "aaa": {"user": {}},
        "api": {"certificate": "web"},
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
        "reboot": {"mode": "cold"},
        "ssh-server": {},
        "wjh": {
            "channel": {"forwarding": {"trigger": {"l2": {}, "l3": {}, "tunnel": {}}}},
            "enable": "on",
        },
    },
    "service": {
        "dns": {
            "default": {
                "server": {
                    # https://libreops.cc/radicaldns.html server 1
                    "2a01:4f8:1c0c:82c0::1": {},
                    # https://libreops.cc/radicaldns.html server 2
                    "2a03:f80:30:192:71:166:92:1": {},
                }
            }
        }
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
                                "151.216.64.0/19": {
                                    "max-prefix-len": 32,
                                    "min-prefix-len": 20,
                                }
                            },
                        }
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
            "loopback": {"ip": {"address": {}}},
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
