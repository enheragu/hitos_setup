import os
import tempfile

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration


def _launch_ouster(context, *args, **kwargs):
    sensor_hostname = context.perform_substitution(LaunchConfiguration('sensor_hostname'))
    viz = context.perform_substitution(LaunchConfiguration('viz'))

    hitos_share = get_package_share_directory('hitos_setup')
    ouster_share = get_package_share_directory('ouster_ros')

    base_params = os.path.join(hitos_share, 'config', 'ouster_params.yaml')
    with open(base_params) as f:
        params = yaml.safe_load(f)

    params['ouster/os_driver']['ros__parameters']['sensor_hostname'] = sensor_hostname

    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
    yaml.dump(params, tmp)
    tmp_path = tmp.name
    tmp.close()

    return [IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(ouster_share, 'launch', 'driver.launch.py')
        ),
        launch_arguments={
            'params_file': tmp_path,
            'viz': viz,
        }.items(),
    )]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'sensor_hostname',
            default_value=EnvironmentVariable('HITOS_LIDAR_IP', default_value='192.168.4.4'),
            description='Hostname or IP of the Ouster LiDAR sensor',
        ),
        DeclareLaunchArgument('viz', default_value='False',
                              description='Launch RViz visualizer'),
        OpaqueFunction(function=_launch_ouster),
    ])
