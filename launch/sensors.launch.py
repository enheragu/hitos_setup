from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    hitos_share = FindPackageShare('hitos_setup')
    temp_share  = FindPackageShare('temperature_driver')

    return LaunchDescription([
        DeclareLaunchArgument('with_lidar', default_value='true',
                              description='Launch Ouster LiDAR driver'),
        DeclareLaunchArgument('with_gps',   default_value='true',
                              description='Launch u-blox GPS driver'),
        DeclareLaunchArgument('with_ekf',   default_value='true',
                              description='Launch EKF sensor fusion (GPS + IMU)'),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([hitos_share, '/launch/gps.launch.py']),
            condition=IfCondition(LaunchConfiguration('with_gps')),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([hitos_share, '/launch/lidar.launch.py']),
            condition=IfCondition(LaunchConfiguration('with_lidar')),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([hitos_share, '/launch/sensor_model.launch.py']),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([hitos_share, '/launch/ekf.launch.py']),
            condition=IfCondition(LaunchConfiguration('with_ekf')),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([temp_share, '/launch/dht22.launch.py']),
            launch_arguments={
                'port': EnvironmentVariable('HITOS_DHT22_PORT', default_value='/dev/ttyUSB0'),
            }.items(),
        ),
    ])
