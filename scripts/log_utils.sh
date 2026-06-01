#!/usr/bin/env bash

## Output color
RED='\033[1;91m'
GREEN='\033[1;92m'
YELLOW='\033[1;93m'
BOLD='\033[1m'
NC='\033[0m'

function print_info() {
	echo -e "[INFO] $1 ${NC}"
}

function print_error() {
	echo -e "${RED}[ERROR] $1 ${NC}"
}

function print_green() {
	echo -e "${GREEN}[INFO] $1 ${NC}"
}

function print_warn() {
	echo -e "${YELLOW}[WARN] $1 ${NC}"
}