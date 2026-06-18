from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution


def generate_launch_description():
    params_file = PathJoinSubstitution([
        FindPackageShare('hitos_setup'), 'config', 'ublox7_gps.yaml'
    ])

    return LaunchDescription([
        DeclareLaunchArgument(
            'port',
            # Persistent udev symlink (99-ublox-gps.rules), NOT /dev/ttyACMx:
            # it follows the GPS across USB re-enumeration, so a respawn always
            # re-opens the current device.
            default_value=EnvironmentVariable('HITOS_GPS_PORT', default_value='/dev/ublox_gps'),
            description='Serial port for the u-blox 7 GPS (override config file value)',
        ),
        DeclareLaunchArgument('frame_id', default_value='gps_link'),

        Node(
            package='ublox_gps',
            executable='ublox_gps_node',
            name='gnss',
            output='screen',
            # On a dead fd the driver exits after ~3 s of read errors (see
            # async_worker.hpp); respawn restarts ONLY this node and re-opens
            # /dev/ublox_gps — auto-recovery without restarting the Ouster/EKF.
            respawn=True,
            respawn_delay=5.0,
            parameters=[
                params_file,
                {
                    'device':   LaunchConfiguration('port'),
                    'frame_id': LaunchConfiguration('frame_id'),
                },
            ],
            # Drop INFO/DEBUG chatter. NOTE: this does NOT suppress the read-
            # error ERROR line (ERROR > WARN); that flood is now throttled at
            # source in async_worker.hpp.
            arguments=['--ros-args', '--log-level', 'gnss:=WARN'],
        ),

        # GPS-only sliding-window smoother: refines the 5 Hz /gnss/fix into
        # /gnss/fix_smoothed (linear fit, adaptive window, conservative covariance).
        # NO IMU — pure GPS. The GNSS buffer handler stores this topic.
        Node(
            package='hitos_setup',
            executable='gps_smoother_node.py',
            name='gps_smoother',
            output='screen',
            respawn=True,
            respawn_delay=5.0,
            parameters=[{
                'input_topic':  '/gnss/fix',
                'output_topic': '/gnss/fix_smoothed',
                'adaptive':     True,
            }],
        ),
    ])
