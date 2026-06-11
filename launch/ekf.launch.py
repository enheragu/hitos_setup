from launch import LaunchDescription
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

# Ouster IMU publishes BEST_EFFORT; robot_localization subscribes RELIABLE by
# default — override via ROS2 QoS parameter namespace to avoid silent mismatch.
_IMU_QOS = {'qos_overrides./ouster/imu.subscription.reliability': 'best_effort'}


def generate_launch_description():
    share = FindPackageShare('hitos_setup')
    ekf_local_cfg  = PathJoinSubstitution([share, 'config', 'ekf_local.yaml'])
    ekf_global_cfg = PathJoinSubstitution([share, 'config', 'ekf_global.yaml'])

    return LaunchDescription([
        # EKF 1 — local frame, IMU only.
        # Publishes odometry/filtered (odom → base_link).
        Node(
            package='robot_localization',
            executable='ekf_node',
            name='ekf_local',
            namespace='',
            output='screen',
            parameters=[ekf_local_cfg, _IMU_QOS],
        ),

        # navsat_transform — converts /gnss/fix to local ENU odometry.
        # Needs odometry/filtered from EKF 1 to initialise.
        # Publishes /odometry/gnss.
        Node(
            package='robot_localization',
            executable='navsat_transform_node',
            name='navsat_transform',
            output='screen',
            parameters=[ekf_global_cfg, _IMU_QOS],
            remappings=[
                ('imu/data',          '/ouster/imu'),
                ('gps/fix',           '/gnss/fix'),
                ('odometry/filtered', '/odometry/filtered'),
                ('odometry/gps',      '/odometry/gnss'),
            ],
        ),

        # EKF 2 — global frame (map), fuses local odometry + GPS.
        # Publishes /odometry/combined (map → base_link).
        #
        # namespace='global' is intentional: the output topic is
        # /global/odometry/filtered (relative in 'global' ns) and the
        # remapping redirects it to the absolute /odometry/combined.
        # Without the namespace, the remapping would also remap the
        # odom0 subscription (/odometry/filtered) to /odometry/combined,
        # causing ekf_global to subscribe to its own output.
        Node(
            package='robot_localization',
            executable='ekf_node',
            name='ekf_global',
            namespace='global',
            output='screen',
            parameters=[ekf_global_cfg],
            remappings=[
                ('odometry/filtered', '/odometry/combined'),
            ],
        ),
    ])
