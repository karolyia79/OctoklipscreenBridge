# coding=utf-8
"""
OctoklipscreenBridge - OctoPrint plugin
Sends serial logs and job data via MQTT to CYD display
"""

import logging
import threading
import os
import json

import paho.mqtt.client as mqtt

import octoprint.plugin
from octoprint.util import RepeatedTimer

__all__ = ["OctoklipscreenBridgePlugin"]

logger = logging.getLogger(__name__)


class OctoklipscreenBridgePlugin(octoprint.plugin.StartupPlugin,
                                octoprint.plugin.SettingsPlugin,
                                octoprint.plugin.EventHandlerPlugin,
                                octoprint.plugin.TemplatePlugin):
    """
    OctoPrint plugin for bridging serial logs and job info to MQTT
    """

    def initialize(self):
        """Initialize the plugin"""
        self.mqtt_client = None
        self.serial_log_thread = None
        self._serial_log_file = None
        self._mqtt_connected = False
        self._status_timer = None
        
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
        return [dict(type="settings", name="Octoklipscreen Bridge")]
      
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

        # Időzítő indítása: 15 másodpercenként automatikusan kiküldi a státuszt, profilt és a job adatokat
        self._status_timer = RepeatedTimer(15.0, self._send_periodic_updates)
        self._status_timer.start()

    def on_shutdown(self):
        """Called when OctoPrint is shutting down"""
        logger.info("OctoklipscreenBridge plugin shutting down")
        if self._status_timer:
            self._status_timer.cancel()
            self._status_timer = None
        self._disconnect_mqtt()

    def on_event(self, event, payload):
        """Handle OctoPrint events and printer states"""
        if event == "PrinterStateChanged":
            state_text = payload.get("state_string", "Operational")
            self._send_mqtt_message("status", state_text)
            self._send_current_printer_profile()
            self._send_current_job()
        elif event == "PrintStarted":
            print_name = payload.get("name", "Unknown")
            self._send_mqtt_message("status", f"Printing: {print_name}")
            self._send_current_job()
        elif event == "PrintPaused":
            self._send_mqtt_message("status", "Paused")
            self._send_current_job()
        elif event == "PrintResumed":
            self._send_mqtt_message("status", "Printing")
            self._send_current_job()
        elif event == "PrintDone" or event == "PrintCancelled":
            self._send_mqtt_message("status", "Operational")
            self._send_current_job()
        elif event == "PrintFailed":
            reason = payload.get("reason", "Unknown reason")
            self._send_mqtt_message("status", f"Failed: {reason}")
            self._send_current_job()
        elif event == "Connected":
            self._send_mqtt_message("status", "Operational")
            self._send_current_printer_profile()
            self._send_current_job()
        elif event == "Disconnected":
            self._send_mqtt_message("status", "Offline")

    def _send_periodic_updates(self):
        """Időzített rutin a státusz, profil és job adatok együttes küldésére"""
        self._send_current_status()
        self._send_current_printer_profile()
        self._send_current_job()

    def _send_current_status(self):
        """Aktív státusz lekérdezése és küldése"""
        if not self._mqtt_connected:
            return
        state_text = "Operational"
        if hasattr(self, "_printer"):
            try:
                state_text = self._printer.get_state_string()
            except Exception:
                pass
        self._send_mqtt_message("status", state_text)

    def _send_current_printer_profile(self):
        """Aktív nyomtatóprofil nevének lekérdezése és küldése a /printer topicra"""
        if not self._mqtt_connected:
            return
        profile_name = "Unknown"
        if hasattr(self, "_printer"):
            try:
                profile = self._printer.get_current_printer_profile()
                if profile and "name" in profile:
                    profile_name = profile["name"]
            except Exception as e:
                logger.error(f"Error fetching printer profile: {e}")
        self._send_mqtt_message("printer", profile_name)

    def _send_current_job(self):
        """Aktuális job, haladás és fájl adatok lekérdezése és küldése a /job topicra JSON-ként"""
        if not self._mqtt_connected:
            return
        job_data = {}
        if hasattr(self, "_printer"):
            try:
                job_data = self._printer.get_current_data()
            except Exception as e:
                logger.error(f"Error fetching current job data: {e}")
        
        try:
            message = json.dumps(job_data)
        except Exception:
            message = "{}"
            
        self._send_mqtt_message("job", message)

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
            self.mqtt_client.on_message = self._on_mqtt_message

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
            self._send_periodic_updates()
            base_topic = self._settings.get(["mqtt_topic"])
            client.subscribe(f"{base_topic}/command", qos=1)
            logger.info(f"Subscribed to {base_topic}/command")
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

    def _on_mqtt_message(self, client, userdata, msg):
        """MQTT message callback for incoming commands"""
        try:
            command = msg.payload.decode("utf-8").strip()
            logger.info(f"Received MQTT command: {command}")
            
            if command.upper() in ["STATUS", "GET_STATUS"]:
                self._send_periodic_updates()
            elif command and hasattr(self, "_printer"):
                self._printer.commands(command)
        except Exception as e:
            logger.error(f"Error handling incoming MQTT message: {e}")

    def _send_mqtt_message(self, topic_suffix, message):
        """Send message to MQTT broker"""
        if not self._mqtt_connected or not self.mqtt_client:
            return False

        try:
            base_topic = self._settings.get(["mqtt_topic"])
            full_topic = f"{base_topic}/{topic_suffix}"
            
            # A status, printer és job topicok retained flaget kapnak
            is_retain = topic_suffix in ["status", "printer", "job"]
            result = self.mqtt_client.publish(full_topic, message, qos=1, retain=is_retain)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"Published to {full_topic} (retain={is_retain}): {message}")
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
                  displayVersion="0.7.1",
                  type="github_release",
                  user="karolyia79",
                  repo="OctoklipscreenBridge",
                  current="0.7.1",
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
__plugin_identifier__ = "octoklipscreen_bridge"
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
