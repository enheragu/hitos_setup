#!/usr/bin/env bash

source $HITOS_SETUP_SCRIPT_PATH/log_utils.sh

function _hitos_get_gps_port() {
    local port
    # u-blox 7 GPS/GNSS Receiver (USB ID 1546:01a7)
    port=$(readlink -f /dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00 2>/dev/null)

    [ -z "$port" ] && port="/dev/ttyACM0"
    export GPS_PORT="$port"
}

function _hitos_get_dht22_port() {
    local port
    # CH340 USB-serial (ESP8266 with DHT22 sensor)
    port=$(readlink -f /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 2>/dev/null)

    [ -z "$port" ] && port="/dev/ttyUSB0"
    export DHT22_PORT="$port"
}


function _hitos_get_lidar_ip() {
    # Always use the configured static IP. The ouster_ros driver handles its own
    # retries, so there is no need to arp-scan: doing so creates a race condition
    # on boot where the link-local address (169.254.x.x) appears before the
    # static IP, causing the driver to connect to the wrong address permanently.
    echo "192.168.4.4"
}

## IP and port configuration
function _hitos_export_ip() {
    _hitos_get_gps_port
    _hitos_get_dht22_port

    export HITOS_LIDAR_IP=$(_hitos_get_lidar_ip)

    export HITOS_GPS_PORT=$GPS_PORT
    export HITOS_DHT22_PORT=$DHT22_PORT

    export MULTIESPECTRAL_VISIBLE_IP="192.168.4.5"
    export MULTIESPECTRAL_LWIR_IP="192.168.4.6"

    export HITOS_WIFI_IP=192.168.1.151
}


function _hitos_setup_iptables() {
    local ips=(
        "${MULTIESPECTRAL_VISIBLE_IP:-192.168.4.5}"
        "${MULTIESPECTRAL_LWIR_IP:-192.168.4.6}"
        "${HITOS_LIDAR_IP:-192.168.4.4}"
    )

    iptables -N HITOS_RX 2>/dev/null || iptables -F HITOS_RX
    iptables -N HITOS_TX 2>/dev/null || iptables -F HITOS_TX

    iptables -C INPUT  -i eth0 -j HITOS_RX 2>/dev/null || iptables -I INPUT  -i eth0 -j HITOS_RX
    iptables -C OUTPUT -o eth0 -j HITOS_TX 2>/dev/null || iptables -I OUTPUT -o eth0 -j HITOS_TX

    for ip in "${ips[@]}"; do
        iptables -A HITOS_RX -s "$ip" -j RETURN
        iptables -A HITOS_TX -d "$ip" -j RETURN
    done

    print_green "HITOS iptables rules installed for: ${ips[*]}"

    # Add link-local route only if the Ouster is still using its factory link-local IP.
    # Once reconfigured to 192.168.4.4 this block is a no-op (ping won't match 169.254.*).
    if ping -c 1 -W 1 169.254.46.138 &>/dev/null 2>&1; then
        if ! ip route show dev eth0 | grep -q "^169\.254\."; then
            ip route add 169.254.0.0/16 dev eth0 2>/dev/null \
                && print_green "Added 169.254.0.0/16 route on eth0 (legacy link-local Ouster)" \
                || print_warn "Could not add 169.254.0.0/16 route (already exists?)"
        fi
    fi
}


## Check if setup was already sourced and env vars are loaded. If not, load them.
function _hitos_check_setup() {
	if [[ $ROS_CONFIGURED -eq 0 ]]
	then
		hitos_ros_setup
	else
		print_info "ROS ws was already configured, not resourcing it."
	fi
}