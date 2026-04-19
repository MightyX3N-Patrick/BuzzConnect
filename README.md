# BuzzConnect

**BuzzConnect** is a Windows utility that bridges original Sony PlayStation Buzz! Buzzers to your PC as virtual Xbox 360 controllers. Whether you have the wired PS2 version or the wireless PS3 dongles, this tool lets you use them in any game or software that supports XInput (like *The Jackbox Party Pack*).

---

## ✨ Features

* **Automatic XInput Mapping:** Converts each physical buzzer into a separate virtual Xbox 360 controller.
* **Web Dashboard:** A built-in management suite accessible at `http://localhost:7843` to monitor inputs and manage devices.
* **Custom Mapping:** Rebind any of the five buzzer buttons (Red, Blue, Orange, Green, Yellow) to specific Xbox inputs (A, B, X, Y, Triggers, etc.).
* **Phone Pad Mode:** Scan a QR code on the dashboard to use your smartphone as a virtual buzzer for extra players.
* **Hardware Light Control:** Manually or programmatically trigger the iconic red LED lights on the buzzers via the web interface.
* **Zero-Configuration Setup:** The script automatically handles dependency installation (`vgamepad`, `pybuzzers`, etc.) and ViGEmBus driver setup internally on the first run.
* **System Tray Integration:** Runs quietly in the background with a system tray icon for easy access and management.

---

## 🛠️ Requirements

* **Windows 10 or 11**
* **Python 3.11+**
* **ViGEmBus Driver:** Required for Xbox controller emulation (the script will prompt to install this if missing).

---

## 🚀 Getting Started

### 1. Run the Script
Double-click `buzzconnect.pyw`. 

> **Note:** On the very first launch, the script will download necessary components in the background. It may take 30-60 seconds to initialize while it sets up your environment.

### 2. Access the Dashboard
Once the setup is complete, your default web browser will open to:
`http://localhost:7843`

From here, you can see connected buzzers, test buttons, and change your button mappings.

### 3. Background Operation
BuzzConnect lives in your **System Tray** (next to the clock). 
* **Right-click** the icon to Quit or quickly re-open the Dashboard.
* Closing the browser window will **not** stop the controller emulation; the script stays active in the tray so your controllers keep working during gameplay.

---

## 🔧 Troubleshooting

* **Missing Driver:** If controllers aren't appearing in your game, ensure the ViGEmBus installer finished successfully. You may need to restart your PC after the driver installation.
* **Invalid Distribution Warning:** If you see warnings regarding `~ywebview` in your console, these are leftover artifacts from previous attempts. The current version of BuzzConnect does not use webview and these warnings can be safely ignored, or cleared by deleting the tilde folders in your Python `site-packages` directory.
