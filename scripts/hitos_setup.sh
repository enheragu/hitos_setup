#!/usr/bin/env bash

## Path of current file
SOURCE=${BASH_SOURCE[0]}
while [ -L "$SOURCE" ]; do
  DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )
  SOURCE=$(readlink "$SOURCE")
  [[ $SOURCE != /* ]] && SOURCE=$DIR/$SOURCE
done
export HITOS_SETUP_SCRIPT_PATH=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )

export ROS_CONFIGURED=0

source $HITOS_SETUP_SCRIPT_PATH/log_utils.sh
source $HITOS_SETUP_SCRIPT_PATH/hitos_private_functions.sh


function bind_fkeys() { # Test output with showkey -a command
if [[ $- == *i* ]]; then

	bind -x '"\e[15~":"hitos_launch_gps"' 					# F5
	bind -x '"\e[17~":"hitos_launch_lidar"' 				# F6
	bind -x '"\e[18~":"hitos_launch_temperature"'    		# F7
	bind -x '"\e[19~":"hitos_launch_multiespectral"'        # F8
	bind -x '"\e[20~":"hitos_launch_all"'	    # F9	
	# bind -x '"\e[21~":"hitos_check_sensors"' 				# F10		
else
    echo "Non interactive shell, not binding keys for command shortcuts"
fi
}


function hitos_ros_setup() {
    bind_fkeys
    _hitos_export_ip
    source /home/arvc/ros2_ws/install/setup.bash

    # Status indicators
    local OK="\033[1;92m OK \033[0m"
    local FAIL="\033[1;91m -- \033[0m"
    local WARN="\033[1;93m ?? \033[0m"

    local gps_st dht22_st lidar_st vis_st lwir_st disk_st
    test -e "$HITOS_GPS_PORT"   && gps_st="$OK"   || gps_st="$FAIL"
    test -e "$HITOS_DHT22_PORT" && dht22_st="$OK"  || dht22_st="$FAIL"
    ping -c1 -W1 -q "$HITOS_LIDAR_IP"             &>/dev/null && lidar_st="$OK"  || lidar_st="$WARN"
    ping -c1 -W1 -q "$MULTIESPECTRAL_VISIBLE_IP"  &>/dev/null && vis_st="$OK"    || vis_st="$WARN"
    ping -c1 -W1 -q "$MULTIESPECTRAL_LWIR_IP"     &>/dev/null && lwir_st="$OK"   || lwir_st="$WARN"
    grep -qs '/media/arvc/DATASETS ' /proc/mounts              && disk_st="$OK"   || disk_st="$WARN"

    local host_ip
    host_ip=$(hostname -I 2>/dev/null | awk '{print $1}')

    printf "\n\033[1;93m"
    printf "  █████   █████     ███     ███████████      ███████       █████████  \n"
    printf " ▒▒███   ▒▒███     ▒▒▒     ▒█▒▒▒███▒▒▒█    ███▒▒▒▒▒███    ███▒▒▒▒▒███\n"
    printf "  ▒███    ▒███      ███    ▒   ▒███  ▒    ███     ▒▒███  ▒███    ▒▒▒ \n"
    printf "  ▒███████████     ▒███        ▒███      ▒███      ▒███  ▒▒█████████  \n"
    printf "  ▒███▒▒▒▒▒███     ▒███        ▒███      ▒███      ▒███   ▒▒▒▒▒▒▒▒███ \n"
    printf "  ▒███    ▒███     ▒███        ▒███      ▒▒███     ███    ███    ▒███ \n"
    printf "  █████   █████    █████       █████      ▒▒▒███████▒    ▒▒█████████  \n"
    printf " ▒▒▒▒▒   ▒▒▒▒▒    ▒▒▒▒▒       ▒▒▒▒▒         ▒▒▒▒▒▒▒       ▒▒▒▒▒▒▒▒▒  \n"
    printf " Heterogeneous  Integrated       Thermal-Optical            System   \n"
    printf "\033[0m\n"
    # Two-column layout: sensors left, cameras+disk right
    # Format: label(8) value(20) status  |  label(9) value(18) status
    _row() {
        printf "  \033[1m%-8s\033[0m %-20s %b     \033[1m%-9s\033[0m %-18s %b\n" \
            "$1" "$2" "$3" "$4" "$5" "$6"
    }
    _row "GPS"   "$HITOS_GPS_PORT"   "$gps_st"   "Vis.Cam" "$MULTIESPECTRAL_VISIBLE_IP" "$vis_st"
    _row "DHT22" "$HITOS_DHT22_PORT" "$dht22_st"  "LWIR Cam" "$MULTIESPECTRAL_LWIR_IP"  "$lwir_st"
    _row "LiDAR" "$HITOS_LIDAR_IP"   "$lidar_st"  "DATASETS" "/media/arvc/DATASETS"      "$disk_st"
    unset -f _row

    printf "\n"
    printf "  \033[1m%-14s\033[0m  \033[1;94mhttp://%s:5050\033[0m    |    \033[1;94mhttp://arvc-multiespectral:5050\033[0m\n" "Web GUI for Manager"  "$host_ip"
    printf "  \033[1m%-14s\033[0m  \033[1;94mhttp://%s:5051\033[0m    |    \033[1;94mhttp://arvc-multiespectral:5051\033[0m\n" "Web GUI for Cameras"  "$host_ip"
    printf "\n"

    export ROS_CONFIGURED=1
}

function hitos_make()
{
    _hitos_check_setup

    local _SERVICES=(hitos_sensors hitos_cameras hitos_camera_gui hitos_web_manager)
    local _was_active=()

    print_info "Stopping ROS services to free memory for compilation..."
    local _stop_pids=()
    for svc in "${_SERVICES[@]}"; do
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            _was_active+=("$svc")
            sudo -n /bin/systemctl stop "${svc}.service" 2>/dev/null &
            _stop_pids+=($!)
        fi
    done
    for i in "${!_stop_pids[@]}"; do
        if wait "${_stop_pids[$i]}"; then
            print_info "  · Stopped ${_was_active[$i]}"
        else
            print_warn "Could not stop ${_was_active[$i]} (no sudo?)"
        fi
    done
    ## Secuential compiling for tigh resources in raspberry pi
    (cd ~/ros2_ws && MAKEFLAGS="-j2" colcon build \
        --executor sequential \
        --symlink-install \
        --cmake-args -DCMAKE_BUILD_TYPE=Release)
    local _build_exit=$?

    if [[ ${#_was_active[@]} -gt 0 ]]; then
        print_info "Restarting services that were active: ${_was_active[*]}"
        for svc in "${_was_active[@]}"; do
            if sudo -n /bin/systemctl restart "${svc}.service" 2>/dev/null; then
                print_info "  · Restarted $svc"
            else
                print_warn "Could not restart $svc (no sudo?)"
            fi
        done
    fi

    return $_build_exit
}

# ---- Launch shortcuts ----

function hitos_launch_multiespectral()
{
    _hitos_check_setup
    local session_folder
    session_folder=$(date +'%d-%m-%Y_%Hh%Mm')
    print_green "Session folder: $session_folder"
    ros2 launch multiespectral_acquire multiespectral_launch.py \
        session_folder:="$session_folder" "$@"
}

function hitos_launch_temperature()
{
    _hitos_check_setup
    ros2 launch temperature_driver dht22.launch.py
}

function hitos_launch_gps()
{
    _hitos_check_setup
    ros2 launch hitos_setup gps.launch.py
}

function hitos_launch_lidar()
{
    _hitos_check_setup
    ros2 launch hitos_setup lidar.launch.py
}

function hitos_launch_all()
{
    _hitos_check_setup
    ros2 launch hitos_setup hitos_full.launch.py
}

# ---- Recording control ----

function hitos_multiespectral_start_store() {
    ros2 topic pub -1 /Multiespectral/recording_enabled std_msgs/msg/Bool "data: true"
}

function hitos_multiespectral_stop_store() {
    ros2 topic pub -1 /Multiespectral/recording_enabled std_msgs/msg/Bool "data: false"
}
