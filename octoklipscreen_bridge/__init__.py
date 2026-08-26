# coding=utf-8
"""OctoklipscreenBridge - OctoPrint plugin

Sends serial logs, status, printer state/temps, profiles and job data via MQTT
to CYD display. Includes server-side statistics and REST API management with
unique file names.
"""

import json
import logging
import os
import threading
import time

import flask

import octoprint.plugin
from octoprint.util import RepeatedTimer
import paho.mqtt.client as mqtt

__all__ = ["OctoklipscreenBridgePlugin"]

logger = logging.getLogger(__name__)


class OctoklipscreenBridgePlugin(
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.BlueprintPlugin,
):
    """OctoPrint plugin for bridging serial logs, printer info to MQTT, and

    managing server-side print statistics with dedicated storage.
    """

    def initialize(self):
        """Initialize the plugin"""
        self.mqtt_client = None
        self.serial_log_thread = None
        self._serial_log_file = None
        self._mqtt_connected = False
        self._status_timer = None

        # Get OctoPrint base folder for data storage
        self._base_folder = self.get_plugin_data_folder()
        os.makedirs(self._base_folder, exist_ok=True)

        # Statistics runtime variables
        self._print_start_time = 0
        self._current_material = "EGYÉB"
        self._active_system = "OctoPrint"

        # Initialize config and CSV with unique names if not present
        self._init_stats_storage()

    # --- Settings Defaults ---
    def get_settings_defaults(self):
        return dict(
            mqtt_enabled=True,
            mqtt_host="localhost",
            mqtt_port=1883,
            mqtt_username="",
            mqtt_password="",
            mqtt_topic="octoprint/serial",
            stat_enabled=True,
            stat_currency="Ft",
            stat_cost_kwh=5.0,
            stat_power_w=250.0,
            materials=[
                dict(name="PLA", n_min=180, n_max=220, b_min=40, b_max=65),
                dict(name="PETG", n_min=225, n_max=250, b_min=65, b_max=85),
            ],
        )

    def get_template_configs(self):
        """Return template configurations"""
        return [dict(type="settings", name="Octoklipscreen Bridge")]

    # --- Settings Lifecycle Hooks ---
    def on_settings_load(self):
        data = super().on_settings_load()
        try:
            cfg = self._load_config()
            data["stat_enabled"] = cfg.get("enabled", True)
            data["stat_currency"] = cfg.get("currency", "Ft")
            data["stat_cost_kwh"] = cfg.get("cost_kwh", 5.0)
            data["stat_power_w"] = cfg.get("power_w", 250.0)
            data["materials"] = cfg.get("materials", [])
        except Exception as e:
            logger.error(f"[STAT] Hiba az on_settings_load során: {e}")
        return data

    def on_settings_save(self, data):
        # 1. Előbb frissítjük az OctoPrint saját settings tárát
        saved_data = super().on_settings_save(data)
        try:
            # 2. A frissült adatok biztonságos kinyerése és elmentése a saját opiklipscreenstat.json-be
            cfg = {
                "enabled": self._settings.get_boolean(["stat_enabled"]),
                "currency": self._settings.get(["stat_currency"]),
                "cost_kwh": self._settings.get_float(["stat_cost_kwh"]),
                "power_w": self._settings.get_float(["stat_power_w"]),
                "materials": self._settings.get(["materials"]),
            }
            self._save_config(cfg)
        except Exception as e:
            logger.error(f"[STAT] Hiba az on_settings_save során: {e}")

        # 3. KÖTELEZŐ visszaadni a szótárat az OctoPrint felé!
        return saved_data

    # --- Gcode Hooks ---
    def process_gcode_sent(
        self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs
    ):
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

        # Időzítő indítása: 1 másodpercenként automatikusan kiküldi a státuszt
        self._status_timer = RepeatedTimer(1.0, self._send_periodic_updates)
        self._status_timer.start()

    def on_shutdown(self):
        """Called when OctoPrint is shutting down"""
        logger.info("OctoklipscreenBridge plugin shutting down")
        if self._status_timer:
            self._status_timer.cancel()
            self._status_timer = None
        self._disconnect_mqtt()

    # --- Event Handler (MQTT + Stats integration) ---
    def on_event(self, event, payload):
        """Handle OctoPrint events and printer states"""
        if event == "PrinterStateChanged":
            state_text = payload.get("state_string", "Operational")
            self._send_mqtt_message("status", state_text)
            self._send_current_printer_info()
            self._send_current_job()

        elif event == "PrintStarted":
            print_name = payload.get("name", "Unknown")
            self._send_mqtt_message("status", f"Printing: {print_name}")
            self._send_current_job()
            self._handle_print_started(payload)

        elif event == "PrintPaused":
            self._send_mqtt_message("status", "Paused")
            self._send_current_job()
        elif event == "PrintResumed":
            self._send_mqtt_message("status", "Printing")
            self._send_current_job()

        elif event == "PrintDone":
            self._send_mqtt_message("status", "Operational")
            self._send_current_job()
            self._handle_print_finished(success=True)

        elif event == "PrintCancelled":
            self._send_mqtt_message("status", "Operational")
            self._send_current_job()
            self._handle_print_finished(success=False)

        elif event == "PrintFailed":
            reason = payload.get("reason", "Unknown reason")
            self._send_mqtt_message("status", f"Failed: {reason}")
            self._send_current_job()
            self._handle_print_finished(success=False)

        elif event == "Connected":
            self._send_mqtt_message("status", "Operational")
            self._send_current_printer_info()
            self._send_current_job()
            self._send_printer_profile()
        elif event == "Disconnected":
            self._send_mqtt_message("status", "Offline")

    # --- Periodikus MQTT küldések ---
    def _send_periodic_updates(self):
        self._send_current_status()
        self._send_current_printer_info()
        self._send_current_job()

    def _send_current_status(self):
        if not self._mqtt_connected:
            return
        state_text = "Operational"
        if hasattr(self, "_printer"):
            try:
                state_text = self._printer.get_state_string()
            except Exception:
                pass
        self._send_mqtt_message("status", state_text)

    def _send_current_printer_info(self):
        if not self._mqtt_connected:
            return
        printer_data = {}
        if hasattr(self, "_printer"):
            try:
                temps = self._printer.get_current_temperatures()
                state_string = self._printer.get_state_string()
                is_operational = self._printer.is_operational()
                is_printing = self._printer.is_printing()
                is_paused = self._printer.is_paused()

                printer_data = {
                    "sd": {"ready": False},
                    "state": {
                        "error": "",
                        "flags": {
                            "cancelling": False,
                            "closedOrError": False,
                            "error": False,
                            "finishing": False,
                            "operational": is_operational,
                            "paused": is_paused,
                            "pausing": False,
                            "printing": is_printing,
                            "ready": (
                                is_operational and not is_printing and not is_paused
                            ),
                            "resuming": False,
                            "sdReady": False,
                        },
                        "text": state_string,
                    },
                    "temperature": temps if temps else {},
                }
            except Exception as e:
                logger.error(f"Error fetching printer info: {e}")

        try:
            message = json.dumps(printer_data)
        except Exception:
            message = "{}"
        self._send_mqtt_message("printer", message)

    def _send_printer_profile(self):
        if not self._mqtt_connected:
            return
        profiles_data = {}
        try:
            if hasattr(self, "_printer_profile_manager"):
                all_profiles = self._printer_profile_manager.get_all()
                if all_profiles:
                    profiles_data = {"profiles": all_profiles}
        except Exception as e:
            logger.error(f"Error fetching printer profiles: {e}")

        try:
            message = json.dumps(profiles_data)
        except Exception:
            message = "{}"
        self._send_mqtt_message("profile", message)

    def _send_current_job(self):
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

    # --- MQTT Kliens Logika ---
    def _connect_mqtt(self):
        try:
            host = self._settings.get(["mqtt_host"])
            port = self._settings.get_int(["mqtt_port"])
            username = self._settings.get(["mqtt_username"])
            password = self._settings.get(["mqtt_password"])

            if not host:
                logger.warning("MQTT host not configured")
                return

            try:
                self.mqtt_client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION1,
                    client_id=f"octoprint_{os.environ.get('HOSTNAME', 'octoprint')}",
                )
            except AttributeError:
                self.mqtt_client = mqtt.Client(
                    client_id=f"octoprint_{os.environ.get('HOSTNAME', 'octoprint')}"
                )

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
        if rc == 0:
            logger.info("Connected to MQTT broker")
            self._mqtt_connected = True
            self._send_periodic_updates()
            self._send_printer_profile()
            base_topic = self._settings.get(["mqtt_topic"])
            client.subscribe(f"{base_topic}/command", qos=1)
        else:
            logger.error(f"MQTT connection failed with code {rc}")
            self._mqtt_connected = False

    def _on_mqtt_disconnect(self, client, userdata, rc):
        self._mqtt_connected = False

    def _on_mqtt_publish(self, client, userdata, mid):
        pass

    def _on_mqtt_message(self, client, userdata, msg):
        try:
            command = msg.payload.decode("utf-8").strip()
            if command.upper() in ["PROFILE", "GET_PROFILE"]:
                self._send_printer_profile()
            elif command and hasattr(self, "_printer"):
                self._printer.commands(command)
        except Exception as e:
            logger.error(f"Error handling incoming MQTT message: {e}")

    def _send_mqtt_message(self, topic_suffix, message):
        if not self._mqtt_connected or not self.mqtt_client:
            return False
        try:
            base_topic = self._settings.get(["mqtt_topic"])
            full_topic = f"{base_topic}/{topic_suffix}"
            is_retain = topic_suffix in ["status", "printer", "job", "profile"]
            result = self.mqtt_client.publish(
                full_topic, message, qos=1, retain=is_retain
            )
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            return False

    def send_serial_line(self, line):
        if self._settings.get_boolean(["mqtt_enabled"]):
            self._send_mqtt_message("serial", line.strip())

    # =========================================================
    # --- SZERVER OLDALI STATISZTIKA MODUL ---
    # =========================================================

    def _get_json_path(self):
        return os.path.join(self._base_folder, "opiklipscreenstat.json")

    def _get_csv_path(self):
        return os.path.join(self._base_folder, "opiklipscreenstat.csv")

    def _init_stats_storage(self):
        try:
            os.makedirs(self._base_folder, exist_ok=True)
        except Exception as e:
            logger.error(f"[STAT] Hiba a data mappa létrehozásakor: {e}")

        json_path = self._get_json_path()
        if not os.path.exists(json_path):
            default_config = {
                "enabled": True,
                "cost_kwh": 5.0,
                "power_w": 250.0,
                "currency": "Ft",
                "materials": [
                    {
                        "name": "PLA",
                        "n_min": 180,
                        "n_max": 220,
                        "b_min": 40,
                        "b_max": 65,
                    },
                    {
                        "name": "PETG",
                        "n_min": 225,
                        "n_max": 250,
                        "b_min": 65,
                        "b_max": 85,
                    },
                    {
                        "name": "ABS",
                        "n_min": 240,
                        "n_max": 280,
                        "b_min": 90,
                        "b_max": 115,
                    },
                    {
                        "name": "TPU",
                        "n_min": 200,
                        "n_max": 230,
                        "b_min": 20,
                        "b_max": 50,
                    },
                ],
            }
            try:
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(default_config, f, indent=4)
            except Exception as e:
                logger.error(f"Error creating default opiklipscreenstat.json: {e}")

        csv_path = self._get_csv_path()
        if not os.path.exists(csv_path):
            try:
                with open(csv_path, "w", encoding="utf-8") as f:
                    f.write("Rendszer,Anyag,Masodperc,Siker,Koltseg\n")
            except Exception as e:
                logger.error(f"Error creating default opiklipscreenstat.csv: {e}")

    def _load_config(self):
        json_path = self._get_json_path()
        default_config = {
            "enabled": True,
            "cost_kwh": 5.0,
            "power_w": 250.0,
            "currency": "Ft",
            "materials": [
                {
                    "name": "PLA",
                    "n_min": 180,
                    "n_max": 220,
                    "b_min": 40,
                    "b_max": 65,
                },
                {
                    "name": "PETG",
                    "n_min": 225,
                    "n_max": 250,
                    "b_min": 65,
                    "b_max": 85,
                },
                {
                    "name": "ABS",
                    "n_min": 240,
                    "n_max": 280,
                    "b_min": 90,
                    "b_max": 115,
                },
                {
                    "name": "TPU",
                    "n_min": 200,
                    "n_max": 230,
                    "b_min": 20,
                    "b_max": 50,
                },
            ],
        }

        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if not content:
                        return default_config
                    cfg = json.loads(content)
                    if "materials" not in cfg or not cfg["materials"]:
                        cfg["materials"] = default_config["materials"]
                    return cfg
            except Exception as e:
                logger.error(f"Error loading opiklipscreenstat.json: {e}")

        return default_config

    def _save_config(self, cfg):
        json_path = self._get_json_path()
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4)
            return True
        except Exception as e:
            logger.error(f"Error saving opiklipscreenstat.json: {e}")
            return False

    def _determine_material(self, nozzle_target, bed_target):
        cfg = self._load_config()
        for rule in cfg.get("materials", []):
            if rule.get("n_min", 0) <= nozzle_target <= rule.get(
                "n_max", 0
            ) and rule.get("b_min", 0) <= bed_target <= rule.get("b_max", 0):
                return rule.get("name", "EGYÉB")
        return "EGYÉB"

    def _handle_print_started(self, payload):
        cfg = self._load_config()
        if not cfg.get("enabled", True):
            return

        self._print_start_time = time.time()

        nozzle_target = 0.0
        bed_target = 0.0
        try:
            if hasattr(self, "_printer"):
                temps = self._printer.get_current_temperatures()
                if temps:
                    nozzle_target = temps.get("tool0", {}).get("target", 0.0) or 0.0
                    bed_target = temps.get("bed", {}).get("target", 0.0) or 0.0
        except Exception:
            pass

        self._current_material = self._determine_material(
            nozzle_target, bed_target
        )
        logger.info(f"[STAT] Nyomtatás elindult - Anyag: {self._current_material}")

    def _handle_print_finished(self, success):
        cfg = self._load_config()
        if not cfg.get("enabled", True) or self._print_start_time == 0:
            return

        duration_seconds = int(time.time() - self._print_start_time)
        self._print_start_time = 0

        if duration_seconds < 5:
            logger.info("[STAT] Túl rövid nyomtatási idő (<5s), mentés kihagyva.")
            return

        power_w = cfg.get("power_w", 250.0)
        cost_kwh = cfg.get("cost_kwh", 5.0)
        energy_kwh = (power_w / 1000.0) * (duration_seconds / 3600.0)
        current_cost = energy_kwh * cost_kwh

        csv_path = self._get_csv_path()
        try:
            with open(csv_path, "a", encoding="utf-8") as f:
                f.write(
                    f"{self._active_system},{self._current_material},{duration_seconds},{1 if success else 0},{current_cost:.2f}\n"
                )
            logger.info(
                f"[STAT] Nyomtatás rögzítve -> Idő: {duration_seconds}mp, Siker:"
                f" {success}, Költség: {current_cost:.2f}"
            )
        except Exception as e:
            logger.error(f"[STAT] Hiba a CSV mentésekor: {e}")

    def _aggregate_stats(self):
        cfg = self._load_config()
        stats = {
            "totalTimeOcto": 0,
            "totalTimeKlipper": 0,
            "successCountOcto": 0,
            "failCountOcto": 0,
            "successCountKlipper": 0,
            "failCountKlipper": 0,
            "totalCost": 0.0,
            "failCost": 0.0,
        }
        mat_times = {}

        csv_path = self._get_csv_path()
        if os.path.exists(csv_path):
            try:
                with open(csv_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    for line in lines[1:]:
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split(",")
                        if len(parts) >= 5:
                            sys = parts[0]
                            mat = parts[1]
                            dur = int(parts[2])
                            succ = int(parts[3]) == 1
                            cst = float(parts[4])

                            stats["totalCost"] += cst
                            if not succ:
                                stats["failCost"] += cst

                            if sys == "OctoPrint":
                                stats["totalTimeOcto"] += dur
                                if succ:
                                    stats["successCountOcto"] += 1
                                else:
                                    stats["failCountOcto"] += 1
                            elif sys == "Klipper":
                                stats["totalTimeKlipper"] += dur
                                if succ:
                                    stats["successCountKlipper"] += 1
                                else:
                                    stats["failCountKlipper"] += 1

                            mat_times[mat] = mat_times.get(mat, 0) + dur
            except Exception as e:
                logger.error(f"[STAT] Hiba a CSV olvasásakor: {e}")

        return {
            "config": cfg,
            "stats": stats,
            "mat_times": mat_times,
            "status": "ok",
        }

    # --- Blueprint API Configuration ---
    def is_blueprint_protected(self):
        return False

    def get_blueprint_url_prefix(self):
        return ""

    @octoprint.plugin.BlueprintPlugin.route("/stats/data", methods=["GET"])
    def get_stats_data(self):
        data = self._aggregate_stats()

        if hasattr(self, "_printer"):
            try:
                if self._printer.is_printing():
                    data["status"] = "printing"
            except Exception:
                pass

        return flask.jsonify(data)

    @octoprint.plugin.BlueprintPlugin.route("/stats/save", methods=["POST"])
    def save_stats_config(self):
        try:
            req_data = flask.request.get_json()
            if req_data:
                self._save_config(req_data)
                return flask.jsonify({"success": True})
        except Exception as e:
            logger.error(f"[STAT] Hiba a beállítások mentésekor: {e}")
        return flask.jsonify({"success": False}), 400

    @octoprint.plugin.BlueprintPlugin.route("/stats/reset", methods=["POST"])
    def reset_stats_data(self):
        try:
            csv_path = self._get_csv_path()
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("Rendszer,Anyag,Masodperc,Siker,Koltseg\n")
            return flask.jsonify({"success": True})
        except Exception as e:
            logger.error(f"[STAT] Hiba a statisztika törlésekor: {e}")
            return flask.jsonify({"success": False}), 400

    # --- Plugin Info ---
    def get_update_information(self):
        return dict(
            octoklipscreen_bridge=dict(
                displayName="Octoklipscreen Bridge",
                displayVersion="0.8.4",
                type="github_release",
                user="karolyia79",
                repo="OctoklipscreenBridge",
                current="0.8.4",
                stable_branch=dict(
                    name="Main", branch="main", commitish=["main"]
                ),
                prerelease_branches=[],
                pip=(
                    "https://github.com/karolyia79/OctoklipscreenBridge/archive/refs/heads/main.zip"
                ),
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
        "octoprint.comm.protocol.gcode.sent": (
            __plugin_implementation__.process_gcode_sent
        ),
        "octoprint.comm.protocol.gcode.received": (
            __plugin_implementation__.process_gcode_received
        ),
    }
