# GPN Config-Generator

gpncfg generates switch and router configs based on information from netbox/
nautobot. This tool is used by the [Gulaschprogrammiernacht](https://gulas.ch)
Network Operation Center to create the configuration for most devices.

Inspired by [ravens](https://github.com/blackdotraven) config-generator for
GPN21 and Internetmanufaktur's [imfcfg](https://github.com/lub-dub/imfcfg)

``` bash
# setup and activatge a virtual python environment
python3 -mvenv ./venv/
source venv/bin/activate

# install poetry and dependencies
pip3 install poetry
poetry install

# setup pre-commit hooks for autoformatting
pre-commit install
```
