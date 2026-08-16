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
The plugin utilizes the following MQTT topic structure based on your configured base topic (default: octoprint/serial):
 * {base_topic}/serial
   - Purpose: Real-time G-code communication logs (Send: / Recv:).
* {base_topic}/status
   - Purpose: Printer and connection status updates (Operational, Printing, Paused, Failed, etc.) published with the retained flag (retain=True).
   - Behavior: Automatically refreshed every 15 seconds (heartbeat) and instantly updated upon state changes or when requested.
* {base_topic}/command
   - Purpose: Incoming control commands from the display. Send raw G-code (e.g., M105) to control the printer, or send STATUS / GET_STATUS to trigger an immediate status refresh on the status topic.

### OctoklipscreenBridge • A stable and reliable bridge between OctoPrint and your CYD display. 
Built by András Károlyi (karolyia79) 🚀
