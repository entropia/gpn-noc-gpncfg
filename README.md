# GPN Config-Generator

gpncfg generates switch and router configs based on information from nautobot.
This tool is used by the [Gulaschprogrammiernacht](https://gulas.ch) Network
Operation Center to create the configuration for most devices.

Inspired by [ravens](https://github.com/blackdotraven) config-generator for
GPN21 and Internetmanufaktur's [imfcfg](https://github.com/lub-dub/imfcfg)

## Development

### Directory Layout

* `dev-env.sh` sets up the environment
* `data` example config files
  * `data/gpncfg.toml` per user settings and secrets for gpncfg
  * `data/testuser2_*` ssh keys for testing configuration and deployment
  * `data/login.toml` login file specifying root and user login data
* `generated-configs` default output dir for generated device configs
* `gpncfg` python module with gpncfg source code
  * `gpncfg/__init__.py` entry point for libraries
  * `gpncfg/__main__.py` entry point for module execution
  * `gpncfg/config` config parsing which affects gpncfgs behavior
    * `gpncfg/config/event.toml` event specific configuration
  * `gpncfg/data_provider` information fetching from source of truth
  * `gpncfg/fiddle/__init__.py` mutate and adjust data structures of network data
  * `gpncfg/fiddle/cumulus.py` template data structure for cumulus devices
  * `gpncfg/main_action` driver and glue between other components
  * `gpncfg/render` render the templates using the nautobot data
    * `gpncfg/render/templates` switch/router config templates
* `pyproject.toml` packaging and build definitions
* `README.md` human readable project information

### Setup

gpncfg is using poetry to manage dependencies and packaging. Use the provided
`dev-env.sh` script to set up a development environemnt. This will provide a
python [virtual environment](https://packaging.python.org/en/latest/guides/installing-using-pip-and-virtual-environments/#activate-a-virtual-environment)
with all the dependencies and install the pre-commit hooks. The virtual
environment needs to be activated by sourcing the activation script at
`<venv>/bin/activate`. Versions for shells other than bash are provided as well.

Inside the venv, run `gpncfg` or `python3 -m gpncfg` to execute the code.

To provide gpncfg with necessary configuration, for example nautobot
credentials, copy the example config file into your config directory and edit
it:

``` bash
mkdir $XDG_CONFIG_HOME/gpncfg
cp data/gpncfg.toml.example $XDG_CONFIG_HOME/gpncfg/gpncfg.toml
eval $EDITOR  $XDG_CONFIG_HOME/gpncfg/gpncfg.toml
# see data/login.toml for an example login file
eval $EDITOR  $XDG_CONFIG_HOME/gpncfg/login.toml
```
