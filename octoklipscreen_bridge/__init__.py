# coding=utf-8
"""
OctoklipscreenBridge - OctoPrint plugin
Sends serial logs via MQTT to CYD display
"""

import logging
import threading
import os

import paho.mqtt.client as mqtt

import octoprint.plugin
from octoprint.util import RepeatedTimer

__all__ = ["OctoklipscreenBridgePlugin"]

logger = logging.getLogger(__name__)


class OctoklipscreenBridgePlugin(octoprint.plugin.StartupPlugin,
                                octoprint.plugin.SettingsPlugin,
                                octoprint.plugin.EventHandlerPlugin):
    """
    OctoPrint plugin for bridging serial logs to MQTT
    """

    def initialize(self):
        """Initialize the plugin"""
        self.mqtt_client = None
        self.serial_log_thread = None
        self._serial_log_file = None
        self._mqtt_connected = False
        
        # Get OctoPrint base folder for serial.log location
        self._base_folder = self.get_plugin_data_folder()
        os.makedirs(self._base_folder, exist_ok=True)

    def get_settings_defaults(self):
        """Return default settings"""
        return {
            "mqtt_host": "localhost",
            "mqtt_port": 1883,
            "mqtt_username": "",
            "mqtt_password": "",
            "mqtt_topic": "octoprint/serial",
            "mqtt_enabled": True,
            "log_serial": True
        }

    def get_template_configs(self):
        """Return template configurations"""
        return [
            dict(type="settings", custom_bindings=False, name="Octoklipscreen Bridge")
        ]
      
    def process_gcode_sent(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
        """Elkapja a nyomtatónak küldött parancsokat"""
        self.send_serial_line(f"Send: {cmd}")
        return None

    def process_gcode_received(self, comm_instance, line, *args, **kwargs):
        """Elkapja a nyomtatótól érkező válaszokat"""
        self.send_serial_line(f"Recv: {line}")
        return line
      
    def on_after_startup(self):
        """Called after OctoPrint startup"""
        logger.info("OctoklipscreenBridge plugin started")
        
        if self._settings.get_boolean(["mqtt_enabled"]):
            self._connect_mqtt()
        else:
            logger.info("MQTT is disabled in settings")

    def on_shutdown(self):
        """Called when OctoPrint is shutting down"""
        logger.info("OctoklipscreenBridge plugin shutting down")
        self._disconnect_mqtt()

    def on_event(self, event, payload):
        """Handle OctoPrint events"""
        if event == "PrintStarted":
            self._send_mqtt_message("status", "Print started: " + payload.get("name", "Unknown"))
        elif event == "PrintDone":
            self._send_mqtt_message("status", "Print completed successfully")
        elif event == "PrintFailed":
            reason = payload.get("reason", "Unknown reason")
            self._send_mqtt_message("status", f"Print failed: {reason}")

    def _connect_mqtt(self):
        """Connect to MQTT broker safely without blocking startup"""
        try:
            host = self._settings.get(["mqtt_host"])
            port = self._settings.get_int(["mqtt_port"])
            username = self._settings.get(["mqtt_username"])
            password = self._settings.get(["mqtt_password"])

            if not host:
                logger.warning("MQTT host not configured")
                return

            try:
                self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=f"octoprint_{os.environ.get('HOSTNAME', 'octoprint')}")
            except AttributeError:
                self.mqtt_client = mqtt.Client(client_id=f"octoprint_{os.environ.get('HOSTNAME', 'octoprint')}")
            
            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
            self.mqtt_client.on_publish = self._on_mqtt_publish

            if username and password:
                self.mqtt_client.username_pw_set(username, password)

            logger.info(f"Attempting to connect to MQTT broker at {host}:{port}")
            self.mqtt_client.connect_async(host, port, keepalive=60)
            self.mqtt_client.loop_start()

        except Exception as e:
            logger.warning(f"MQTT broker not reachable yet (non-fatal): {e}")
            self.mqtt_client = None
            self._mqtt_connected = False

    def _disconnect_mqtt(self):
        """Disconnect from MQTT broker"""
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting from MQTT: {e}")
            finally:
                self.mqtt_client = None
                self._mqtt_connected = False

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """MQTT connection callback"""
        if rc == 0:
            logger.info("Connected to MQTT broker")
            self._mqtt_connected = True
            self._send_mqtt_message("status", "OctoklipscreenBridge connected")
        else:
            logger.error(f"MQTT connection failed with code {rc}")
            self._mqtt_connected = False

    def _on_mqtt_disconnect(self, client, userdata, rc):
        """MQTT disconnection callback"""
        self._mqtt_connected = False
        if rc != 0:
            logger.warning(f"Unexpected MQTT disconnection (code {rc})")
        else:
            logger.info("Disconnected from MQTT broker")

    def _on_mqtt_publish(self, client, userdata, mid):
        """MQTT publish callback"""
        pass

    def _send_mqtt_message(self, topic_suffix, message):
        """Send message to MQTT broker"""
        if not self._mqtt_connected or not self.mqtt_client:
            return False

        try:
            base_topic = self._settings.get(["mqtt_topic"])
            full_topic = f"{base_topic}/{topic_suffix}"
            
            result = self.mqtt_client.publish(full_topic, message, qos=1)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"Published to {full_topic}: {message}")
                return True
            else:
                logger.error(f"Failed to publish to {full_topic}: {result.rc}")
                return False
                
        except Exception as e:
            logger.error(f"Error publishing MQTT message: {e}")
            return False

    def send_serial_line(self, line):
        """Send a serial line to MQTT"""
        if self._settings.get_boolean(["mqtt_enabled"]):
            self._send_mqtt_message("serial", line.strip())

    def get_update_information(self):
          """Return update information"""
          return dict(
              octoklipscreen_bridge=dict(
                  displayName="Octoklipscreen Bridge",
                  displayVersion="0.4.7",
                  type="github_release",
                  user="karolyia79",
                  repo="OctoklipscreenBridge",
                  current="0.4.7",
                  stable_branch=dict(
                      name="Main",
                      branch="main",
                      comittish=["main"]
                  ),
                  prerelease_branches=[],
                  pip="https://github.com/karolyia79/OctoklipscreenBridge/archive/refs/heads/main.zip"
              )
          )

__plugin_name__ = "Octoklipscreen Bridge"
__plugin_pythoncompat__ = ">=3,<4"

def __plugin_load__():
    plugin = OctoklipscreenBridgePlugin()

    global __plugin_implementation__
    __plugin_implementation__ = plugin

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.comm.protocol.gcode.sent": __plugin_implementation__.process_gcode_sent,
        "octoprint.comm.protocol.gcode.received": __plugin_implementation__.process_gcode_received
    }
