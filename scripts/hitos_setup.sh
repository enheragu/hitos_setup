#!/usr/bin/env bash

## Path of current file
SOURCE=${BASH_SOURCE[0]}
while [ -L "$SOURCE" ]; do # resolve $SOURCE until the file is no longer a symlink
  DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )
  SOURCE=$(readlink "$SOURCE")
  [[ $SOURCE != /* ]] && SOURCE=$DIR/$SOURCE # if $SOURCE was a relative symlink, we need to resolve it relative to the path where the symlink file was located
done
export HITOS_SETUP_SCRIPT_PATH=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )

## Default helper variables
export ROS_CONFIGURED=0

source $HITOS_SETUP_SCRIPT_PATH/log_utils.sh				# Log utilities to be used
source $HITOS_SETUP_SCRIPT_PATH/hitos_private_functions.sh	# Private helper functions

function husky_ros_setup() {
	bind_fkeys
	_husky_export_ip
	# source /home/administrator/cartographer/devel_isolated/setup.sh
	source /home/administrator/husky_noetic_ws/devel/setup.bash

	# When run in systemctl theres no localhost yet
	export ROS_MASTER_URI=http://arvc-multiespectral:11311
	export ROS_HOSTNAME=arvc-multiespectral
	
	
	# Check if disk is already mounted 
	if ! grep -qs '/media/administrator/data ' /proc/mounts; then
		udisksctl mount -b /dev/disk/by-label/data
		print_green "Mounted disk data"
	fi

	export ROS_CONFIGURED=1

	print_green "Husky ROS development environment loaded"
}