#!/usr/bin/env python3
# encoding: utf-8

import re
import subprocess
import threading
import time
from collections import deque
from typing import Any, Dict, Optional

_ANSI_RE      = re.compile(r'\x1b\[[0-9;]*m')
_TIME_RE      = re.compile(r'^\d{2}:\d{2}:\d{2}$')
_ROS_EPOCH_RE = re.compile(r'\s*\[\d{10}\.\d+\]')
_PROC_PFX_RE  = re.compile(r'^\S+:\s*')

def _clean_log_line(line: str) -> str:
    """Strip journalctl header and ROS2 epoch from a log line.

    journalctl short format: "Mon DD HH:MM:SS hostname process[pid]: message"
    Splits on whitespace into at most 5 tokens: month, day, time, host, rest.
    Works for any process name format (bash[pid], python3[pid], ros2, …).
    """
    line = _ANSI_RE.sub('', line)
    parts = line.split(None, 4)
    if len(parts) >= 5 and _TIME_RE.match(parts[2]):
        msg = _PROC_PFX_RE.sub('', parts[4])   # strip "process[pid]: "
        msg = _ROS_EPOCH_RE.sub('', msg)
        return f'{parts[2]} {msg}'.strip()
    return line

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool
from rclpy.qos import (QoSDurabilityPolicy, QoSHistoryPolicy,
                        QoSProfile, QoSReliabilityPolicy)

_BEST_EFFORT_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=1,
)
_RELIABLE_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.RELIABLE,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=1,
)
_LATCHING_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.RELIABLE,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=1,
    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
)

# Topics that benefit from BEST_EFFORT (high-rate sensor data)
_BEST_EFFORT_TOPICS = {'/ouster/points', '/ouster/imu'}


class TopicMonitor:
    """Monitor a single ROS2 topic for frequency and/or data."""

    def __init__(self, node: Node, name: str, topic: str, msg_type,
                 show: str = 'hz', data_field: str = None,
                 extra_fields: dict = None):
        self.name = name
        self.topic = topic
        self.show = show
        self.data_field = data_field
        self.extra_fields = extra_fields or {}

        self._lock = threading.Lock()
        self._history = deque(maxlen=5)
        self._freq_history: deque = deque(maxlen=300)
        self._msg_count = 0
        self._last_update = time.monotonic()
        self._last_msg_time = 0.0
        self._frequency: Optional[float] = None
        self._last_data = None
        self._extra_data: Dict[str, Any] = {}

        self._reset_timeout = 3.0
        self._metric_interval = 1.0
        self._start_time = time.monotonic()
        self._last_hist_push_time = 0.0
        self._null_entries_added = 0

        if msg_type is None:
            node.get_logger().warning(
                f'[TopicMonitor] {name}: msg_type is None, skipping subscription.')
            return

        qos = _BEST_EFFORT_QOS if topic in _BEST_EFFORT_TOPICS else _RELIABLE_QOS

        # For hz-only monitors with no extra_fields, use a generic (untyped) subscription
        # to avoid Python deserialization of large messages (e.g. PointCloud2).
        try:
            node.create_subscription(msg_type, topic, self._callback, qos)
        except Exception as e:
            node.get_logger().warning(f'[TopicMonitor] {name}: failed to subscribe: {e}')

    # ------------------------------------------------------------------

    def _hz_callback(self, _msg):
        """Lightweight callback for hz-only monitors: counts arrivals, no deserialization."""
        with self._lock:
            now = time.monotonic()
            self._msg_count += 1
            self._last_msg_time = now
            if now - self._last_update >= self._metric_interval:
                self._history.append(self._msg_count)
                self._frequency = sum(self._history) / len(self._history)
                self._msg_count = 0
                self._last_update = now

    def _get_nested_attr(self, obj, path: str):
        try:
            for part in path.split('.'):
                obj = getattr(obj, part)
            return obj
        except AttributeError:
            return None

    def _callback(self, msg):
        with self._lock:
            now = time.monotonic()
            self._msg_count += 1
            self._last_msg_time = now

            if now - self._last_update >= self._metric_interval:
                self._history.append(self._msg_count)
                self._frequency = sum(self._history) / len(self._history)
                self._freq_history.append(round(self._frequency, 2))
                self._last_hist_push_time = now
                self._null_entries_added = 0
                self._msg_count = 0
                self._last_update = now

            if self.show == 'data' and self.data_field:
                self._last_data = self._get_nested_attr(msg, self.data_field)

            for field_name, field_cfg in self.extra_fields.items():
                if 'fields' in field_cfg:
                    try:
                        values = [self._get_nested_attr(msg, f) for f in field_cfg['fields']]
                        if 'format' in field_cfg and all(v is not None for v in values):
                            self._extra_data[field_name] = field_cfg['format'].format(*values)
                        else:
                            self._extra_data[field_name] = values
                    except Exception:
                        self._extra_data[field_name] = None
                    continue

                value = self._get_nested_attr(msg, field_cfg.get('field', ''))

                if 'mapping' in field_cfg and value is not None:
                    mapped = field_cfg['mapping'].get(int(value), f'Unknown ({value})')
                    self._extra_data[field_name] = f'{mapped} [{value}]'
                elif 'indices' in field_cfg and value is not None:
                    try:
                        self._extra_data[field_name] = [value[i] for i in field_cfg['indices']]
                    except (IndexError, TypeError):
                        self._extra_data[field_name] = None
                elif 'format' in field_cfg and value is not None:
                    try:
                        if hasattr(value, '__slots__'):
                            # ROS2 msg slots use _name internally; strip leading _ for format keys
                            fmt_dict = {a.lstrip('_'): getattr(value, a) for a in value.__slots__}
                        elif hasattr(value, '__dict__'):
                            fmt_dict = {k: v for k, v in value.__dict__.items()
                                        if not k.startswith('_')}
                        else:
                            fmt_dict = {a: getattr(value, a)
                                        for a in ('x', 'y', 'z', 'w') if hasattr(value, a)}
                        self._extra_data[field_name] = field_cfg['format'].format(**fmt_dict)
                    except Exception:
                        try:
                            self._extra_data[field_name] = field_cfg['format'].format(value)
                        except Exception:
                            self._extra_data[field_name] = str(value)
                else:
                    self._extra_data[field_name] = value

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            timed_out = (self._last_msg_time > 0 and
                         now - self._last_msg_time >= self._reset_timeout)
            if timed_out:
                self._frequency = None
                if self.show == 'hz':
                    self._extra_data = {}
            if self.show == 'hz' and self._frequency is None:
                ref_time = self._last_hist_push_time if self._last_hist_push_time > 0 else self._start_time
                elapsed_s = int(now - ref_time)
                capped = min(elapsed_s, self._freq_history.maxlen)
                to_add = max(0, capped - self._null_entries_added)
                for _ in range(to_add):
                    self._freq_history.append(None)
                self._null_entries_added += to_add

            is_active = (self._frequency is not None) if self.show == 'hz' \
                else (self._last_data is not None)

            result = {
                'name': self.name,
                'topic': self.topic,
                'show': self.show,
                'active': is_active,
            }

            if self.show == 'hz':
                result['value'] = (f'{self._frequency:.2f} Hz'
                                   if self._frequency else 'N/A')
                result['history'] = list(self._freq_history)
            else:
                result['value'] = (str(self._last_data)
                                   if self._last_data is not None else 'N/A')

            for field_name, field_value in self._extra_data.items():
                if isinstance(field_value, str):
                    result[field_name] = field_value
                elif isinstance(field_value, list):
                    formatted = [f'{v:.4f}' if isinstance(v, float) else str(v)
                                 for v in field_value]
                    result[field_name] = f'[{", ".join(formatted)}]'
                elif field_value is not None:
                    result[field_name] = str(field_value)
                else:
                    result[field_name] = 'N/A'

            return result


# =============================================================================

class ProcessMonitor:
    """Check status and control systemd services."""

    def __init__(self, processes: Dict[str, dict]):
        self.processes = processes
        self._cache: Dict[str, dict] = {}
        self._cache_time = 0.0
        self._cache_ttl = 1.0
        self._lock = threading.Lock()

    def _is_active(self, config: dict) -> bool:
        service = config.get('service', '')
        if service:
            if not service.endswith('.service'):
                service += '.service'
            try:
                r = subprocess.run(['systemctl', 'is-active', service],
                                   capture_output=True, text=True, timeout=2)
                return r.stdout.strip() == 'active'
            except Exception:
                pass
        cmd = config.get('command', '')
        if cmd:
            try:
                r = subprocess.run(['pgrep', '-f', cmd],
                                   capture_output=True, text=True, timeout=2)
                return r.returncode == 0 and bool(r.stdout.strip())
            except Exception:
                pass
        return False

    def get_all_status(self) -> Dict[str, dict]:
        with self._lock:
            if time.monotonic() - self._cache_time < self._cache_ttl:
                return self._cache
            status = {}
            for name, cfg in self.processes.items():
                status[name] = {
                    'active': self._is_active(cfg),
                    'service': cfg.get('service'),
                    'can_relaunch': 'service' in cfg,
                    'description': cfg.get('description', ''),
                }
            self._cache = status
            self._cache_time = time.monotonic()
            return status

    def _run_systemctl(self, action: str, service: str, timeout: int) -> dict:
        if not service.endswith('.service'):
            service += '.service'
        try:
            r = subprocess.run(['sudo', '-n', 'systemctl', action, service],
                               capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                return {'success': True, 'message': f'{service} {action}ed successfully'}
            err = r.stderr.strip()
            if 'password' in err or 'terminal' in err:
                return {'success': False,
                        'message': 'Sudo permission required — see systemctl_services/hitos-manager-sudoers'}
            return {'success': False, 'message': f'Failed: {err}'}
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': f'{action} timed out'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def relaunch(self, name: str) -> dict:
        if name not in self.processes:
            return {'success': False, 'message': f'Unknown process: {name}'}
        svc = self.processes[name].get('service')
        if not svc:
            return {'success': False, 'message': 'No service configured'}
        return self._run_systemctl('restart', svc, timeout=30)

    def stop(self, name: str) -> dict:
        if name not in self.processes:
            return {'success': False, 'message': f'Unknown process: {name}'}
        svc = self.processes[name].get('service')
        if not svc:
            return {'success': False, 'message': 'No service configured'}
        return self._run_systemctl('stop', svc, timeout=60)

    def get_logs(self, name: str, lines: int = 100) -> dict:
        if name not in self.processes:
            return {'success': False, 'logs': '', 'message': f'Unknown process: {name}'}
        svc = self.processes[name].get('service', '')
        if not svc:
            return {'success': False, 'logs': '', 'message': 'No service configured'}
        if not svc.endswith('.service'):
            svc += '.service'
        try:
            r = subprocess.run(['journalctl', '-u', svc, '-n', str(lines), '--no-pager'],
                               capture_output=True, text=True, timeout=10)
            cleaned = '\n'.join(_clean_log_line(l) for l in r.stdout.splitlines())
            return {'success': True, 'logs': cleaned}
        except Exception as e:
            return {'success': False, 'logs': '', 'message': str(e)}


# =============================================================================

class HitosMonitor(Node):
    """Main ROS2 node: owns all topic subscriptions and exposes monitoring API."""

    def __init__(self, topic_groups: dict, processes: dict,
                 network_interfaces: dict, sensor_ips: dict = None):
        super().__init__('hitos_web_manager')
        self._topic_monitors: Dict[str, Dict[str, TopicMonitor]] = {}
        self._process_monitor = ProcessMonitor(processes)
        self._net_interfaces = network_interfaces
        self._sensor_ips = sensor_ips or {}

        # CPU stat cache for per-core usage delta
        self._cpu_prev: Dict[str, dict] = {}

        # Background ping cache for IP availability
        self._ip_status: Dict[str, bool] = {}
        self._ping_ips = list((sensor_ips or {}).keys())
        if self._ping_ips:
            ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
            ping_thread.start()
        self._net_prev: Dict[str, dict] = {}
        self._bool_publishers = {}

        from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy
        for group, topics in topic_groups.items():
            self._topic_monitors[group] = {}
            for tname, cfg in topics.items():
                mon = TopicMonitor(
                    node=self,
                    name=tname,
                    topic=cfg['topic'],
                    msg_type=cfg.get('msg_type'),
                    show=cfg.get('show', 'hz'),
                    data_field=cfg.get('data_field'),
                    extra_fields=cfg.get('extra_fields'),
                )
                self._topic_monitors[group][tname] = mon

                if cfg.get('show') == 'data' and cfg.get('msg_type') is Bool:
                    pub = self.create_publisher(Bool, cfg['topic'], _LATCHING_QOS)
                    self._bool_publishers[cfg['topic']] = pub
                    threading.Timer(1.0, self._publish_initial_false, args=[pub]).start()

        self.get_logger().info('HitosMonitor node initialized.')

    def _publish_initial_false(self, pub):
        try:
            msg = Bool()
            msg.data = False
            pub.publish(msg)
        except Exception:
            pass

    def _ping_loop(self):
        """Background thread: ping sensor IPs every 5 seconds and cache result."""
        while True:
            for ip in self._ping_ips:
                try:
                    r = subprocess.run(
                        ['ping', '-c', '1', '-W', '1', '-q', '-I', 'eth0', ip],
                        capture_output=True, timeout=3)
                    self._ip_status[ip] = (r.returncode == 0)
                except Exception:
                    self._ip_status[ip] = False
            time.sleep(5)

    # ------------------------------------------------------------------
    # Public API (called from Flask thread — thread-safe reads only)
    # ------------------------------------------------------------------

    def _read_proc_stat_cores(self) -> dict:
        cores = {}
        try:
            with open('/proc/stat') as f:
                for line in f:
                    if line.startswith('cpu') and len(line) > 3 and line[3].isdigit():
                        parts = line.split()
                        name = parts[0]
                        vals = list(map(int, parts[1:]))
                        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
                        total = sum(vals)
                        cores[name] = {'total': total, 'idle': idle}
        except Exception:
            pass
        return cores

    def _read_proc_meminfo(self) -> dict:
        mem = {}
        try:
            with open('/proc/meminfo') as f:
                for line in f:
                    if ':' in line:
                        k, v = line.split(':', 1)
                        mem[k.strip()] = int(v.strip().split()[0])
        except Exception:
            pass
        return mem

    def get_topics_status(self) -> dict:
        return {
            group: {name: mon.get_status()
                    for name, mon in monitors.items()}
            for group, monitors in self._topic_monitors.items()
        }

    def get_processes_status(self) -> dict:
        return self._process_monitor.get_all_status()

    def relaunch_process(self, name: str) -> dict:
        return self._process_monitor.relaunch(name)

    def stop_process(self, name: str) -> dict:
        return self._process_monitor.stop(name)

    def get_process_logs(self, name: str, lines: int = 100) -> dict:
        return self._process_monitor.get_logs(name, lines)

    def get_network_status(self) -> dict:
        result = {}
        for iface, label in self._net_interfaces.items():
            try:
                rx = int(open(f'/sys/class/net/{iface}/statistics/rx_bytes').read())
                tx = int(open(f'/sys/class/net/{iface}/statistics/tx_bytes').read())
                state = open(f'/sys/class/net/{iface}/operstate').read().strip()
                result[iface] = {'label': label, 'rx_bytes': rx,
                                 'tx_bytes': tx, 'active': state == 'up'}
            except FileNotFoundError:
                result[iface] = {'label': label, 'rx_bytes': 0,
                                 'tx_bytes': 0, 'active': False}

        # Per-IP breakdown via iptables HITOS_RX/HITOS_TX chains
        sensor_stats = self._read_iptables_stats()
        if sensor_stats:
            result['eth0']['sensors'] = sensor_stats
        return result

    def _read_iptables_stats(self) -> dict:
        """Read per-IP byte counts from iptables HITOS_RX and HITOS_TX chains."""
        import re
        rx_bytes = {}
        tx_bytes = {}
        try:
            for chain, store in [('HITOS_RX', rx_bytes), ('HITOS_TX', tx_bytes)]:
                r = subprocess.run(
                    ['sudo', '-n', 'iptables', '-nvxL', chain],
                    capture_output=True, text=True, timeout=3)
                for line in r.stdout.splitlines():
                    # Format: "  pkts  bytes  target  prot  opt  in  out  source  dest"
                    m = re.match(r'\s*\d+\s+(\d+)\s+\S+.*?(\d+\.\d+\.\d+\.\d+)', line)
                    if m:
                        store[m.group(2)] = int(m.group(1))
        except Exception:
            return {}

        result = {}
        for ip, label in self._sensor_ips.items():
            result[ip] = {
                'label':    label,
                'rx_bytes': rx_bytes.get(ip, 0),
                'tx_bytes': tx_bytes.get(ip, 0),
            }
        return result

    def get_system_info(self) -> dict:
        import subprocess

        def _read(path, fallback='N/A'):
            try:
                return open(path).read().strip()
            except Exception:
                return fallback

        def _symlink_port(dev_id, fallback):
            try:
                r = subprocess.run(['readlink', '-f', f'/dev/serial/by-id/{dev_id}'],
                                   capture_output=True, text=True, timeout=2)
                port = r.stdout.strip()
                return port if (r.returncode == 0 and port.startswith('/dev/tty')) else fallback
            except Exception:
                return fallback

        cpu_temp = 'N/A'
        try:
            cpu_temp = f"{int(_read('/sys/class/thermal/thermal_zone0/temp', '0')) / 1000:.1f} °C"
        except Exception:
            pass

        uptime = 'N/A'
        try:
            secs = float(_read('/proc/uptime', '0').split()[0])
            uptime = f"{int(secs // 3600)}h {int((secs % 3600) // 60)}m"
        except Exception:
            pass

        model = _read('/proc/device-tree/model', 'N/A').strip('\x00')

        # RAM via /proc/meminfo (no subprocess needed)
        meminfo = self._read_proc_meminfo()
        mem_total_mb = meminfo.get('MemTotal', 0) // 1024
        mem_avail_mb = meminfo.get('MemAvailable', 0) // 1024
        mem_used_mb  = mem_total_mb - mem_avail_mb
        mem_pct      = round(mem_used_mb / mem_total_mb * 100, 1) if mem_total_mb > 0 else 0.0
        swap_total_mb = meminfo.get('SwapTotal', 0) // 1024
        swap_free_mb  = meminfo.get('SwapFree', 0) // 1024
        swap_used_mb  = swap_total_mb - swap_free_mb
        swap_pct      = round(swap_used_mb / swap_total_mb * 100, 1) if swap_total_mb > 0 else 0.0
        ram = f"{mem_used_mb} / {mem_total_mb} MB ({mem_pct:.0f}%)"

        # Per-core CPU via /proc/stat delta
        curr_cores = self._read_proc_stat_cores()
        cpu_pcts = []
        for i in range(4):
            name = f'cpu{i}'
            if name in curr_cores and name in self._cpu_prev:
                d_total = curr_cores[name]['total'] - self._cpu_prev[name]['total']
                d_idle  = curr_cores[name]['idle']  - self._cpu_prev[name]['idle']
                pct = round((1.0 - d_idle / d_total) * 100.0, 1) if d_total > 0 else 0.0
                cpu_pcts.append(max(0.0, min(100.0, pct)))
            else:
                cpu_pcts.append(0.0)
        self._cpu_prev = curr_cores

        import os
        ros_domain = os.environ.get('ROS_DOMAIN_ID', '0')

        def _ip_up(ip: str) -> bool:
            return self._ip_status.get(ip, False)

        def _port_up(port: str) -> bool:
            return os.path.exists(port)

        gps_port = _symlink_port(
            'usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00',
            '/dev/ttyACM0')
        dht22_port = _symlink_port(
            'usb-1a86_USB_Serial-if00-port0',
            '/dev/ttyUSB0')

        def _disk_usage(path):
            try:
                r = subprocess.run(['df', '-h', path], capture_output=True, text=True, timeout=2)
                line = r.stdout.strip().splitlines()[-1].split()
                return f"{line[2]} / {line[1]} ({line[4]})"
            except Exception:
                return 'N/A'

        def _is_mounted(path):
            try:
                return path in open('/proc/mounts').read()
            except Exception:
                return False

        data_disk = _disk_usage('/media/arvc/DATASETS') if _is_mounted('/media/arvc/DATASETS') else 'Not mounted'

        env_vars = {
            'sections': [
                {
                    'title': 'Hardware',
                    'items': [
                        ('Model',       model),
                        ('Uptime',      uptime),
                        ('CPU Temp',    cpu_temp),
                        ('RAM',         ram),
                        ('ROS Domain',  ros_domain),
                    ],
                },
                {
                    'title': 'Storage',
                    'items': [
                        ('System (/)',            _disk_usage('/')),
                        ('Data (/media/arvc/DATASETS)', data_disk),
                    ],
                },
                {
                    'title': 'Connections',
                    'items': [
                        ('Visible IP',  '192.168.4.5',     _ip_up('192.168.4.5')),
                        ('LWIR IP',     '192.168.4.6',     _ip_up('192.168.4.6')),
                        ('LiDAR IP',    '192.168.4.4',     _ip_up('192.168.4.4')),
                        ('GPS Port',    gps_port,          _port_up(gps_port)),
                        ('DHT22 Port',  dht22_port,        _port_up(dht22_port)),
                    ],
                },
            ]
        }
        ptp_active = False
        ptp_offsets = {}
        try:
            import re
            r = subprocess.run(['pgrep', '-x', 'ptp4l'],
                               capture_output=True, text=True, timeout=2)
            ptp_active = r.returncode == 0
            if ptp_active:
                # phc2sys logs: "eth0 sys offset   38 s2 freq -63552 delay 1037"
                logs = subprocess.run(
                    ['journalctl', '-u', 'hitos_ptp_sync.service', '-n', '20', '--no-pager'],
                    capture_output=True, text=True, timeout=5)
                for line in reversed(logs.stdout.splitlines()):
                    m = re.search(r'eth0 sys offset\s+([-\d]+).*delay\s+([-\d]+)', line)
                    if m:
                        ptp_offsets['eth0'] = {
                            'offset': f'{m.group(1)} ns',
                            'delay':  f'{m.group(2)} ns',
                        }
                        break
        except Exception:
            pass

        return {
            'env': env_vars,
            'ptp_active': ptp_active,
            'ptp_offsets': ptp_offsets,
            'metrics': {
                'cpu_cores': cpu_pcts,
                'ram':  {'pct': mem_pct,  'used_mb': mem_used_mb,  'total_mb': mem_total_mb},
                'swap': {'pct': swap_pct, 'used_mb': swap_used_mb, 'total_mb': swap_total_mb},
            },
        }

    def publish_bool_topic(self, group: str, name: str,
                           value: bool = None) -> dict:
        if group not in self._topic_monitors:
            return {'success': False, 'message': f'Unknown group: {group}'}
        if name not in self._topic_monitors[group]:
            return {'success': False, 'message': f'Unknown topic: {name}'}
        mon = self._topic_monitors[group][name]
        topic_path = mon.topic
        if value is None:
            current = mon._last_data
            value = True if current is None else not bool(current)
        pub = self._bool_publishers.get(topic_path)
        if pub is None:
            pub = self.create_publisher(Bool, topic_path, _LATCHING_QOS)
            self._bool_publishers[topic_path] = pub
        try:
            msg = Bool()
            msg.data = bool(value)
            pub.publish(msg)
            return {'success': True, 'value': value,
                    'message': f'Published {value} to {topic_path}'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def call_ros_service(self, service_name: str) -> dict:
        """Call a std_srvs/srv/Trigger service via ros2 CLI."""
        try:
            r = subprocess.run(
                ['ros2', 'service', 'call', service_name, 'std_srvs/srv/Trigger', '{}'],
                capture_output=True, text=True, timeout=20)
            output = (r.stdout + r.stderr).strip()
            if r.returncode == 0:
                import re
                m = re.search(r"success=(\w+).*?message='([^']*)'", output, re.DOTALL)
                if m:
                    return {'success': m.group(1) == 'True', 'message': m.group(2) or 'ok'}
                return {'success': True, 'message': output or 'ok'}
            return {'success': False, 'message': output or 'service call failed'}
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'Service call timed out'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def get_full_status(self) -> dict:
        return {
            'topics':    self.get_topics_status(),
            'processes': self.get_processes_status(),
            'network':   self.get_network_status(),
            'system':    self.get_system_info(),
            'timestamp': time.time(),
        }
