#!/usr/bin/env bash

source $HITOS_SETUP_SCRIPT_PATH/log_utils.sh

function _hitos_get_gps_port() {
	# export IMU_PORT="/dev/$(dmesg | grep "tty" | sed -En 's/.*usb 1-[0-9]: FTDI USB Serial Device converter now attached to (port:)?((ttyUSB[0-9])).*/\2/p')"

    local port
    port=$(readlink -f /dev/serial/by-id/usb-FTDI_TTL232R-3V3_FTCEUT0Q-if00-port0 2>/dev/null)
    
	[ -z "$port" ] && port="/dev/ttyUSB0"
    export GPS_PORT="$port"
}

function _hitos_get_dht22_port() {
	# export DHT22_PORT="/dev/$(dmesg | grep "tty" | sed -En 's/.*usb 1-[0-9]: ch341-uart converter now attached to (port:)?((ttyUSB[0-9])).*/\2/p')"
    local port
    port=$(readlink -f /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 2>/dev/null)
    
	[ -z "$port" ] && port="/dev/ttyUSB0"
    export DHT22_PORT="$port"
}



## IP and port configuration
function _hitos_export_ip() {
	_hitos_get_gps_port
	_hitos_get_dht22_port
    
	export HITOS_OBC_IP=$OWN_IP
    		# LIDAR IP ORIGINAL
	export HITOS_LIDAR_IP=169.254.252.240 			# LIDAR IP ORIGINAL
	export HITOS_LIDAR_IP_DEST=$(ip addr show enp2s0 | grep "inet " | awk '{print $2}' | cut -d/ -f1)

	export HITOS_GPS_PORT=$GPS_PORT
	
	export MULTIESPECTRAL_VISIBLE_IP="192.168.4.5"
	export MULTIESPECTRAL_LWIR_IP="192.168.4.6"
	
	export HITOS_WIFI_IP=192.168.1.151 # Static IP configured 
}