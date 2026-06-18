import os
import tempfile

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument, GroupAction, IncludeLaunchDescription, OpaqueFunction,
    SetEnvironmentVariable,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node


def _launch_ouster(context, *args, **kwargs):
    sensor_hostname = context.perform_substitution(LaunchConfiguration('sensor_hostname'))
    viz = context.perform_substitution(LaunchConfiguration('viz'))

    hitos_share = get_package_share_directory('hitos_setup')
    ouster_share = get_package_share_directory('ouster_ros')

    base_params = os.path.join(hitos_share, 'config', 'ouster_params.yaml')
    with open(base_params) as f:
        params = yaml.safe_load(f)

    params['ouster/os_driver']['ros__parameters']['sensor_hostname'] = sensor_hostname

    # Publish RELIABLE (not the default SensorDataQoS best-effort) in BOTH modes.
    # The dense cloud (~1.6 MB normal / ~3.8 MB calib) and the lidar images
    # fragment over UDP loopback; best-effort loses whole samples (a lost fragment
    # is never retransmitted), dropping delivery from the sensor's 10 Hz to ~5 Hz.
    # That HALVES the cloud rate the buffer can match against, doubling the
    # camera↔lidar sync error (closest cloud to a trigger: ±50 → ±100 ms) — not
    # acceptable even when storing at 1 Hz. Reliable retransmits the lost fragments
    # so the buffer always has the full 10 Hz. The matching _sync handlers read
    # reliable too (buffer_compositor: use_reliable_qos=True). Best-effort consumers
    # (crop, recal, rviz) stay QoS-compatible with a reliable writer. Cost is the
    # always-on reliable overhead (history + retransmit); SHM transport would remove
    # it but needs its own config/test cycle — future optimisation.
    params['ouster/os_driver']['ros__parameters']['use_system_default_qos'] = True

    # Calibration mode: widen the azimuth window to capture a near-complete cloud.
    # Default 250° (window 52000..302000 millideg) centred so the ~110° gap sits
    # behind the operator (encoder ~0°, opposite the camera-forward centre ~177°).
    # Tunable via env without code edits. HITOS_CALIB is exported by the service
    # ExecStart sourcing /tmp/hitos_mode.env.
    if os.environ.get('HITOS_CALIB', '0') == '1':
        p = params['ouster/os_driver']['ros__parameters']
        p['azimuth_window_start'] = int(os.environ.get('HITOS_CALIB_AZIMUTH_START', 52000))
        p['azimuth_window_end']   = int(os.environ.get('HITOS_CALIB_AZIMUTH_END', 302000))

    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
    yaml.dump(params, tmp)
    tmp_path = tmp.name
    tmp.close()

    # os_driver publishes the large cloud (3.8 MB calib) + 4 lidar images. Give
    # ONLY this process the big-segment SHM profile so those go over shared memory
    # instead of fragmented UDP loopback. Scoped GroupAction so the env var does
    # not leak to the other sensor nodes (ekf/gnss/recal/…), which would each
    # waste a 32 MB resident segment. os_driver lives inside Ouster's driver.launch
    # include, so SetEnvironmentVariable is the only way to reach its process env.
    shm_profile = os.path.join(hitos_share, 'config', 'fastdds_shm_profile.xml')
    return [GroupAction(scoped=True, actions=[
        SetEnvironmentVariable('FASTRTPS_DEFAULT_PROFILES_FILE', shm_profile),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(ouster_share, 'launch', 'driver.launch.py')
            ),
            launch_arguments={
                'params_file': tmp_path,
                'viz': viz,
            }.items(),
        ),
    ])]


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
        # Calibrates the Ouster internal-osc clock to wall-clock from the 100 Hz IMU.
        # Publishes /ouster/imu_recal (for the EKF) and /ouster/clock_offset (for the
        # buffer compositor). Required because the sensor runs TIME_FROM_INTERNAL_OSC.
        Node(
            package='hitos_setup',
            executable='ouster_recal_node',
            name='ouster_recal_node',
            output='screen',
        ),
    ])
