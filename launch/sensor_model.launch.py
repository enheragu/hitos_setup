"""Publish the HITOS sensor TF tree from the URDF/xacro via robot_state_publisher.

This is THE source of the static sensor TFs (it replaced the old static_transform_publisher
script). Included by sensors.launch.py (hitos_sensors.service), and also runnable alone to
render the rig in rviz via /robot_description + the meshes (sanity-check the CAD seed: frame
placement, the +Y-left assumption, OUSTER_BASE_Z, the os_sensor yaw, the box placement).
All joints are fixed, so no joint_state_publisher is needed. Needs the `xacro` package.
"""
from launch import LaunchDescription
from launch.substitutions import Command, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    xacro_file = PathJoinSubstitution(
        [FindPackageShare('hitos_setup'), 'urdf', 'hitos_sensors.urdf.xacro'])
    robot_description = ParameterValue(
        Command(['xacro ', xacro_file]), value_type=str)

    return LaunchDescription([
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            name='robot_state_publisher',
            output='screen',
            parameters=[{'robot_description': robot_description}],
        ),
    ])
