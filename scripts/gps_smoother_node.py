#!/usr/bin/env python3
"""gps_smoother_node — GPS-ONLY refinement of the raw fix using the higher-rate measurements.

The dataset is stored at the camera trigger rate (~1 Hz) but the u-blox runs at 5 Hz, so most
fixes are otherwise discarded. This node keeps a sliding time window of /gnss/fix and fits a
per-axis linear model (value = a + b·t) by least squares, evaluated at the latest sample time.

Why this and not navsat_transform: navsat's /gps/filtered is the EKF state (IMU+GPS) reprojected
to lat-lon — on a hand-carried rig with no magnetometer/wheel-odometry the IMU fusion does not
help and can drift. This is pure GPS: it averages down the *random* noise via the repeated
measurements, with NO IMU. Using a linear fit (not a plain mean) and evaluating it at the sample
instant keeps the position from being smeared while you walk slowly.

Covariance is scaled toward 1/N but FLOORED (cov_corr_floor): GPS error has a temporally
correlated part (multipath / ionosphere) that does NOT average out over a 1–3 s window, so the
honest reduction is conservative, not the full 1/N.

Window is adaptive (optional): from the fitted speed it widens when slow/static (more averaging)
and narrows when moving (bounded spatial smear = max_smear_m).

Publishes /gnss/fix_smoothed (sensor_msgs/NavSatFix). Point the GNSS buffer handler at it.
"""
import math
from collections import deque

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import NavSatFix


class GpsSmoother(Node):
    def __init__(self):
        super().__init__('gps_smoother')
        self.declare_parameter('input_topic', '/gnss/fix')
        self.declare_parameter('output_topic', '/gnss/fix_smoothed')
        self.declare_parameter('window_sec', 1.0)       # base window when not adaptive
        self.declare_parameter('adaptive', True)
        self.declare_parameter('window_min', 0.4)       # s, fastest-motion window
        self.declare_parameter('window_max', 3.0)       # s, static window
        self.declare_parameter('max_smear_m', 0.30)     # spatial budget that sets the adaptive window
        self.declare_parameter('cov_corr_floor', 0.4)   # fraction of variance that does NOT average down

        gp = lambda n: self.get_parameter(n).value
        self.in_topic = gp('input_topic'); self.win = gp('window_sec')
        self.adaptive = gp('adaptive'); self.wmin = gp('window_min'); self.wmax = gp('window_max')
        self.smear = gp('max_smear_m'); self.floor = gp('cov_corr_floor')

        self.buf = deque()      # (t, lat, lon, alt, (cx,cy,cz))
        self.pub = self.create_publisher(NavSatFix, gp('output_topic'), 10)
        self.create_subscription(NavSatFix, self.in_topic, self.cb, qos_profile_sensor_data)
        self.get_logger().info(
            f"gps_smoother: {self.in_topic} -> {gp('output_topic')} | "
            f"window {'adaptive '+str(self.wmin)+'-'+str(self.wmax) if self.adaptive else self.win} s")

    @staticmethod
    def _fit_at0(ts, vals):
        """Linear least-squares value = a + b*t, returned (value@t=0, slope b)."""
        b, a = np.polyfit(ts, vals, 1)
        return a, b

    def cb(self, msg):
        # Reject invalid / no-fix messages: the u-blox emits NavSatFix with status=NO_FIX,
        # lat/lon ≈ 0 (or NaN) and a huge covariance before it has a lock. Letting those into
        # the window poisons both the average and the linear fit.
        if (msg.status.status < 0
                or not math.isfinite(msg.latitude) or not math.isfinite(msg.longitude)
                or msg.position_covariance[0] > 1e6):
            return
        t = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        cov = (msg.position_covariance[0], msg.position_covariance[4], msg.position_covariance[8])
        self.buf.append((t, msg.latitude, msg.longitude, msg.altitude, cov))
        while self.buf and t - self.buf[0][0] > self.wmax:   # never keep more than wmax
            self.buf.popleft()

        m_per_deg_lat = 111320.0
        m_per_deg_lon = 111320.0 * math.cos(math.radians(msg.latitude))

        # --- choose the window (adaptive from current speed) ---
        win = self.win
        if self.adaptive and len(self.buf) >= 3:
            ts = np.array([b[0] for b in self.buf]) - t
            _, blat = self._fit_at0(ts, np.array([b[1] for b in self.buf]))
            _, blon = self._fit_at0(ts, np.array([b[2] for b in self.buf]))
            speed = math.hypot(blat * m_per_deg_lat, blon * m_per_deg_lon)   # m/s
            win = self.wmax if speed < 1e-3 else min(self.wmax, max(self.wmin, self.smear / speed))

        sel = [b for b in self.buf if t - b[0] <= win] or [self.buf[-1]]
        n = len(sel)

        # --- refined position: linear fit evaluated at the latest instant (t=0) ---
        if n >= 2:
            ts = np.array([b[0] for b in sel]) - t
            lat, _ = self._fit_at0(ts, np.array([b[1] for b in sel]))
            lon, _ = self._fit_at0(ts, np.array([b[2] for b in sel]))
            alt, _ = self._fit_at0(ts, np.array([b[3] for b in sel]))
        else:
            lat, lon, alt = sel[0][1], sel[0][2], sel[0][3]

        # --- conservative covariance reduction ---
        cov_in = np.mean(np.array([b[4] for b in sel]), axis=0)
        cov_out = cov_in * (self.floor + (1.0 - self.floor) / max(n, 1))

        out = NavSatFix()
        out.header = msg.header          # keep the trigger-aligned stamp & frame_id
        out.status = msg.status
        out.latitude, out.longitude, out.altitude = float(lat), float(lon), float(alt)
        pc = [0.0] * 9
        pc[0], pc[4], pc[8] = float(cov_out[0]), float(cov_out[1]), float(cov_out[2])
        out.position_covariance = pc
        out.position_covariance_type = NavSatFix.COVARIANCE_TYPE_DIAGONAL_KNOWN
        self.pub.publish(out)


def main():
    rclpy.init()
    node = GpsSmoother()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.try_shutdown()


if __name__ == '__main__':
    main()
