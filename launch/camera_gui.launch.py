import os
from ament_index_python.packages import get_package_prefix
from launch import LaunchDescription
from launch.actions import GroupAction
from launch_ros.actions import Node, PushRosNamespace
from launch_ros.parameter_descriptions import ParameterValue
from launch.substitutions import TextSubstitution


def generate_launch_description():
    executable = os.path.join(
        get_package_prefix('multiespectral_acquire_gui'), 'bin', 'multiespectral_control')

    return LaunchDescription([
        GroupAction(actions=[
            PushRosNamespace('Multiespectral'),
            Node(
                executable=executable,
                name='multiespectral_flask_gui',
                output='screen',
                parameters=[{
                    'flask_host':    '::',
                    'flask_port':    5051,
                    'gui_title':     'HITOS Acquisition GUI',
                    'camera1_name':  'LWIR Camera',
                    'camera1_topic': '/Multiespectral/lwir_camera/image_with_metadata_sync',
                    'camera2_name':  'Visible Camera',
                    'camera2_topic': '/Multiespectral/visible_camera/image_with_metadata_sync',
                    'lidar_name':    'LIDAR',
                    'lidar_topic':   '/Multiespectral/ouster/reflec_image_sync_cropped_sync',
                    'lidar_topic_names': [
                        '/Multiespectral/ouster/range_image_sync_cropped_sync',
                        '/Multiespectral/ouster/reflec_image_sync_cropped_sync',
                        '/Multiespectral/ouster/signal_image_sync_cropped_sync',
                        '/Multiespectral/ouster/nearir_image_sync_cropped_sync',
                    ],
                    'lidar_topic_labels': [
                        'Range Image', 'Reflectivity Image',
                        'Signal Image', 'Near-IR Image',
                    ],
                }],
            ),
        ]),
    ])
