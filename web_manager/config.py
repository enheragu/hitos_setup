#!/usr/bin/env python3
# encoding: utf-8

from sensor_msgs.msg import NavSatFix, PointCloud2, Imu
from nav_msgs.msg import Odometry
from std_msgs.msg import Bool

try:
    from temperature_driver.msg import TemperatureHumidity
except ImportError:
    TemperatureHumidity = None

try:
    from multiespectral_acquire.msg import ImageWithMetadata
except ImportError:
    from sensor_msgs.msg import Image as ImageWithMetadata

# =============================================================================
# TOPIC MONITORING
# =============================================================================

TOPIC_GROUPS = {
    "sensors": {
        "GPS": {
            "topic": "/gnss/fix",
            "msg_type": NavSatFix,
            "show": "hz",
            "extra_fields": {
                "Fix Mode": {
                    "field": "status.status",
                    "mapping": {-1: "No Fix", 0: "Fix", 1: "SBAS Fix", 2: "GBAS Fix"},
                },
                "Lat / Lon / Altitude": {
                    "fields": ["latitude", "longitude", "altitude"],
                    "format": "{0:.6f}, {1:.6f}, {2:.1f}",
                },
                "COV": {
                    "field": "position_covariance",
                    "indices": [0, 4],
                },
            },
        },
        "Temperature": {
            "topic": "/dht22/data",
            "msg_type": TemperatureHumidity,
            "show": "hz",
            "extra_fields": {
                "Data": {
                    "fields": ["temperature", "humidity"],
                    "format": "{0:.1f} °C,  {1:.1f} %",
                },
            },
        },
        "LiDAR": {
            "topic": "/ouster/points",
            "msg_type": PointCloud2,
            "show": "hz",
        },
        "IMU": {
            "topic": "/ouster/imu",
            "show": "hz",
            "msg_type": Imu
        },
    },
    "cameras": {
        "LWIR (sync)": {
            "topic": "/Multiespectral/lwir_camera/image_with_metadata_sync",
            "msg_type": ImageWithMetadata,
            "show": "hz",
        },
        "Visible (sync)": {
            "topic": "/Multiespectral/visible_camera/image_with_metadata_sync",
            "msg_type": ImageWithMetadata,
            "show": "hz",
        },
        "LWIR (raw)": {
            "topic": "/Multiespectral/lwir_camera/image_with_metadata",
            "msg_type": ImageWithMetadata,
            "show": "hz",
        },
        "Storing": {
            "topic": "/Multiespectral/recording_enabled",
            "msg_type": Bool,
            "show": "data",
            "data_field": "data",
        },
    },
    "fusion": {
        # "EKF Local": {
        #     "topic": "/odometry/filtered",
        #     "msg_type": Odometry,
        #     "show": "hz",
        #     "extra_fields": {
        #         "Position": {
        #             "field": "pose.pose.position",
        #             "format": "[{x:.2f}, {y:.2f}, {z:.2f}]",
        #         },
        #         "Orientation": {
        #             "field": "pose.pose.orientation",
        #             "format": "[{x:.2f}, {y:.2f}, {z:.2f}, {w:.2f}]",
        #         },
        #     },
        # },
        "GNSS (local ENU)": {
            "topic": "/odometry/gnss",
            "msg_type": Odometry,
            "show": "hz",
            "extra_fields": {
                "Position": {
                    "field": "pose.pose.position",
                    "format": "[{x:.2f}, {y:.2f}, {z:.2f}]",
                },
            },
        },
        "EKF Combined": {
            "topic": "/odometry/combined",
            "msg_type": Odometry,
            "show": "hz",
            "extra_fields": {
                "Position": {
                    "field": "pose.pose.position",
                    "format": "[{x:.2f}, {y:.2f}, {z:.2f}]",
                },
                "Orientation": {
                    "field": "pose.pose.orientation",
                    "format": "[{x:.2f}, {y:.2f}, {z:.2f}, {w:.2f}]",
                },
            },
        },
    },
}

# =============================================================================
# PROCESS MONITORING
# =============================================================================

PROCESSES = {
    "PTP Master": {
        "service": "hitos_ptp",
        "description": "IEEE 1588 PTP daemon — synchronises hardware clocks of cameras and LiDAR (eth0).",
    },
    "PTP Sync": {
        "service": "hitos_ptp_sync",
        "description": "Synchronises eth0 PHC from CLOCK_REALTIME via phc2sys.",
    },
    "Sensors": {
        "service": "hitos_sensors",
        "description": "GPS (u-blox 7) + LiDAR (Ouster) + EKF fusion + Temperature (DHT22).",
    },
    "Multiespectral Cameras": {
        "service": "hitos_cameras",
        "description": "Multiespectral FLIR+Basler acquisition with auto session folder and disk mount.",
    },
}

# =============================================================================
# NETWORK INTERFACES
# =============================================================================

NETWORK_INTERFACES = {
    "eth0":            "Cameras + LiDAR",
    "enx3c18a0d60888": "Internet",
    "hnet0":           "Husarnet",
    "wlan0":           "WiFi",
}

# Per-IP breakdown on eth0 (monitored via iptables HITOS_RX/HITOS_TX chains)
SENSOR_IPS = {
    "192.168.4.5":     "Visible Cam",
    "192.168.4.6":     "LWIR Cam",
    "192.168.4.4":    "LiDAR",
}

# =============================================================================
# FLASK CONFIG
# =============================================================================

FLASK_CONFIG = {
    "host": "::",
    "port": 5050,
}

# =============================================================================
# SUB-GUI LINKS
# =============================================================================

GUI_LINKS = {
    "cameras": {
        "name": "Multiespectral Camera GUI",
        "port": 5051,
        "path": "/",
        "service": "hitos_camera_gui",
    },
}
