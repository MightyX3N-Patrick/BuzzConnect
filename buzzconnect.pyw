"""
BuzzConnect
"""

import asyncio
import datetime
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler

# ── Paths ──────────────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
    EXE_DIR  = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
    EXE_DIR  = BASE_DIR

MAPPING_FILE = os.path.join(EXE_DIR, "mapping.json")

# ── Check and install missing dependencies ─────────────────────────────────────
def check_vigem():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\ViGEmBus")
        winreg.CloseKey(k)
        return True
    except Exception:
        return False

def get_missing():
    missing = []
    for pkg, imp in [("pybuzzers","pybuzzers"), ("vgamepad","vgamepad"),
                     ("websockets","websockets"), ("pystray","pystray"),
                     ("Pillow","PIL")]:
        try:
            __import__(imp)
        except ImportError:
            missing.append(pkg)
    if not check_vigem():
        missing.append("vigem")
    return missing

def install_pip(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package,
                           "--quiet", "--disable-pip-version-check"])

def install_vigem():
    import urllib.request, tempfile
    api = "https://api.github.com/repos/nefarius/ViGEmBus/releases/latest"
    with urllib.request.urlopen(api, timeout=15) as r:
        data = json.loads(r.read())
    url = next(a["browser_download_url"] for a in data["assets"] if a["name"].endswith(".exe"))
    tmp = os.path.join(tempfile.gettempdir(), "ViGEmBus_Setup.exe")
    urllib.request.urlretrieve(url, tmp)
    subprocess.call([tmp], shell=False)
    try:
        os.remove(tmp)
    except Exception:
        pass

def uninstall_vigem():
    """Uninstall ViGEmBus via Windows registry uninstall string."""
    import winreg
    paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, path in paths:
        try:
            with winreg.OpenKey(hive, path) as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sub:
                            try:
                                name, _ = winreg.QueryValueEx(sub, "DisplayName")
                                if "vigem" in name.lower():
                                    uninstall_str, _ = winreg.QueryValueEx(sub, "UninstallString")
                                    subprocess.call(uninstall_str, shell=True)
                                    return
                            except Exception:
                                pass
                    except Exception:
                        pass
        except Exception:
            pass
    raise Exception("ViGEmBus uninstaller not found in registry")

def run_installer(missing):
    """Installs missing dependencies directly via pip/python."""
    for pkg in missing:
        try:
            if pkg == "vigem":
                print(f"Installing ViGEmBus driver...")
                install_vigem()
            else:
                print(f"Installing {pkg}...")
                install_pip(pkg)
        except Exception as e:
            print(f"Failed to install {pkg}: {e}")

# ── Config ─────────────────────────────────────────────────────────────────────
HTTP_PORT = 7843
WS_PORT   = 7844
NUM_SLOTS = 4
SCAN_SEC  = 3.0

BUZZ_BUTTONS = ["Red", "Blue", "Orange", "Green", "Yellow"]
DEVICE_NAMES = {0x0002: "Buzz Controller (PS2)", 0x1000: "Buzz Dongle (PS3/Wireless)"}
DEFAULT_MAPPING = {"Red": "RT", "Blue": "A", "Orange": "B", "Green": "X", "Yellow": "Y"}

XBOX_BUTTON_NAMES = [
    "A", "B", "X", "Y", "LB", "RB", "LT", "RT",
    "Start", "Back", "DPad Up", "DPad Down", "DPad Left", "DPad Right",
]
TRIGGER_MAP = {"LT": "left", "RT": "right"}

def get_local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# ── App state ──────────────────────────────────────────────────────────────────
class AppState:
    def __init__(self):
        self.devices  = {}  # path -> Device
        self._device_order = []  # paths in connection order
        self._lock    = threading.Lock()
        self.mapping  = self._load_mapping()
        self.clients  = set()
        self._ws_loop = None
        self.logs     = []
        self._ev_queue = queue.Queue()
        self._seen    = set()
        self._events  = []
        self._ev_lock = threading.Lock()
        self.vg_ok    = False
        self.XBOX_MAP = {}

    def buzzer_id(self, path, slot):
        """Return device:buzzer label e.g. 1:2"""
        try:
            di = self._device_order.index(path) + 1
        except ValueError:
            di = '?'
        return f"{di}:{slot+1}"

    def init_xbox(self):
        try:
            import vgamepad as vg
            self.XBOX_MAP = {
                "A":          vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
                "B":          vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
                "X":          vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
                "Y":          vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
                "LB":         vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
                "RB":         vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
                "Start":      vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
                "Back":       vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
                "DPad Up":    vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
                "DPad Down":  vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
                "DPad Left":  vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
                "DPad Right": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
            }
            self.vg_ok = True
            self.log("vgamepad ready")
        except Exception as e:
            self.log(f"vgamepad not available: {e}")

    def log(self, msg):
        entry = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
        self.logs.append(entry)
        if len(self.logs) > 300:
            self.logs = self.logs[-300:]
        print(entry)
        self.broadcast({"type": "log", "msg": entry})

    def _load_mapping(self):
        if os.path.exists(MAPPING_FILE):
            try:
                with open(MAPPING_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return {str(i): dict(DEFAULT_MAPPING) for i in range(NUM_SLOTS)}

    def save_mapping(self):
        with open(MAPPING_FILE, "w") as f:
            json.dump(self.mapping, f, indent=2)

    def slot_mapping(self, path, slot):
        key = f"{path}:{slot}"
        return self.mapping.get(key) or self.mapping.get(str(slot)) or DEFAULT_MAPPING

    def broadcast(self, msg):
        if not self._ws_loop:
            return
        data = json.dumps(msg)
        async def _do():
            dead = set()
            for ws in list(self.clients):
                try:
                    await ws.send(data)
                except Exception:
                    dead.add(ws)
            self.clients -= dead
        asyncio.run_coroutine_threadsafe(_do(), self._ws_loop)

    def full_state(self):
        with self._lock:
            devs = []
            for path, dev in self.devices.items():
                try:
                    lights = dev.bs.get_lights_state()
                except Exception:
                    lights = [False] * NUM_SLOTS
                devs.append({
                    "path":         path,
                    "name":         dev.name,
                    "active_slots": sorted(dev.active_slots),
                    "gamepads":     [s in dev.active_slots for s in range(NUM_SLOTS)],
                    "lights":       lights,
                })
        return {
            "type":    "state",
            "devices": devs,
            "mapping": self.mapping,
            "buttons": XBOX_BUTTON_NAMES,
            "logs":    list(self.logs),
            "vg_ok":   self.vg_ok,
            "active_buzzers": sum(len(d.active_slots) for d in self.devices.values()),
            "missing": [p for p,i in [("pybuzzers","pybuzzers"),("vgamepad","vgamepad"),("websockets","websockets"),("pystray","pystray"),("Pillow","PIL")] if not __import__("importlib").util.find_spec(i)],
            "vigem_ok": check_vigem(),
            "local_ip": get_local_ip(),
        }

    def press_xbox(self, path, slot, btn_name, pressed):
        if not self.vg_ok:
            return
        with self._lock:
            dev = self.devices.get(path)
        if not dev:
            return
        gp = dev.gamepads.get(slot)
        if not gp:
            return
        mapped = self.slot_mapping(path, slot).get(btn_name)
        if not mapped:
            return
        try:
            if mapped in TRIGGER_MAP:
                val = 255 if pressed else 0
                if TRIGGER_MAP[mapped] == "left":
                    gp.left_trigger(value=val)
                else:
                    gp.right_trigger(value=val)
            else:
                btn = self.XBOX_MAP.get(mapped)
                if not btn:
                    return
                gp.press_button(button=btn) if pressed else gp.release_button(button=btn)
            gp.update()
        except Exception as e:
            self.log(f"Xbox error: {e}")

    def release_all(self):
        with self._lock:
            devs = list(self.devices.values())
        for dev in devs:
            for gp in dev.gamepads.values():
                try:
                    gp.reset()
                    gp.update()
                except Exception:
                    pass

    def set_light(self, path, slot, on):
        with self._lock:
            dev = self.devices.get(path)
        if dev:
            try:
                dev.bs.set_light(slot, on)
                dev.lights[slot] = on
            except Exception as e:
                self.log(f"Light error: {e}")

    def set_all_lights(self, on):
        with self._lock:
            devs = list(self.devices.values())
        for dev in devs:
            try:
                dev.bs.set_lights_on() if on else dev.bs.set_lights_off()
                dev.lights = [on] * NUM_SLOTS
            except Exception:
                pass

    def push_event(self, buzzer, button, state):
        ev = {"buzzer": buzzer, "button": button, "state": state,
              "time": int(time.time() * 1000)}
        with self._ev_lock:
            self._events.append(ev)
            if len(self._events) > 500:
                self._events = self._events[-500:]

    def get_events_since(self, ts):
        with self._ev_lock:
            return [e for e in self._events if e["time"] > ts]

    def get_current_state(self):
        return {str(i+1): {b: False for b in BUZZ_BUTTONS} for i in range(NUM_SLOTS)}

    def _process_events(self):
        while True:
            try:
                path, slot, btn, pressed = self._ev_queue.get(timeout=0.1)
                if path == "pad":
                    with self._lock:
                        devs = list(self.devices.values())
                    dev = devs[0] if devs else None
                    if dev:
                        path = dev.path
                    else:
                        continue
                if pressed and self.vg_ok:
                    with self._lock:
                        dev = self.devices.get(path)
                    if dev and slot not in dev.active_slots:
                        try:
                            import vgamepad as vg
                            gp = vg.VX360Gamepad()
                            with self._lock:
                                dev.gamepads[slot] = gp
                                dev.active_slots.add(slot)
                            self.log(f"Xbox controller ready for {self.buzzer_id(path, slot)}")
                            self.broadcast(self.full_state())
                        except Exception as e:
                            self.log(f"Xbox controller failed for {self.buzzer_id(path, slot)}: {e}")
                if pressed:
                    self.log(f"Button DOWN: {self.buzzer_id(path, slot)} {btn}")
                self.press_xbox(path, slot, btn, pressed)
                self.push_event(slot+1, btn, "down" if pressed else "up")
                self.broadcast({"type": "button", "path": path,
                                "slot": slot, "btn": btn, "pressed": pressed})
            except queue.Empty:
                continue
            except Exception as e:
                self.log(f"Event error: {e}\n{traceback.format_exc()}")

    def _connect(self, bs):
        path = bs.path.decode() if isinstance(bs.path, bytes) else bs.path
        pid  = getattr(bs, "product_id", None) or getattr(bs, "_product_id", None)
        name = DEVICE_NAMES.get(pid, "Buzz Device")
        dev  = Device(path=path, name=name, bs=bs)
        with self._lock:
            self.devices[path] = dev
            self._seen.add(path)
            if path not in self._device_order:
                self._device_order.append(path)
        try:
            bs.set_lights_off()
        except Exception:
            pass

        def on_down(bset, buzzer, button):
            if button < len(BUZZ_BUTTONS):
                self._ev_queue.put((path, buzzer, BUZZ_BUTTONS[button], True))

        def on_up(bset, buzzer, button):
            if button < len(BUZZ_BUTTONS):
                self._ev_queue.put((path, buzzer, BUZZ_BUTTONS[button], False))

        bs.clear_handlers()
        bs.on_button_down(on_down)
        bs.on_button_up(on_up)
        bs.start_listening()
        with self._lock:
            di = self._device_order.index(path) + 1
        self.log(f"Device {di} connected: {name}")
        self.broadcast(self.full_state())

    def _scan_loop(self):
        while True:
            try:
                import pybuzzers
                found = pybuzzers.get_all_buzzers()
            except Exception as e:
                self.log(f"Scan error: {e}")
                time.sleep(SCAN_SEC)
                continue
            with self._lock:
                seen = set(self._seen)
            for bs in found:
                path = bs.path.decode() if isinstance(bs.path, bytes) else bs.path
                if path not in seen:
                    self.log(f"New device found")
                    self._connect(bs)
            time.sleep(SCAN_SEC)

    def start(self):
        threading.Thread(target=self._scan_loop,      daemon=True).start()
        threading.Thread(target=self._process_events, daemon=True).start()


class Device:
    def __init__(self, path, name, bs):
        self.path         = path
        self.name         = name
        self.bs           = bs
        self.gamepads     = {}
        self.active_slots = set()
        self.lights       = [False] * NUM_SLOTS


# ── HTTP ───────────────────────────────────────────────────────────────────────
class HttpHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, state=None, **kwargs):
        self.state = state
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def log_message(self, *a): pass

    def send_json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", len(b))
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()
        if self.path == "/gamepad.html":
            return super().do_GET()
        if self.path == "/api/status":
            return self.send_json(200, self.state.full_state())
        if self.path.startswith("/api/events"):
            from urllib.parse import urlparse, parse_qs
            ts  = int(parse_qs(urlparse(self.path).query).get("since", ["0"])[0])
            return self.send_json(200, {"events": self.state.get_events_since(ts)})
        if self.path == "/api/state":
            return self.send_json(200, {"buzzers": self.state.get_current_state()})
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n)) if n else {}
        except Exception:
            self.send_json(400, {"error": "bad json"}); return

        if self.path == "/api/light":
            on   = bool(body.get("state", False))
            path = body.get("path")
            slot = body.get("slot", "all")
            if path == "all" or not path:
                self.state.set_all_lights(on)
            elif slot == "all":
                with self.state._lock:
                    dev = self.state.devices.get(path)
                if dev:
                    try:
                        dev.bs.set_lights_on() if on else dev.bs.set_lights_off()
                        dev.lights = [on] * NUM_SLOTS
                    except Exception:
                        pass
            elif isinstance(slot, int) and 0 <= slot < NUM_SLOTS:
                self.state.set_light(path, slot, on)
            self.state.broadcast(self.state.full_state())
            self.send_json(200, {"ok": True})

        elif self.path == "/api/light/all":
            self.state.set_all_lights(bool(body.get("state", False)))
            self.state.broadcast(self.state.full_state())
            self.send_json(200, {"ok": True})

        elif self.path == "/api/mapping":
            mapping = body.get("mapping")
            if mapping:
                self.state.release_all()
                self.state.mapping = mapping
                self.state.save_mapping()
                self.state.broadcast(self.state.full_state())
            self.send_json(200, {"ok": True})

        elif self.path == "/api/pad":
            btn     = body.get("btn")
            pressed = bool(body.get("pressed", False))
            s       = int(body.get("slot", 0))
            x       = float(body.get("x", 0))
            y       = float(body.get("y", 0))

 # Calculate which physical device and which local buzzer to use
            d_idx = s // 4
            l_slot = s % 4

            def get_or_create_gp():
                with self.state._lock:
                    # Use the connection order to find the right physical device
                    if d_idx >= len(self.state._device_order):
                        return None
                    
                    path = self.state._device_order[d_idx]
                    dev = self.state.devices.get(path)
                
                if not dev:
                    return None

                gp = dev.gamepads.get(l_slot)
                if not gp and self.state.vg_ok:
                    try:
                        import vgamepad as vg
                        gp = vg.VX360Gamepad()
                        with self.state._lock:
                            dev.gamepads[l_slot] = gp
                            dev.active_slots.add(l_slot)
                    except Exception:
                        pass
                return dev.gamepads.get(l_slot)

            if btn == "stick":
                gp = get_or_create_gp()
                if gp:
                    try:
                        gp.left_joystick_float(x_value_float=x, y_value_float=-y)
                        gp.update()
                    except Exception:
                        pass
            elif btn:
                gp = get_or_create_gp()
                if gp:
                    try:
                        xbox_btn = self.state.XBOX_MAP.get(btn)
                        if xbox_btn:
                            if pressed:
                                gp.press_button(button=xbox_btn)
                            else:
                                gp.release_button(button=xbox_btn)
                            gp.update()
                    except Exception:
                        pass
            self.send_json(200, {"ok": True})

        elif self.path == "/api/install":
            pkg = body.get("package")
            def do_install():
                try:
                    self.state.log(f"Installing {pkg}...")
                    if pkg == "vigem":
                        install_vigem()
                    else:
                        install_pip(pkg)
                    self.state.log(f"Installed {pkg} successfully")
                    if pkg == "vgamepad":
                        self.state.init_xbox()
                except Exception as e:
                    self.state.log(f"Install failed for {pkg}: {e}")
                self.state.broadcast(self.state.full_state())
            threading.Thread(target=do_install, daemon=True).start()
            self.send_json(200, {"ok": True})

        elif self.path == "/api/uninstall":
            pkg = body.get("package")
            def do_uninstall():
                try:
                    self.state.log(f"Removing {pkg}...")
                    if pkg == "vigem":
                        uninstall_vigem()
                    else:
                        subprocess.check_call([sys.executable, "-m", "pip", "uninstall",
                                               pkg, "-y", "--quiet"])
                    self.state.log(f"Removed {pkg} successfully")
                except Exception as e:
                    self.state.log(f"Remove failed for {pkg}: {e}")
                self.state.broadcast(self.state.full_state())
            threading.Thread(target=do_uninstall, daemon=True).start()
            self.send_json(200, {"ok": True})

        else:
            self.send_json(404, {"error": "not found"})


# ── WebSocket ──────────────────────────────────────────────────────────────────
async def ws_handler(state, websocket):
    state.clients.add(websocket)
    try:
        await websocket.send(json.dumps(state.full_state()))
        async for _ in websocket:
            pass
    except Exception:
        pass
    finally:
        state.clients.discard(websocket)


def start_ws(state):
    from websockets import serve as ws_serve
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    state._ws_loop = loop
    async def _run():
        async with ws_serve(partial(ws_handler, state), "0.0.0.0", WS_PORT):
            await asyncio.Future()
    loop.run_until_complete(_run())


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    # Check for missing dependencies and install them directly
    missing = get_missing()
    if missing:
        print(f"Missing: {missing} — downloading dependencies...")
        run_installer(missing)
        # Re-check after install
        missing = get_missing()
        if missing:
            print(f"Still missing after install: {missing}")

    state = AppState()

    _orig = threading.excepthook
    def _hook(args):
        try:
            msg = "".join(traceback.format_exception(
                args.exc_type, args.exc_value, getattr(args, "exc_tb", None)))
            state.log(f"CRASH [{getattr(args.thread,'name','?')}]:\n{msg}")
        except Exception:
            pass
        _orig(args)
    threading.excepthook = _hook

    state.log("BuzzConnect starting...")
    state.init_xbox()
    state.start()

    try:
        import websockets
        threading.Thread(target=start_ws, args=(state,), daemon=True).start()
    except ImportError:
        state.log("websockets not available")

    handler = partial(HttpHandler, state=state)
    httpd   = HTTPServer(("0.0.0.0", HTTP_PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    state.log(f"Ready — http://127.0.0.1:{HTTP_PORT}")

    # Install pystray and Pillow if missing before trying to use them
    for pkg in ["pystray", "Pillow"]:
        try:
            __import__(pkg.lower())
        except ImportError:
            try:
                install_pip(pkg)
            except Exception as e:
                state.log(f"Could not install {pkg}: {e}")

    import webbrowser
    webbrowser.open(f"http://127.0.0.1:{HTTP_PORT}")

    # ── Tray icon ──────────────────────────────────────────────────────────────
    try:
        import pystray
        from PIL import Image

        ico_path = os.path.join(EXE_DIR, "buzzconnect.ico")
        if os.path.exists(ico_path):
            tray_image = Image.open(ico_path)
        else:
            from PIL import ImageDraw
            tray_image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(tray_image)
            d.ellipse([4, 4, 60, 60], fill="#e74c3c")
            d.ellipse([18, 18, 46, 46], fill="#922b21")

        def on_open(icon, item):
            webbrowser.open(f"http://127.0.0.1:{HTTP_PORT}")

        def on_quit(icon, item):
            state.set_all_lights(False)
            httpd.shutdown()
            icon.stop()

        menu = pystray.Menu(
            pystray.MenuItem("Open BuzzConnect", on_open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_quit),
        )
        icon = pystray.Icon("BuzzConnect", tray_image, "BuzzConnect", menu)
        icon.run()

    except Exception as e:
        state.log(f"Tray icon failed: {e} — running headless")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    state.set_all_lights(False)
    httpd.shutdown()


if __name__ == "__main__":
    main()
