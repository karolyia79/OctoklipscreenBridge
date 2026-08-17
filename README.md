# OctoklipscreenBridge

An OctoPrint plugin built specifically for the **OctoKlipScreen** project (fully compatible out-of-the-box), designed to bridge serial logs and printer status events via MQTT to external displays (such as CYD - Cheap Yellow Display).
While tailor-made for the CYD hardware ecosystem, it is fully open-source and freely usable for building any custom MQTT-based printer control or monitoring solution.

* **OctoClipScreen Repository**: [https://github.com/karolyia79/CYD_octoprint](https://github.com/karolyia79/CYD_octoprint)

## Features

* **Serial Communication Bridge**: Captures G-code sent (`Send:`) and received (`Recv:`) by the printer and publishes them to an MQTT topic in real time.
* **Status & Heartbeat Events**: Automatically publishes printer status updates (Operational, Printing, Paused, etc.) with retained messages. Status is automatically refreshed every 15 seconds (heartbeat) or instantly upon receiving a `STATUS` / `GET_STATUS` command.
* **Direct G-code Control**: Allows sending control commands directly to the OctoPrint printer terminal via MQTT.
* **OctoPrint Settings Integration**: Fully manageable through a dedicated configuration panel in the OctoPrint Settings menu.

## Requirements

* OctoPrint (v1.11.0 or newer)
* Python 3.11+
* An MQTT broker (such as Mosquitto) running locally or accessible on your network.

---

## Installation

You can install the plugin directly via the OctoPrint Plugin Manager or through the terminal using pip within your OctoPrint environment:

```
source ~/oprint/bin/activate
pip install [https://github.com/karolyia79/OctoklipscreenBridge/archive/refs/heads/main.zip](https://github.com/karolyia79/OctoklipscreenBridge/archive/refs/heads/main.zip)
sudo systemctl restart octoprint
```

---

## Configuration and Usage

1. Open your OctoPrint web interface and navigate to Settings (wrench icon).
2. Locate Octoklipscreen Bridge in the left-hand sidebar menu under Plugins.
3. Configure your connection options:
   * MQTT Host: Enter your broker address (e.g., localhost).
   * MQTT Port: Default is 1883.
   * MQTT Username / Password: Provide credentials if your broker requires authentication (leave blank otherwise).
   * MQTT Topic: The base topic used for messages (default: octoprint/serial). Note: Do not change this unless required by custom firmware, as the topic structure is strictly matched with the CYD display.
4. Click Save to apply your changes.

---

## IMPORTANT: Maximum Stability
For maximum stability, zero latency, and reliable local communication, it is highly recommended to run a dedicated local Mosquitto MQTT broker directly on the OctoPrint server (localhost).
If you need a lightweight MQTT broker running directly on your server, install Mosquitto with the following terminal commands:

```
sudo apt update
sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
```

## MQTT Topics Structure

The plugin utilizes the following MQTT topic structure based on your configured base topic (default: `octoprint/serial`):

* **`{base_topic}/serial`**
  * **Primary Purpose**: Transmitting real-time G-code communication logs to the display.
  * **Payload Type**: Single-line text messages.
  * **Example Payload**:
    ```text
    Send: N12 M105*38
    Recv: ok T:205.0 /205.0 B:60.0 /60.0 @:127
    ```
  * **Behavior**: Continuous data stream (sent instantly in real time as the printer communicates).

* **`{base_topic}/status`**
  * **Primary Purpose**: Simple text indicator of printing or connection status (`retain=True`).
  * **Payload Type**: Single-line status text.
  * **Example Payload**:
    ```text
    Printing: CCR20PRO_Test_hanoi_PETG.gcode
    ```
    or simply:
    ```text
    Operational
    ```
  * **Behavior**: 15-second timed heartbeat (scheduled update), plus instant updates on state changes or explicit requests.

* **`{base_topic}/printer`**
  * **Primary Purpose**: Official OctoPrint API compatible telemetry and live temperature data (`retain=True`).
  * **Payload Type**: Complete structured JSON package.
  * **Example Payload**:
    ```json
    {
      "sd": { "ready": false },
      "state": {
        "error": "",
        "flags": { "operational": true, "printing": false, "ready": true },
        "text": "Operational"
      },
      "temperature": {
        "bed": { "actual": 25.4, "offset": 0, "target": 0.0 },
        "tool0": { "actual": 26.68, "offset": 0, "target": 0.0 }
      }
    }
    ```
  * **Behavior**: 15-second timed schedule (heartbeat) and automatic updates upon state changes.

* **`{base_topic}/job`**
  * **Primary Purpose**: Active print job, file information, and progress telemetry (`retain=True`).
  * **Payload Type**: Detailed, complete structured JSON package.
  * **Example Payload**:
    ```json
    {
      "job": {
        "estimatedPrintTime": 1570.34,
        "file": { "name": "CCR20PRO_Test_hanoi_PETG.gcode", "size": 2358569 }
      },
      "progress": { "completion": 45.67, "printTime": 712, "printTimeLeft": 858 },
      "state": "Printing"
    }
    ```
  * **Behavior**: 15-second timed schedule (heartbeat) and event-driven updates.

* **`{base_topic}/profile`**
  * **Primary Purpose**: Querying the physical printer profile configuration (axes, build volume, nozzle diameter) (`retain=True`).
  * **Payload Type**: Complete, detailed JSON profile structure.
  * **Example Payload**:
    ```json
    {
      "profiles": {
        "_default": {
          "name": "CR20 Pro",
          "model": "CR20 Pro",
          "volume": { "width": 200.0, "depth": 200.0, "height": 200.0, "formFactor": "rectangular" },
          "extruder": { "count": 1, "nozzleDiameter": 0.4 }
        }
      }
    }
    ```
  * **Behavior**: Event-driven only (automatically published upon broker connection, or on-demand request); completely excluded from the 15-second heartbeat timer to eliminate unnecessary network traffic.

---

## MQTT Command & Request Control (`{base_topic}/command`)

You can use messages sent to the `{base_topic}/command` topic to control the printer or force immediate data publication across the other topics:

* **Data Request & Refresh Commands**:
  * **`STATUS`** or **`GET_STATUS`**: Forces an immediate, synchronized refresh across all live telemetry topics (`status`, `printer`, and `job`).
  * **`PROFILE`** or **`GET_PROFILE`**: Immediately queries and publishes the printer profile configuration to the `profile` topic.

* **Printer Control Commands**:
  * **Any valid G-code** (e.g., `M105`, `G28`, `M104 S200`): The plugin forwards the command directly to OctoPrint's printer terminal for execution.

### OctoklipscreenBridge • A stable and reliable bridge between OctoPrint and your CYD display. 
Built by András Károlyi (karolyia79) 🚀
