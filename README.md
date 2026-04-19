# BuzzConnect

**BuzzConnect** is a Windows utility that bridges original Sony PlayStation Buzz! Buzzers to your PC as virtual Xbox 360 controllers. Whether you have the wired PS2 version or the wireless PS3 dongles, this tool lets you use them in any game or software that supports XInput (like *The Jackbox Party Pack*).

---

## ✨ Features

* **Automatic XInput Mapping:** Converts each physical buzzer into a separate virtual Xbox 360 controller.
* **Web Dashboard:** A built-in management suite accessible at `http://localhost:7843` to monitor inputs and manage devices.
* **Custom Mapping:** Rebind any of the five buzzer buttons (Red, Blue, Orange, Green, Yellow) to specific Xbox inputs (A, B, X, Y, Triggers, etc.).
* **Phone Pad Mode:** Scan a QR code to use your smartphone as a virtual buzzer/controller for extra players.
* **Hardware Light Control:** Manually or programmatically trigger the iconic red LED lights on the buzzers.
* **Integrated Installer:** Automatically checks for and installs missing dependencies like `vgamepad` and `pybuzzers` on launch.

---

## 🛠️ Requirements

* **Windows 10 or 11**
* **ViGEmBus Driver:** Required for Xbox controller emulation.
* **Python 3.8+** (If running from source)

---

## 🚀 Getting Started

### 1. Installation
The script is designed to handle its own setup. Simply run:
```bash
python buzzconnect.py
