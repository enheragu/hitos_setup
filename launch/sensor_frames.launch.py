"""
Static TF tree for the HITOS sensor rig.

All sensor-frame-to-base_link transforms live here. Arguments are
[x y z yaw pitch roll parent_frame child_frame], units: metres / radians.

Frames that have not been physically measured yet are set to identity
and marked with a TODO comment.
"""
from launch import LaunchDescription
from launch_ros.actions import Node

# ---- base_link → Ouster IMU (identity — TODO: measure after mounting) ----
_BASE_TO_IMU = ['0', '0', '0', '0', '0', '0', 'base_link', 'os_sensor']

# ---- base_link → GPS antenna (identity — TODO: measure after mounting) ----
_BASE_TO_GPS = ['0', '0', '0', '0', '0', '0', 'base_link', 'gps_link']

# ---- base_link → visible camera (identity — TODO: measure after mounting) ----
_BASE_TO_VIS = ['0', '0', '0', '0', '0', '0', 'base_link', 'visible_camera_frame']

# ---- visible camera → LWIR camera
# Measured: LWIR is +3 cm in X relative to visible (same Y, same Z).
# Positive X = right when looking forward. Verify sign with physical measurement.
_VIS_TO_LWIR = ['0.03', '0', '0', '0', '0', '0', 'visible_camera_frame', 'lwir_camera_frame']


def generate_launch_description():
    def stp(name, args):
        return Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name=name,
            arguments=args,
        )

    return LaunchDescription([
        stp('tf_base_to_imu',     _BASE_TO_IMU),
        stp('tf_base_to_gps',     _BASE_TO_GPS),
        stp('tf_base_to_visible', _BASE_TO_VIS),
        stp('tf_visible_to_lwir', _VIS_TO_LWIR),
    ])
