#!/usr/bin/env python3
# encoding: utf-8

import os
import sys
import signal
import subprocess
import threading

from flask import Flask, jsonify, render_template, request
from werkzeug.serving import make_server

try:
    from ament_index_python.packages import get_package_share_directory
    _share = get_package_share_directory('hitos_setup')
    _web_dir = os.path.join(_share, 'web_manager')
except Exception:
    _web_dir = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, _web_dir)

from config import FLASK_CONFIG, GUI_LINKS, PROCESSES, TOPIC_GROUPS, NETWORK_INTERFACES, SENSOR_IPS  # noqa: E402

try:
    import rclpy
    from ros_monitor import HitosMonitor
    _using_ros = True
except ImportError as e:
    print(f'[HitosWebManager] ROS2 not available: {e}')
    _using_ros = False

# ---------------------------------------------------------------------------

app = Flask(__name__,
            template_folder=os.path.join(_web_dir, 'templates'),
            static_folder=os.path.join(_web_dir, 'static'))
app.json.sort_keys = False
# Cache CSS/JS for an hour. Flask's default (Cache-Control: no-cache) revalidates
# every asset on every load; over a relayed Husarnet link that round-trip can drop
# → unstyled page. With a max-age, one good load keeps it styled. Hard-refresh
# (Ctrl+Shift+R) bypasses it when editing assets.
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600

_monitor: 'HitosMonitor | None' = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html', gui_links=GUI_LINKS)


@app.route('/api/status')
def api_status():
    if _monitor is None:
        return jsonify({'error': 'Monitor not initialized'}), 503
    try:
        return jsonify(_monitor.get_full_status())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/topics')
def api_topics():
    if _monitor is None:
        return jsonify({'error': 'Monitor not initialized'}), 503
    return jsonify(_monitor.get_topics_status())


@app.route('/api/processes')
def api_processes():
    if _monitor is None:
        return jsonify({'error': 'Monitor not initialized'}), 503
    return jsonify(_monitor.get_processes_status())


@app.route('/api/processes/<name>/relaunch', methods=['POST'])
def api_relaunch(name):
    if _monitor is None:
        return jsonify({'error': 'Monitor not initialized'}), 503
    result = _monitor.relaunch_process(name)
    return jsonify(result), 200 if result.get('success') else 500


@app.route('/api/processes/<name>/stop', methods=['POST'])
def api_stop(name):
    if _monitor is None:
        return jsonify({'error': 'Monitor not initialized'}), 503
    result = _monitor.stop_process(name)
    return jsonify(result), 200 if result.get('success') else 500


@app.route('/api/processes/<name>/logs')
def api_logs(name):
    if _monitor is None:
        return jsonify({'error': 'Monitor not initialized'}), 503
    lines = request.args.get('lines', 100, type=int)
    return jsonify(_monitor.get_process_logs(name, lines))


@app.route('/api/topics/<group>/<name>/toggle', methods=['POST'])
def api_toggle(group, name):
    if _monitor is None:
        return jsonify({'error': 'Monitor not initialized'}), 503
    data = {}
    if request.content_length and request.content_length > 0:
        data = request.get_json(silent=True) or {}
    result = _monitor.publish_bool_topic(group, name, data.get('value'))
    return jsonify(result)


@app.route('/api/guis')
def api_guis():
    return jsonify(GUI_LINKS)


@app.route('/api/mode')
def api_mode_get():
    if _monitor is None:
        return jsonify({'error': 'Monitor not initialized'}), 503
    return jsonify(_monitor.get_capture_mode())


@app.route('/api/mode/calibration', methods=['POST'])
def api_mode_set():
    if _monitor is None:
        return jsonify({'error': 'Monitor not initialized'}), 503
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get('enabled', False))
    visible_hz = data.get('visible_hz', 4.0)
    result = _monitor.set_capture_mode(enabled, visible_hz)
    return jsonify(result), 200 if result.get('success') else 500


@app.route('/api/system/shutdown', methods=['POST'])
def api_shutdown():
    try:
        subprocess.Popen(['sudo', 'shutdown', '-h', 'now'])
        return jsonify({'success': True, 'message': 'Shutdown initiated'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ---------------------------------------------------------------------------
# Server thread
# ---------------------------------------------------------------------------

class _FlaskThread(threading.Thread):
    def __init__(self, host, port):
        super().__init__(daemon=True)
        self._server = make_server(host, port, app, threaded=True)

    def run(self):
        self._server.serve_forever()

    def shutdown(self):
        self._server.shutdown()


def _sigint_handler(sig, frame):
    global _monitor
    print('[HitosWebManager] SIGINT received.')
    if _using_ros and _monitor:
        _monitor.destroy_node()
        rclpy.shutdown()
    os._exit(0)


def main():
    signal.signal(signal.SIGINT, _sigint_handler)
    global _monitor

    host = FLASK_CONFIG['host']
    port = FLASK_CONFIG['port']

    if _using_ros:
        rclpy.init()
        _monitor = HitosMonitor(TOPIC_GROUPS, PROCESSES, NETWORK_INTERFACES, SENSOR_IPS)
        print(f'[HitosWebManager] Flask on {host}:{port}')
        flask_thread = _FlaskThread(host, port)
        flask_thread.start()
        try:
            rclpy.spin(_monitor)
        finally:
            _monitor.destroy_node()
            rclpy.shutdown()
    else:
        print(f'[HitosWebManager] Running without ROS2 on {host}:{port}')
        _FlaskThread(host, port).run()


if __name__ == '__main__':
    main()
