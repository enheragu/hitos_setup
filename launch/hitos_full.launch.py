from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    hitos_share = FindPackageShare('hitos_setup')
    ma_share    = FindPackageShare('multiespectral_acquire')

    session_folder = LaunchConfiguration('session_folder')

    return LaunchDescription([
        DeclareLaunchArgument('session_folder',       default_value='test_session',
                              description='Dataset subfolder name (timestamp recommended)'),
        DeclareLaunchArgument('dataset_output_path',
                              default_value='/media/arvc/DATASETS/images_eeha'),
        DeclareLaunchArgument('with_lidar',           default_value='true'),
        DeclareLaunchArgument('with_gps',             default_value='true'),
        DeclareLaunchArgument('with_ekf',             default_value='true'),

        # ---- All sensors (GPS + LiDAR + EKF + Temperature) ----
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([hitos_share, '/launch/sensors.launch.py']),
            launch_arguments={
                'with_gps':   LaunchConfiguration('with_gps'),
                'with_lidar': LaunchConfiguration('with_lidar'),
                'with_ekf':   LaunchConfiguration('with_ekf'),
            }.items(),
        ),

        # ---- Multiespectral cameras + buffers ----
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([ma_share, '/launch/multiespectral_launch.py']),
            launch_arguments={
                'session_folder':      session_folder,
                'dataset_output_path': LaunchConfiguration('dataset_output_path'),
            }.items(),
        ),
    ])
