"""Topic Hz monitor — publishes <topic>/hz for the high-rate sensor topics.

Offloads frequency measurement from the Python web manager (where receiving a
97 Hz IMU + 6 MB point clouds pinned a core) to a cheap C++ node. The web
manager can then subscribe to the tiny 1 Hz Float64 "/hz" topics instead of the
raw firehose.
"""
from launch import LaunchDescription
from launch_ros.actions import Node


# High-rate / large topics that are expensive to monitor from Python.
# Add the lighter ones too if you want all rates centralised here.
MONITORED_TOPICS = [
    '/ouster/points',
    '/ouster/imu',
    '/Multiespectral/lwir_camera/image_with_metadata',
    '/Multiespectral/visible_camera/image_with_metadata',
    '/Multiespectral/lwir_camera/image_with_metadata_sync',
    '/Multiespectral/visible_camera/image_with_metadata_sync',
]


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='hitos_setup',
            executable='topic_hz_monitor',
            name='topic_hz_monitor',
            output='screen',
            parameters=[{
                'topics': MONITORED_TOPICS,
                'publish_rate': 1.0,
            }],
        ),
    ])
