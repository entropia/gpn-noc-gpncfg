#!/usr/bin/env bash

say() {
	echo "=== $*"
}

error() {
	echo "error: $*" >&2
}

fatal() {
	error "fatal: $*"
	exit 1
}

say "hello, I am setting up your development environment for you!"

if ! command -v python3 > /dev/null; then
	fatal "python3 not found. please install python3 using your preferred package manager"
fi

say "cleaning up old venv"
rm -r venv

say "creating the venv"
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate

say "installing poetry"
pip3 install "poetry == 1.8.2"

say "installing dependencies"
poetry install --sync

say "installing the pre-commit hook"
pre-commit install

say "all done!"
say "you can use \`source venv/bin/activate\` to enter the python environment and \`deactivate\` to leave afterwards"
