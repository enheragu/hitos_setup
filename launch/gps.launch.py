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
            default_value=EnvironmentVariable('HITOS_GPS_PORT', default_value='/dev/ttyACM0'),
            description='Serial port for the u-blox 7 GPS (override config file value)',
        ),
        DeclareLaunchArgument('frame_id', default_value='gps_link'),

        Node(
            package='ublox_gps',
            executable='ublox_gps_node',
            name='gnss',
            output='screen',
            parameters=[
                params_file,
                {
                    'device':   LaunchConfiguration('port'),
                    'frame_id': LaunchConfiguration('frame_id'),
                },
            ],
            # Suppress the "End of file" flood when GPS is disconnected.
            # WARN level still shows real errors; ERROR/FATAL spam is dropped.
            arguments=['--ros-args', '--log-level', 'gnss:=WARN'],
        ),
    ])
