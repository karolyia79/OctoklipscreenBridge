# OctoklipscreenBridge

An OctoPrint plugin designed to bridge serial logs and printer status events via MQTT to external displays (such as CYD - Cheap Yellow Display).

## Features

* **Serial Communication Bridge**: Captures G-code sent (`Send:`) and received (`Recv:`) by the printer and publishes them to an MQTT topic in real time.
* **Status Events**: Automatically publishes printer status updates (e.g., Print Started, Print Completed, Print Failed) to MQTT.
* **OctoPrint Settings Integration**: Fully manageable through a dedicated configuration panel in the OctoPrint Settings menu.

## Requirements

* OctoPrint (v1.11.0 or newer)
* Python 3.11+
* An MQTT broker (such as Mosquitto) running locally or accessible on your network.

## Installation

You can install the plugin directly via the OctoPrint Plugin Manager or through the terminal using pip within your OctoPrint environment:

```
source ~/oprint/bin/activate
pip install [https://github.com/karolyia79/OctoklipscreenBridge/archive/refs/heads/main.zip](https://github.com/karolyia79/OctoklipscreenBridge/archive/refs/heads/main.zip)
sudo systemctl restart octoprint
```

## Configuration and Usage

1. Open your OctoPrint web interface and navigate to Settings (wrench icon).
2. Locate Octoklipscreen Bridge in the left-hand sidebar menu under Plugins.
3. Configure your connection options:
   - Enable MQTT Bridge: Check to turn on the MQTT bridge.
   - MQTT Host: Enter your broker address (e.g., localhost).
   - MQTT Port: Default is 1883.
   - MQTT Username / Password: Provide credentials if your broker requires authentication (leave blank otherwise).
   - MQTT Topic: The base topic used for messages (default: octoprint/serial).

4. Click Save to apply your changes.

## MQTT Topics Structure

- Serial Logs: <base_topic>/serial (e.g., octoprint/serial)
- Status Messages: <base_topic>/status (e.g., octoprint/status)

## Setting Up a Local MQTT Broker (Mosquitto)
If you need a lightweight MQTT broker running directly on your OctoPi server, install Mosquitto with the following terminal commands:

```
sudo apt update
sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
```
