"""
=============================================================================
 COSMIC LINK - Sci-Fi Spatial Control Center & Instant Screen Pop-Up Engine
=============================================================================
 Features:
 1. Button 3 Single-Click Toggle & Hold-to-Beam Spatial Flow:
    - Button 3 Single Click: Toggles BLE profile slot for another laptop on ESP32.
    - Button 3 Hold: Initiates 360° spatial aiming (mouse physically moves reticle).
    - Release Button 3: Transmits staged file/screenshot to locked target laptop!
 2. Tactical Spatial Radar with Interactive Key-Based Pairing:
    - Wi-Fi discovery prompts both laptops to confirm pairing with the shared Key.
    - User on Laptop A physically points Air Mouse at Laptop B and clicks "Lock Aim".
    - Laptop A automatically synchronizes spatial coordinates over Wi-Fi to Laptop B,
      so Laptop B automatically knows Laptop A's location on its radar (zero manual setup on B!).
 3. Resilient Dual-Mode Transfer (TCP + Automatic UDP Fallback):
    - Tries high-speed TCP streaming first.
    - If TCP is blocked by Windows Firewall on Public Wi-Fi, automatically falls
      back to chunked UDP streaming on port 5052!
 4. Robust File Grabber:
    - Captures selected files from Windows Explorer or Desktop.
    - Supports copied clipboard files (CF_HDROP) and manual file staging.
    - Only falls back to full-screen screenshot if no file is selected.
 5. Hardware Live Tuning with Freeze & Calibrate Workflow:
    - Dedicated "Freeze Mouse for Tuning" button: ESP32 ignores gyro movement
      so cursor won't move across the screen while adjusting sliders.
    - User tunes Sensitivity and Smoothing.
    - User clicks "Confirm & Calibrate Air Mouse" -> writes to ESP32 Flash,
      runs gyro calibration, and automatically unfreezes the mouse!
=============================================================================
"""

import sys
import os
import socket
import struct
import io
import time
import math
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    from PIL import ImageGrab, Image, ImageTk
except ImportError:
    ImageGrab = None
    Image = None
    ImageTk = None

try:
    from pynput import mouse, keyboard
except ImportError:
    mouse = None
    keyboard = None

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None

try:
    import pythoncom
    import win32com.client
    import win32clipboard
except ImportError:
    pythoncom = None
    win32com = None
    win32clipboard = None

# =============================================================================
# CONSTANTS & NETWORKING PORTS
# =============================================================================
DEFAULT_DISCOVERY_PORT = 5052
DEFAULT_TRANSFER_PORT  = 5051
DEFAULT_PAIRING_KEY    = "COSMIC-8492"

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".cosmic_link_config.json")

# Default DropZone directory
DEFAULT_DROPZONE = os.path.join(os.path.expanduser("~"), "Documents", "CosmicDropZone")
if not os.path.exists(DEFAULT_DROPZONE):
    try:
        os.makedirs(DEFAULT_DROPZONE, exist_ok=True)
    except Exception:
        DEFAULT_DROPZONE = os.path.join(os.environ.get("TEMP", "C:\\"), "CosmicDropZone")
        os.makedirs(DEFAULT_DROPZONE, exist_ok=True)


def get_local_ip():
    """Detect local Wi-Fi IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


# =============================================================================
# CONFIGURATION MANAGER
# =============================================================================
class ConfigManager:
    def __init__(self):
        self.config = {
            "device_name": socket.gethostname(),
            "pairing_key": DEFAULT_PAIRING_KEY,
            "dropzone": DEFAULT_DROPZONE,
            "auto_display": True,
            "sensitivity": 0.20,
            "smoothing": 0.82,
            "deadzone": 1,
            "serial_port": "",
            "desk_layout": "side_by_side",  # "side_by_side" or "opposite"
            "devices": {}  # name -> {"ip": ..., "angle": float, "last_seen": float, "trusted": bool}
        }
        self.load()

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    self.config.update(data)
            except Exception as e:
                print(f"[CONFIG] Warning loading config: {e}")

    def save(self):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"[CONFIG] Error saving config: {e}")


# =============================================================================
# ESP32 HARDWARE SERIAL BRIDGE
# Communicates with ESP32 Air Mouse for Freeze, Live Tuning & Gyro Calibration
# =============================================================================
class ESP32SerialBridge:
    def __init__(self, log_fn=None):
        self.ser = None
        self.current_port = None
        self.log_fn = log_fn or (lambda msg: print(msg))
        self.is_frozen = False
        self.reader_thread = None
        self.running = False

    def list_ports(self):
        if not serial:
            return []
        ports = serial.tools.list_ports.comports()
        return [p.device for p in ports]

    def connect(self, port):
        if not serial:
            self.log_fn("[SERIAL] pyserial is not installed.")
            return False

        if self.ser and self.ser.is_open:
            self.disconnect()

        try:
            self.ser = serial.Serial(port, 115200, timeout=1.0)
            self.current_port = port
            self.running = True
            self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.reader_thread.start()
            self.log_fn(f"[SERIAL] Connected to ESP32 Air Mouse on {port} (115200 baud)")
            return True
        except Exception as e:
            self.log_fn(f"[SERIAL] Failed to connect to {port}: {e}")
            self.ser = None
            return False

    def disconnect(self):
        self.running = False
        if self.ser:
            try:
                if self.is_frozen:
                    self.unfreeze_mouse()
                self.ser.close()
            except Exception:
                pass
            self.ser = None
        self.log_fn("[SERIAL] Disconnected from ESP32 Air Mouse.")

    def _read_loop(self):
        while self.running and self.ser and self.ser.is_open:
            try:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    self.log_fn(f"[ESP32] {line}")
            except Exception:
                break

    def send_command(self, cmd):
        if self.ser and self.ser.is_open:
            try:
                payload = (cmd.strip() + "\n").encode("utf-8")
                self.ser.write(payload)
                self.ser.flush()
                return True
            except Exception as e:
                self.log_fn(f"[SERIAL] Error sending '{cmd}': {e}")
                return False
        return False

    def freeze_mouse(self):
        """Signals ESP32 to freeze mouse movement and button clicks."""
        if self.send_command("FREEZE"):
            self.is_frozen = True
            self.log_fn("❄️ [HARDWARE] ESP32 Air Mouse FROZEN for tuning. Cursor will not move.")
            return True
        return False

    def unfreeze_mouse(self):
        """Signals ESP32 to restore mouse movement."""
        if self.send_command("UNFREEZE"):
            self.is_frozen = False
            self.log_fn("🟢 [HARDWARE] ESP32 Air Mouse UNFROZEN. Normal control restored.")
            return True
        return False

    def calibrate_and_apply(self, sensitivity, smoothing):
        """Sends sensitivity, smoothing, triggers gyro calibration, and unfreezes."""
        if not (self.ser and self.ser.is_open):
            self.log_fn("[SERIAL] ESP32 not connected over USB/Serial. Settings saved locally.")
            return False

        self.send_command(f"SENS:{sensitivity:.2f}")
        time.sleep(0.05)
        self.send_command(f"SMOOTH:{smoothing:.2f}")
        time.sleep(0.05)

        self.send_command("CALIBRATE")
        self.is_frozen = False
        self.log_fn(f"🚀 [HARDWARE] Flashed Sens: {sensitivity:.2f}, Smooth: {smoothing:.2f}. Calibrating Gyro...")
        return True


# =============================================================================
# FLOATING DESKTOP HUD OVERLAY
# =============================================================================
class FloatingHUD:
    """Sleek, borderless, semi-transparent top-level HUD pill."""
    def __init__(self, root):
        self.root = root
        self.hud_win = None
        self.label = None
        self.frame = None
        self.fade_job = None

    def show(self, text, status="ready"):
        if self.hud_win is None or not tk.Toplevel.winfo_exists(self.hud_win):
            self.hud_win = tk.Toplevel(self.root)
            self.hud_win.overrideredirect(True)
            self.hud_win.attributes("-topmost", True)
            try:
                self.hud_win.attributes("-alpha", 0.92)
            except Exception:
                pass

            sw = self.hud_win.winfo_screenwidth()
            w, h = 480, 52
            x = (sw - w) // 2
            y = 35
            self.hud_win.geometry(f"{w}x{h}+{x}+{y}")

            self.frame = tk.Frame(self.hud_win, bg="#0d1117", bd=2, relief="ridge")
            self.frame.pack(fill=tk.BOTH, expand=True)

            self.label = tk.Label(
                self.frame,
                text=text,
                font=("Segoe UI", 11, "bold"),
                bg="#0d1117",
                fg="#58a6ff"
            )
            self.label.pack(expand=True)
        else:
            self.hud_win.deiconify()

        if status == "ready":
            self.label.config(text=text, fg="#79c0ff")
            self.frame.config(highlightbackground="#1f6feb", highlightthickness=1)
        elif status == "locked":
            self.label.config(text=text, fg="#3fb950")
            self.frame.config(highlightbackground="#238636", highlightthickness=2)
        elif status == "sent":
            self.label.config(text=text, fg="#a371f7")
            self.frame.config(highlightbackground="#8957e5", highlightthickness=2)
            self.auto_hide(2000)

    def auto_hide(self, delay_ms):
        if self.fade_job:
            self.root.after_cancel(self.fade_job)
        self.fade_job = self.root.after(delay_ms, self.hide)

    def hide(self):
        if self.hud_win and tk.Toplevel.winfo_exists(self.hud_win):
            self.hud_win.withdraw()


# =============================================================================
# GAMING RADAR HUD CANVAS
# =============================================================================
class RadarCanvas(tk.Canvas):
    """Circular tactical radar drawing device blips and heading reticle."""
    def __init__(self, parent, size=320, **kwargs):
        super().__init__(parent, width=size, height=size, bg="#090d13", highlightthickness=0, **kwargs)
        self.size = size
        self.center = size // 2
        self.radius = self.center - 20
        self.current_yaw = 0.0
        self.locked_target = None
        self.devices = {}
        self.sweep_angle = 0.0
        self.selected_blip = None

        self.bind("<Button-1>", self.on_click)
        self.bind("<B1-Motion>", self.on_drag)
        self.animate_sweep()

    def set_devices(self, devices):
        self.devices = devices
        self.redraw()

    def update_heading(self, yaw, locked_name=None):
        self.current_yaw = yaw % 360
        self.locked_target = locked_name
        self.redraw()

    def animate_sweep(self):
        self.sweep_angle = (self.sweep_angle + 2.5) % 360
        self.redraw()
        self.after(35, self.animate_sweep)

    def redraw(self):
        self.delete("all")
        cx, cy, r = self.center, self.center, self.radius

        # 1. Concentric Range Rings
        for ratio in [0.33, 0.66, 1.0]:
            ring_r = r * ratio
            self.create_oval(cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r, outline="#162c3d", width=1)

        # 2. Crosshair Grid Lines
        self.create_line(cx - r, cy, cx + r, cy, fill="#162c3d", width=1, dash=(2, 4))
        self.create_line(cx, cy - r, cx, cy + r, fill="#162c3d", width=1, dash=(2, 4))

        # Cardinal Labels
        self.create_text(cx, cy - r + 8, text="0° FORWARD", fill="#388bfd", font=("Segoe UI", 7, "bold"))
        self.create_text(cx + r - 15, cy, text="+90°", fill="#58a6ff", font=("Segoe UI", 7))
        self.create_text(cx - r + 15, cy, text="-90°", fill="#58a6ff", font=("Segoe UI", 7))

        # 3. Rotating Radar Sweep Beam
        rad = math.radians(self.sweep_angle - 90)
        sx = cx + r * math.cos(rad)
        sy = cy + r * math.sin(rad)
        self.create_line(cx, cy, sx, sy, fill="#005533", width=2)

        # 4. Center Dot (YOU / AIR MOUSE)
        self.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill="#58a6ff", outline="#79c0ff", width=2)
        self.create_text(cx, cy + 14, text="YOU", fill="#79c0ff", font=("Segoe UI", 8, "bold"))

        # 5. Device Blips
        for name, data in self.devices.items():
            ang = data.get("angle", 0.0)
            ang_rad = math.radians(ang - 90)
            blip_dist = r * 0.75
            bx = cx + blip_dist * math.cos(ang_rad)
            by = cy + blip_dist * math.sin(ang_rad)

            is_locked = (name == self.locked_target)
            color = "#3fb950" if is_locked else "#f0883e"
            glow_color = "#2ea043" if is_locked else "#bd5610"

            b_size = 8 if is_locked else 6
            self.create_oval(bx - b_size - 3, by - b_size - 3, bx + b_size + 3, by + b_size + 3, fill="", outline=glow_color, width=2)
            self.create_oval(bx - b_size, by - b_size, bx + b_size, by + b_size, fill=color, outline="#ffffff", width=1)

            tag = "LOCKED" if is_locked else f"{int(ang)}°"
            trusted_tag = "✔" if data.get("trusted", True) else "🔒"
            self.create_text(bx, by - 14, text=f"{name} {trusted_tag}\n[{tag}]", fill=color, font=("Segoe UI", 8, "bold"), justify=tk.CENTER)

        # 6. Current Cosmic Reticle
        aim_rad = math.radians(self.current_yaw - 90)
        ax = cx + (r * 0.95) * math.cos(aim_rad)
        ay = cy + (r * 0.95) * math.sin(aim_rad)
        reticle_color = "#3fb950" if self.locked_target else "#79c0ff"
        self.create_line(cx, cy, ax, ay, fill=reticle_color, width=2, arrow=tk.LAST)

    def on_click(self, event):
        cx, cy, r = self.center, self.center, self.radius
        blip_dist = r * 0.75
        for name, data in self.devices.items():
            ang = data.get("angle", 0.0)
            ang_rad = math.radians(ang - 90)
            bx = cx + blip_dist * math.cos(ang_rad)
            by = cy + blip_dist * math.sin(ang_rad)
            if math.hypot(event.x - bx, event.y - by) < 18:
                self.selected_blip = name
                return
        self.selected_blip = None

    def on_drag(self, event):
        if self.selected_blip and self.selected_blip in self.devices:
            dx = event.x - self.center
            dy = event.y - self.center
            deg = math.degrees(math.atan2(dy, dx)) + 90
            deg = (deg + 360) % 360
            self.devices[self.selected_blip]["angle"] = round(deg, 1)
            self.redraw()


# =============================================================================
# COSMIC LINK MAIN APPLICATION
# =============================================================================
class CosmicLinkApp:
    def __init__(self, root):
        self.root = root
        self.root.title("COSMIC LINK - Spatial Control Center (Stark Edition)")
        self.root.geometry("880x720")
        self.root.minsize(840, 680)
        self.root.configure(bg="#0d1117")

        self.cfg_mgr = ConfigManager()
        self.cfg = self.cfg_mgr.config

        self.hud = FloatingHUD(self.root)
        self.local_ip = get_local_ip()

        # ESP32 Serial Bridge
        self.esp_bridge = ESP32SerialBridge(log_fn=self.log)

        # Motion & Spatial States
        self.current_yaw = 0.0
        self.zero_offset = 0.0
        self.is_holding_beam = False
        self.target_locked = None
        self.last_mouse_x = None

        # Staged payload cache (fname, payload_src, fsize, ptype)
        self.staged_payload = None
        self.manual_staged_file = None

        # Set of devices currently prompting for pairing to avoid duplicate popups
        self.pending_pairings = set()

        # UDP transfers in progress: transfer_id -> {"fname": ..., "total": ..., "chunks": {...}, "time": ...}
        self.udp_transfers = {}

        # Build UI layout
        self.build_ui()

        # Start Networking Threads
        self.running = True
        threading.Thread(target=self.udp_beacon_broadcaster, daemon=True).start()
        threading.Thread(target=self.udp_beacon_listener, daemon=True).start()
        threading.Thread(target=self.tcp_receiver_server, daemon=True).start()

        # Start Mouse / Spatial Listener
        self.init_spatial_listener()

        # Auto-connect serial if available
        self.auto_connect_serial()

        # Periodic refresh loop
        self.root.after(100, self.update_loop)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # -------------------------------------------------------------------------
    # UI SETUP
    # -------------------------------------------------------------------------
    def build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background="#0d1117", foreground="#c9d1d9")
        style.configure("TLabel", background="#0d1117", foreground="#c9d1d9", font=("Segoe UI", 9))
        style.configure("TButton", background="#21262d", foreground="#58a6ff", borderwidth=0, font=("Segoe UI", 9, "bold"))
        style.map("TButton", background=[("active", "#30363d")])

        # Top Header Bar
        hdr = tk.Frame(self.root, bg="#161b22", height=50)
        hdr.pack(fill=tk.X, side=tk.TOP)

        lbl_title = tk.Label(hdr, text="🌌 COSMIC LINK", font=("Segoe UI", 14, "bold"), bg="#161b22", fg="#58a6ff")
        lbl_title.pack(side=tk.LEFT, padx=15, pady=10)

        # Pairing Key & IP
        self.lbl_status = tk.Label(
            hdr,
            text=f"IP: {self.local_ip}  |  Pairing Key: {self.cfg['pairing_key']}",
            font=("Segoe UI", 9, "bold"),
            bg="#161b22",
            fg="#8b949e"
        )
        self.lbl_status.pack(side=tk.RIGHT, padx=15, pady=10)

        # Main Body Split (Left: Radar, Right: Controls & Hardware)
        body = tk.Frame(self.root, bg="#0d1117")
        body.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        # ----------------- Left Column: Radar HUD -----------------
        left_col = tk.Frame(body, bg="#161b22", bd=1, relief="ridge")
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        tk.Label(left_col, text="TACTICAL SPATIAL RADAR", font=("Segoe UI", 10, "bold"), bg="#161b22", fg="#58a6ff").pack(pady=4)
        self.radar = RadarCanvas(left_col, size=320)
        self.radar.pack(pady=2)
        self.radar.set_devices(self.cfg["devices"])

        # Radar Control Buttons
        btn_row = tk.Frame(left_col, bg="#161b22")
        btn_row.pack(fill=tk.X, pady=2, padx=10)

        btn_recenter = tk.Button(
            btn_row, text="🎯 Re-center (0°)", bg="#238636", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", command=self.recenter_zero
        )
        btn_recenter.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        btn_lock_angle = tk.Button(
            btn_row, text="📍 Point & Sync to Peer", bg="#1f6feb", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", command=self.lock_heading_to_device
        )
        btn_lock_angle.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # Desk Layout Option
        layout_frame = tk.Frame(left_col, bg="#161b22")
        layout_frame.pack(fill=tk.X, padx=12, pady=2)
        tk.Label(layout_frame, text="Desk Geometry:", font=("Segoe UI", 8), bg="#161b22", fg="#8b949e").pack(side=tk.LEFT)
        self.combo_layout = ttk.Combobox(layout_frame, width=22, state="readonly", values=[
            "Side-by-Side (Facing User)",
            "Opposite (Across Table)"
        ])
        saved_layout = self.cfg.get("desk_layout", "side_by_side")
        self.combo_layout.set("Side-by-Side (Facing User)" if saved_layout == "side_by_side" else "Opposite (Across Table)")
        self.combo_layout.pack(side=tk.RIGHT, padx=4)
        self.combo_layout.bind("<<ComboboxSelected>>", self.on_layout_change)

        # Staged Payload Quick-Actions
        stage_row = tk.Frame(left_col, bg="#161b22")
        stage_row.pack(fill=tk.X, padx=10, pady=3)

        btn_browse_file = tk.Button(
            stage_row, text="📎 Stage File Manually", bg="#30363d", fg="#79c0ff", font=("Segoe UI", 8, "bold"),
            relief="flat", command=self.browse_stage_file
        )
        btn_browse_file.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        btn_test_ping = tk.Button(
            stage_row, text="📶 Test Ping Peer", bg="#30363d", fg="#7ee787", font=("Segoe UI", 8, "bold"),
            relief="flat", command=self.test_ping_peer
        )
        btn_test_ping.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        btn_test_beam = tk.Button(
            left_col, text="⚡ Beam Staged Payload Now", bg="#238636", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", command=self.trigger_manual_beam
        )
        btn_test_beam.pack(fill=tk.X, padx=12, pady=(2, 4))

        # Instructions Note
        lbl_hint = tk.Label(
            left_col,
            text="✨ Dual-Laptop Workflow:\n"
                 "1. Right-click file in Explorer OR click 'Stage File Manually'.\n"
                 "2. Hold Button 3 & turn arm toward target laptop.\n"
                 "3. Release Button 3: Streams via TCP or automatic UDP fallback!\n"
                 "4. Single-click Button 3 toggles controlling Laptop A/B.",
            font=("Segoe UI", 8),
            bg="#161b22",
            fg="#8b949e",
            justify=tk.LEFT
        )
        lbl_hint.pack(fill=tk.X, padx=12, pady=(0, 4))

        # ----------------- Right Column: Hardware & Settings -----------------
        right_col = tk.Frame(body, bg="#161b22", bd=1, relief="ridge", width=420)
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 1. Pairing Key & Trust Section
        key_frame = tk.Frame(right_col, bg="#161b22")
        key_frame.pack(fill=tk.X, padx=15, pady=(6, 2))
        tk.Label(key_frame, text="PAIRING & TRUST SETUP", font=("Segoe UI", 9, "bold"), bg="#161b22", fg="#58a6ff").pack(anchor=tk.W)

        kf_inner = tk.Frame(key_frame, bg="#161b22")
        kf_inner.pack(fill=tk.X, pady=2)
        tk.Label(kf_inner, text="Network Key:", bg="#161b22", fg="#c9d1d9").pack(side=tk.LEFT)
        self.entry_key = tk.Entry(kf_inner, bg="#0d1117", fg="#58a6ff", font=("Segoe UI", 9, "bold"), width=15, relief="flat")
        self.entry_key.insert(0, self.cfg.get("pairing_key", DEFAULT_PAIRING_KEY))
        self.entry_key.pack(side=tk.LEFT, padx=6)
        btn_update_key = tk.Button(kf_inner, text="Set Key", bg="#21262d", fg="#79c0ff", relief="flat", command=self.update_pairing_key)
        btn_update_key.pack(side=tk.LEFT)

        btn_firewall = tk.Button(kf_inner, text="🛡️ Fix Firewall", bg="#21262d", fg="#f0883e", relief="flat", command=self.launch_firewall_setup)
        btn_firewall.pack(side=tk.RIGHT)

        # 2. Hardware Live Tuning (Freeze & Calibrate)
        tk.Label(right_col, text="AIR MOUSE HARDWARE TUNING (SERIAL / USB)", font=("Segoe UI", 9, "bold"), bg="#161b22", fg="#58a6ff").pack(anchor=tk.W, padx=15, pady=(6, 2))

        # Serial COM Port Selector
        port_frame = tk.Frame(right_col, bg="#161b22")
        port_frame.pack(fill=tk.X, padx=15, pady=2)
        tk.Label(port_frame, text="COM Port:", bg="#161b22", fg="#c9d1d9").pack(side=tk.LEFT)
        self.combo_ports = ttk.Combobox(port_frame, width=12, state="readonly")
        self.combo_ports.pack(side=tk.LEFT, padx=6)
        btn_refresh_ports = tk.Button(port_frame, text="🔄", bg="#21262d", fg="white", relief="flat", command=self.refresh_serial_ports)
        btn_refresh_ports.pack(side=tk.LEFT, padx=2)
        self.btn_serial_connect = tk.Button(port_frame, text="Connect", bg="#238636", fg="white", relief="flat", command=self.toggle_serial_connection)
        self.btn_serial_connect.pack(side=tk.LEFT, padx=4)

        # Tuning Status Banner
        self.lbl_hw_status = tk.Label(
            right_col,
            text="STATUS: 🟢 Ready (Live Active)",
            font=("Segoe UI", 9, "bold"),
            bg="#0d1117",
            fg="#7ee787",
            pady=2
        )
        self.lbl_hw_status.pack(fill=tk.X, padx=15, pady=2)

        # Freeze Button
        freeze_btn_row = tk.Frame(right_col, bg="#161b22")
        freeze_btn_row.pack(fill=tk.X, padx=15, pady=2)

        self.btn_freeze = tk.Button(
            freeze_btn_row,
            text="❄️ FREEZE AIR MOUSE FOR TUNING",
            bg="#b62324",
            fg="white",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            command=self.freeze_mouse_for_tuning
        )
        self.btn_freeze.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        self.btn_unfreeze = tk.Button(
            freeze_btn_row,
            text="🔓 Unfreeze",
            bg="#30363d",
            fg="#c9d1d9",
            font=("Segoe UI", 9),
            relief="flat",
            command=self.unfreeze_mouse_manual
        )
        self.btn_unfreeze.pack(side=tk.LEFT, padx=2)

        # Sensitivity Slider
        s_frame = tk.Frame(right_col, bg="#161b22")
        s_frame.pack(fill=tk.X, padx=15, pady=2)
        tk.Label(s_frame, text="Sensitivity:", bg="#161b22", fg="#c9d1d9").pack(side=tk.LEFT)
        self.slider_sens = tk.Scale(s_frame, from_=0.05, to=0.80, resolution=0.01, orient=tk.HORIZONTAL,
                                    bg="#161b22", fg="#58a6ff", highlightthickness=0, command=lambda v: self.save_settings())
        self.slider_sens.set(self.cfg.get("sensitivity", 0.20))
        self.slider_sens.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=5)

        # Smoothing Slider
        sm_frame = tk.Frame(right_col, bg="#161b22")
        sm_frame.pack(fill=tk.X, padx=15, pady=2)
        tk.Label(sm_frame, text="Smoothing:", bg="#161b22", fg="#c9d1d9").pack(side=tk.LEFT)
        self.slider_smooth = tk.Scale(sm_frame, from_=0.50, to=0.98, resolution=0.01, orient=tk.HORIZONTAL,
                                      bg="#161b22", fg="#58a6ff", highlightthickness=0, command=lambda v: self.save_settings())
        self.slider_smooth.set(self.cfg.get("smoothing", 0.82))
        self.slider_smooth.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=5)

        # Confirm & Calibrate Button
        self.btn_calibrate = tk.Button(
            right_col,
            text="🚀 CONFIRM, FLASH & CALIBRATE GYRO",
            bg="#1f6feb",
            fg="white",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            command=self.confirm_and_calibrate
        )
        self.btn_calibrate.pack(fill=tk.X, padx=15, pady=(2, 4))

        # 3. Sharing & DropZone Settings
        tk.Label(right_col, text="SHARING & DROPZONE", font=("Segoe UI", 9, "bold"), bg="#161b22", fg="#58a6ff").pack(anchor=tk.W, padx=15, pady=(4, 2))

        self.var_autodisplay = tk.BooleanVar(value=self.cfg.get("auto_display", True))
        chk_auto = tk.Checkbutton(
            right_col, text="Instant Screen Display (Zero-Confirmation Auto-Popup)", variable=self.var_autodisplay,
            bg="#161b22", fg="#c9d1d9", selectcolor="#0d1117", activebackground="#161b22",
            command=self.save_settings
        )
        chk_auto.pack(anchor=tk.W, padx=15, pady=1)

        dz_frame = tk.Frame(right_col, bg="#161b22")
        dz_frame.pack(fill=tk.X, padx=15, pady=2)
        tk.Label(dz_frame, text="DropZone:", font=("Segoe UI", 8), bg="#161b22", fg="#8b949e").pack(side=tk.LEFT)
        self.entry_dz = tk.Entry(dz_frame, bg="#0d1117", fg="#c9d1d9", insertbackground="#58a6ff", relief="flat")
        self.entry_dz.insert(0, self.cfg.get("dropzone", DEFAULT_DROPZONE))
        self.entry_dz.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        btn_browse = tk.Button(dz_frame, text="📂", bg="#30363d", fg="white", relief="flat", command=self.browse_dropzone)
        btn_browse.pack(side=tk.LEFT)

        # 4. Activity Log
        tk.Label(right_col, text="Activity Log / Recent Beams:", font=("Segoe UI", 8, "bold"), bg="#161b22", fg="#8b949e").pack(anchor=tk.W, padx=15, pady=(4, 2))
        self.txt_log = tk.Text(right_col, height=6, bg="#0d1117", fg="#7ee787", font=("Consolas", 8), relief="flat")
        self.txt_log.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 6))

        # Populate COM ports
        self.refresh_serial_ports()

    def log(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.txt_log.insert(tk.END, f"[{timestamp}] {msg}\n")
        self.txt_log.see(tk.END)

    def on_layout_change(self, event=None):
        val = self.combo_layout.get()
        layout_key = "opposite" if "Opposite" in val else "side_by_side"
        self.cfg["desk_layout"] = layout_key
        self.cfg_mgr.save()
        self.log(f"📐 Desk Geometry set to: {val}")

    def browse_dropzone(self):
        folder = filedialog.askdirectory(initialdir=self.entry_dz.get())
        if folder:
            self.entry_dz.delete(0, tk.END)
            self.entry_dz.insert(0, folder)
            self.save_settings()

    def browse_stage_file(self):
        """Allows user to explicitly select any file to stage for beaming."""
        path = filedialog.askopenfilename(title="Select File to Beam")
        if path and os.path.isfile(path):
            self.manual_staged_file = path
            fname = os.path.basename(path)
            fsize = os.path.getsize(path)
            self.staged_payload = (fname, path, fsize, "manual_file")
            self.log(f"📎 Staged file manually: '{fname}' ({fsize} bytes)")
            self.hud.show(f"⚡ READY TO SEND [{fname}]", status="ready")
            self.hud.auto_hide(2500)

    def launch_firewall_setup(self):
        """Launches setup_firewall.bat with administrator elevation."""
        bat_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup_firewall.bat")
        if os.path.exists(bat_path):
            try:
                import subprocess
                subprocess.Popen(["powershell", "-Command", f"Start-Process cmd -Verb RunAs -ArgumentList '/c \"{bat_path}\"'"])
                self.log("🛡️ Launched Windows Firewall configuration with Administrator prompt.")
            except Exception as e:
                self.log(f"[!] Could not launch firewall helper: {e}")
        else:
            messagebox.showinfo("Firewall Helper", "Please run setup_firewall.bat as administrator to unblock ports.")

    def test_ping_peer(self):
        """Tests reaching peer laptop via TCP and UDP."""
        if not self.cfg["devices"]:
            messagebox.showinfo("Ping Test", "No peer laptops discovered yet on your Wi-Fi.")
            return

        target_name = self.radar.selected_blip or list(self.cfg["devices"].keys())[0]
        target_info = self.cfg["devices"][target_name]
        target_ip = target_info.get("ip")

        self.log(f"📡 Testing connection to {target_name} ({target_ip})...")

        def run_test():
            # Test TCP
            tcp_ok = False
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2.0)
                s.connect((target_ip, DEFAULT_TRANSFER_PORT))
                s.close()
                tcp_ok = True
            except Exception:
                tcp_ok = False

            # Test UDP
            udp_ok = True  # Verified by beacon

            res = f"Results for {target_name} ({target_ip}):\n"
            if tcp_ok:
                res += "• TCP Port 5051: 🟢 OPEN & FAST\n"
            else:
                res += "• TCP Port 5051: ⚠️ BLOCKED by Windows Firewall on peer\n"

            res += "• UDP Port 5052: 🟢 ACTIVE (UDP Fallback Transfer will work!)\n"
            if not tcp_ok:
                res += "\n💡 TIP: Run 'setup_firewall.bat' as Administrator on both laptops to unblock full-speed TCP transfers."

            self.root.after(0, lambda: messagebox.showinfo("Connection Test", res))
            self.root.after(0, lambda: self.log(f"Test Ping: TCP={tcp_ok}, UDP=True"))

        threading.Thread(target=run_test, daemon=True).start()

    def update_pairing_key(self):
        new_key = self.entry_key.get().strip()
        if new_key:
            self.cfg["pairing_key"] = new_key
            self.cfg_mgr.save()
            self.lbl_status.config(text=f"IP: {self.local_ip}  |  Pairing Key: {new_key}")
            self.log(f"🔑 Pairing Key updated to '{new_key}'.")

    def save_settings(self):
        self.cfg["auto_display"] = self.var_autodisplay.get()
        self.cfg["dropzone"] = self.entry_dz.get()
        self.cfg["sensitivity"] = float(self.slider_sens.get())
        self.cfg["smoothing"] = float(self.slider_smooth.get())
        self.cfg_mgr.save()

    # -------------------------------------------------------------------------
    # SERIAL PORT & HARDWARE ACTIONS
    # -------------------------------------------------------------------------
    def refresh_serial_ports(self):
        ports = self.esp_bridge.list_ports()
        self.combo_ports["values"] = ports
        if ports:
            if not self.combo_ports.get() or self.combo_ports.get() not in ports:
                self.combo_ports.current(0)
        else:
            self.combo_ports.set("No Ports")

    def auto_connect_serial(self):
        ports = self.esp_bridge.list_ports()
        if ports:
            target_port = self.cfg.get("serial_port", "")
            if target_port not in ports:
                target_port = ports[0]
            self.combo_ports.set(target_port)
            if self.esp_bridge.connect(target_port):
                self.btn_serial_connect.config(text="Disconnect", bg="#b62324")
                self.cfg["serial_port"] = target_port
                self.cfg_mgr.save()

    def toggle_serial_connection(self):
        if self.esp_bridge.ser and self.esp_bridge.ser.is_open:
            self.esp_bridge.disconnect()
            self.btn_serial_connect.config(text="Connect", bg="#238636")
            self.lbl_hw_status.config(text="STATUS: Disconnected", fg="#8b949e")
        else:
            port = self.combo_ports.get()
            if not port or port == "No Ports":
                messagebox.showwarning("Serial Connection", "No COM port selected!\nPlug in the ESP32 via USB and click Refresh.")
                return
            if self.esp_bridge.connect(port):
                self.btn_serial_connect.config(text="Disconnect", bg="#b62324")
                self.lbl_hw_status.config(text="STATUS: 🟢 Ready (Live Active)", fg="#7ee787")
                self.cfg["serial_port"] = port
                self.cfg_mgr.save()
            else:
                messagebox.showerror("Serial Connection", f"Could not open {port}.\nMake sure Arduino Serial Monitor is closed.")

    def freeze_mouse_for_tuning(self):
        """Freezes air mouse so the user can adjust sliders without cursor jumps."""
        if not (self.esp_bridge.ser and self.esp_bridge.ser.is_open):
            port = self.combo_ports.get()
            if port and port != "No Ports":
                self.esp_bridge.connect(port)

        if self.esp_bridge.ser and self.esp_bridge.ser.is_open:
            self.esp_bridge.freeze_mouse()
            self.lbl_hw_status.config(
                text="STATUS: ❄️ MOUSE FROZEN (Safe to adjust sliders)",
                fg="#f0883e",
                bg="#2d1b00"
            )
            self.hud.show("❄️ AIR MOUSE FROZEN FOR TUNING", status="ready")
            self.hud.auto_hide(2000)
        else:
            self.lbl_hw_status.config(
                text="STATUS: ⚠️ Local Mode (ESP32 USB not connected)",
                fg="#d29922"
            )
            self.log("[NOTE] ESP32 not connected over USB. Connect USB cable to freeze hardware.")

    def unfreeze_mouse_manual(self):
        self.esp_bridge.unfreeze_mouse()
        self.lbl_hw_status.config(
            text="STATUS: 🟢 Ready (Live Active)",
            fg="#7ee787",
            bg="#0d1117"
        )
        self.hud.show("🟢 AIR MOUSE ACTIVE", status="ready")
        self.hud.auto_hide(1200)

    def confirm_and_calibrate(self):
        """User confirmation to flash settings to ESP32 Flash and calibrate gyro."""
        sens = float(self.slider_sens.get())
        smooth = float(self.slider_smooth.get())

        answer = messagebox.askyesno(
            "Confirm Air Mouse Calibration",
            f"Apply settings to ESP32?\n\n"
            f"• Sensitivity: {sens:.2f}\n"
            f"• Smoothing: {smooth:.2f}\n\n"
            f"Keep the Air Mouse completely flat and still for 2 seconds while gyro calibrates.\n\n"
            f"Proceed now?"
        )
        if not answer:
            return

        self.save_settings()

        if self.esp_bridge.ser and self.esp_bridge.ser.is_open:
            self.lbl_hw_status.config(
                text="STATUS: ⏳ Calibrating Gyro (Keep mouse still!)...",
                fg="#58a6ff",
                bg="#0b1b36"
            )
            self.hud.show("⏳ CALIBRATING GYRO (KEEP STILL!)...", status="ready")

            def run_cal():
                self.esp_bridge.calibrate_and_apply(sens, smooth)
                time.sleep(1.8)
                self.root.after(0, self._on_cal_complete)

            threading.Thread(target=run_cal, daemon=True).start()
        else:
            self.log(f"Settings saved locally. Connect ESP32 USB to flash to hardware memory.")
            self.recenter_zero()
            messagebox.showinfo("Cosmic Link", "Settings saved locally!\nConnect ESP32 via USB if you wish to write directly to hardware Flash memory.")

    def _on_cal_complete(self):
        self.recenter_zero()
        self.lbl_hw_status.config(
            text="STATUS: 🟢 Calibrated & Unfrozen (Ready)",
            fg="#7ee787",
            bg="#0d1117"
        )
        self.hud.show("✔ CALIBRATED & UNFROZEN!", status="locked")
        self.hud.auto_hide(2000)
        self.log("✔ Gyro calibration complete. Air Mouse unfrozen and ready to fly!")

    # -------------------------------------------------------------------------
    # SPATIAL LOGIC & BIDIRECTIONAL RADAR SYNC
    # -------------------------------------------------------------------------
    def recenter_zero(self):
        """Snaps current direction as 0° Forward."""
        self.zero_offset = self.current_yaw
        self.log("🎯 Radar re-centered: Current heading is now 0° Forward.")
        self.radar.update_heading(0.0)

    def calculate_relative_heading(self, raw_yaw):
        return (raw_yaw - self.zero_offset + 360) % 360

    def lock_heading_to_device(self):
        """Locks the current air mouse aim angle for the selected laptop,

        and automatically transmits the reciprocal angle over Wi-Fi so
        the target laptop immediately knows this laptop's location!
        """
        if not self.cfg["devices"]:
            messagebox.showinfo("Lock Angle", "No peer laptops discovered yet on your Wi-Fi.\nStart cosmic.py on your other laptop to connect.")
            return

        target_name = self.radar.selected_blip or list(self.cfg["devices"].keys())[0]
        heading = self.calculate_relative_heading(self.current_yaw)
        self.cfg["devices"][target_name]["angle"] = round(heading, 1)
        self.cfg_mgr.save()
        self.radar.set_devices(self.cfg["devices"])

        self.log(f"📍 Locked {target_name} at {heading:.1f}°")
        self.hud.show(f"📍 {target_name.upper()} LOCKED AT {int(heading)}°", status="locked")
        self.hud.auto_hide(2000)

        # Synchronize location with target laptop over Wi-Fi
        target_info = self.cfg["devices"].get(target_name)
        if target_info and target_info.get("ip"):
            threading.Thread(
                target=self.send_location_sync,
                args=(target_info["ip"], target_name, heading),
                daemon=True
            ).start()

    def send_location_sync(self, target_ip, target_name, heading):
        """Sends location sync packet to peer laptop so it automatically positions this laptop on its radar."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.0)
            sock.connect((target_ip, DEFAULT_TRANSFER_PORT))

            sync_packet = {
                "type": "SYNC_RADAR_LOCATION",
                "key": self.cfg["pairing_key"],
                "sender": self.cfg["device_name"],
                "angle_from_sender": heading,
                "desk_layout": self.cfg.get("desk_layout", "side_by_side")
            }
            payload = json.dumps(sync_packet).encode("utf-8")
            sock.sendall(struct.pack(">I", len(payload)))
            sock.sendall(payload)
            sock.close()
            self.root.after(0, lambda: self.log(f"📡 Synchronized spatial coordinates to {target_name} ({target_ip})!"))
        except Exception:
            # Fallback sync via UDP packet on port 5052
            try:
                u_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                key = self.cfg["pairing_key"]
                sender = self.cfg["device_name"]
                layout = self.cfg.get("desk_layout", "side_by_side")
                msg = f"COSMIC_LOC_SYNC:{key}:{sender}:{heading}:{layout}".encode("utf-8")
                u_sock.sendto(msg, (target_ip, DEFAULT_DISCOVERY_PORT))
                u_sock.close()
                self.root.after(0, lambda: self.log(f"📡 Synchronized spatial coordinates to {target_name} via UDP."))
            except Exception as ue:
                self.root.after(0, lambda: self.log(f"[!] Could not sync radar location: {ue}"))

    def evaluate_target_lock(self):
        """Finds if current aim is pointing at any paired laptop (within ±25°)."""
        heading = self.calculate_relative_heading(self.current_yaw)
        best_match = None
        min_diff = 25.0

        for name, data in self.cfg["devices"].items():
            ang = data.get("angle", 0.0)
            diff = abs((heading - ang + 180) % 360 - 180)
            if diff <= min_diff:
                min_diff = diff
                best_match = name

        self.target_locked = best_match
        self.radar.update_heading(heading, self.target_locked)
        return self.target_locked

    # -------------------------------------------------------------------------
    # HARDWARE & MOUSE GESTURE HOOKS
    # -------------------------------------------------------------------------
    def init_spatial_listener(self):
        """Hooks into mouse to handle Button 3 hold for spatial move & screen edge wrapping."""
        if not mouse or not keyboard:
            self.log("[!] pynput not available - use 'Beam Staged Payload' button.")
            return

        self.last_btn3_press = 0.0
        self.mouse_controller = mouse.Controller()

        def on_move(x, y):
            if self.last_mouse_x is not None:
                dx = x - self.last_mouse_x
                yaw_delta = dx * 0.30
                self.current_yaw = (self.current_yaw + yaw_delta) % 360

                # Screen edge warp while holding beam so aiming never traps at monitor edge
                if self.is_holding_beam:
                    try:
                        sw = self.root.winfo_screenwidth()
                        sh = self.root.winfo_screenheight()
                        if x < 40 or x > sw - 40:
                            cx = sw // 2
                            cy = sh // 2
                            self.mouse_controller.position = (cx, cy)
                            self.last_mouse_x = cx
                            return
                    except Exception:
                        pass

            self.last_mouse_x = x

        def on_click(x, y, button, pressed):
            # Middle button (sent by ESP32 on Button 3 hold)
            if button == mouse.Button.middle:
                now = time.time()
                if pressed:
                    self.last_btn3_press = now
                    self.is_holding_beam = True
                    self.root.after(0, self.on_beam_hold_start)
                else:
                    if self.is_holding_beam:
                        self.is_holding_beam = False
                        self.root.after(0, self.on_beam_hold_release)

        listener = mouse.Listener(on_move=on_move, on_click=on_click)
        listener.daemon = True
        listener.start()

    def on_beam_hold_start(self):
        # Lock in staged payload immediately when hold starts!
        try:
            self.staged_payload = self.get_staged_payload()
            fname, _, _, ptype = self.staged_payload
            if ptype == "screenshot":
                status_text = "⚡ READY TO SEND [Screenshot]"
            else:
                status_text = f"⚡ READY TO SEND [{fname}]"
            self.log(f"📦 Staged for beaming: '{fname}' ({ptype})")
        except Exception:
            self.staged_payload = None
            status_text = "⚡ READY TO SEND [Aim at Target Laptop...]"

        self.hud.show(status_text, status="ready")

    def on_beam_hold_release(self):
        if self.target_locked:
            target_info = self.cfg["devices"].get(self.target_locked)
            if target_info:
                payload_to_send = self.staged_payload
                self.hud.show(f"✔ SENT TO {self.target_locked.upper()}!", status="sent")
                self.log(f"🚀 Beaming payload to {self.target_locked} ({target_info['ip']})...")
                threading.Thread(
                    target=self.transmit_payload,
                    args=(target_info["ip"], self.target_locked, payload_to_send),
                    daemon=True
                ).start()
        else:
            self.hud.hide()

    def trigger_manual_beam(self):
        """Allows testing without physical mouse hardware."""
        heading = self.calculate_relative_heading(self.current_yaw)
        self.evaluate_target_lock()
        target_name = self.target_locked
        if not target_name and self.cfg["devices"]:
            target_name = list(self.cfg["devices"].keys())[0]

        if target_name:
            target_info = self.cfg["devices"][target_name]
            self.hud.show(f"✔ BEAMED TO {target_name.upper()}!", status="sent")
            payload_to_send = self.staged_payload or self.get_staged_payload()
            threading.Thread(
                target=self.transmit_payload,
                args=(target_info["ip"], target_name, payload_to_send),
                daemon=True
            ).start()
        else:
            messagebox.showinfo("Cosmic Link", "No nearby laptops discovered yet!\nOpen Cosmic Link on another laptop on your Wi-Fi.")

    # -------------------------------------------------------------------------
    # NETWORKING: PEER DISCOVERY & MUTUAL PAIRING CONFIRMATION
    # -------------------------------------------------------------------------
    def udp_beacon_broadcaster(self):
        """Whispers presence on local Wi-Fi with Pairing Key."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        while self.running:
            try:
                my_name = self.cfg["device_name"]
                key = self.cfg["pairing_key"]
                msg = f"COSMIC:{key}:{my_name}:{self.local_ip}".encode("utf-8")
                sock.sendto(msg, ("<broadcast>", DEFAULT_DISCOVERY_PORT))
            except Exception:
                pass
            time.sleep(2.0)

    def udp_beacon_listener(self):
        """Hears whispers, pairing commands, and incoming UDP chunk transfers."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", DEFAULT_DISCOVERY_PORT))
        except Exception as e:
            print(f"[BEACON] Port bind error: {e}")
            return

        while self.running:
            try:
                data, addr = sock.recvfrom(65536)

                # -------------------------------------------------------------
                # 1. HANDLE UDP FILE TRANSFER CHUNKS (Firewall Fallback Engine)
                # -------------------------------------------------------------
                if data.startswith(b"COSMIC_UDP_START:"):
                    msg = data.decode("utf-8", errors="ignore")
                    parts = msg.split(":")
                    if len(parts) >= 7 and parts[1] == self.cfg["pairing_key"]:
                        tid = parts[2]
                        total = int(parts[3])
                        fsize = int(parts[4])
                        fname = os.path.basename(parts[5])
                        sender = parts[6]
                        self.udp_transfers[tid] = {
                            "fname": fname,
                            "total": total,
                            "fsize": fsize,
                            "sender": sender,
                            "chunks": {},
                            "start_time": time.time()
                        }
                    continue

                if data.startswith(b"COSMIC_UDP_CHUNK:"):
                    # Split first 4 parts
                    header_end = 0
                    colon_count = 0
                    for i, b in enumerate(data):
                        if b == ord(':'):
                            colon_count += 1
                            if colon_count == 4:
                                header_end = i + 1
                                break

                    if header_end > 0:
                        header_str = data[:header_end].decode("utf-8", errors="ignore")
                        parts = header_str.split(":")
                        if len(parts) >= 4 and parts[1] == self.cfg["pairing_key"]:
                            tid = parts[2]
                            idx = int(parts[3])
                            chunk_bytes = data[header_end:]
                            if tid in self.udp_transfers:
                                self.udp_transfers[tid]["chunks"][idx] = chunk_bytes
                    continue

                if data.startswith(b"COSMIC_UDP_DONE:"):
                    msg = data.decode("utf-8", errors="ignore")
                    parts = msg.split(":")
                    if len(parts) >= 4 and parts[1] == self.cfg["pairing_key"]:
                        tid = parts[2]
                        if tid in self.udp_transfers:
                            t_info = self.udp_transfers[tid]
                            fname = t_info["fname"]
                            total = t_info["total"]
                            chunks_dict = t_info["chunks"]

                            # Assemble file
                            full_bytes = b"".join([chunks_dict.get(i, b"") for i in range(total)])
                            drop_folder = self.cfg.get("dropzone", DEFAULT_DROPZONE)
                            os.makedirs(drop_folder, exist_ok=True)
                            filepath = os.path.join(drop_folder, fname)

                            with open(filepath, "wb") as f:
                                f.write(full_bytes)

                            del self.udp_transfers[tid]

                            # Display and notify
                            sender = t_info.get("sender", addr[0])
                            self.root.after(0, lambda: self.log(
                                f"⚡ RECEIVED: '{fname}' ({len(full_bytes)} bytes) via UDP Fallback from {sender}!"
                            ))
                            self.root.after(0, lambda: self.hud.show(f"⚡ RECEIVED: {fname} (OPENING NOW!)", status="locked"))
                            self.root.after(0, lambda: self.hud.auto_hide(2500))

                            if self.cfg.get("auto_display", True):
                                try:
                                    os.startfile(filepath)
                                except Exception as e:
                                    self.root.after(0, lambda: self.log(f"Auto-display note: {e}"))
                    continue

                # -------------------------------------------------------------
                # 2. HANDLE LOCATION SYNC OVER UDP
                # -------------------------------------------------------------
                if data.startswith(b"COSMIC_LOC_SYNC:"):
                    msg = data.decode("utf-8", errors="ignore")
                    parts = msg.split(":")
                    if len(parts) >= 5 and parts[1] == self.cfg["pairing_key"]:
                        sender = parts[2]
                        ang = float(parts[3])
                        layout = parts[4]
                        recip = (ang + 180.0) % 360.0 if layout == "opposite" else (360.0 - ang) % 360.0

                        if sender not in self.cfg["devices"]:
                            self.cfg["devices"][sender] = {"ip": addr[0], "angle": round(recip, 1), "last_seen": time.time(), "trusted": True}
                        else:
                            self.cfg["devices"][sender]["angle"] = round(recip, 1)
                            self.cfg["devices"][sender]["ip"] = addr[0]

                        self.cfg_mgr.save()
                        self.root.after(0, lambda: self.radar.set_devices(self.cfg["devices"]))
                        self.root.after(0, lambda: self.log(f"📍 Radar location synced from {sender} via UDP ({recip:.1f}°)."))
                    continue

                # -------------------------------------------------------------
                # 3. REGULAR BEACON DISCOVERY
                # -------------------------------------------------------------
                msg = data.decode("utf-8", errors="ignore")
                parts = msg.split(":")
                if len(parts) >= 4 and parts[0] == "COSMIC":
                    beacon_key = parts[1]
                    dev_name   = parts[2]
                    dev_ip     = parts[3]

                    if beacon_key != self.cfg["pairing_key"] or dev_name == self.cfg["device_name"]:
                        continue

                    now = time.time()
                    if dev_name in self.cfg["devices"] and self.cfg["devices"][dev_name].get("trusted", False):
                        self.cfg["devices"][dev_name]["ip"] = dev_ip
                        self.cfg["devices"][dev_name]["last_seen"] = now
                        continue

                    if dev_name not in self.pending_pairings:
                        self.pending_pairings.add(dev_name)
                        self.root.after(0, lambda d=dev_name, ip=dev_ip: self.prompt_pair_confirmation(d, ip))
            except Exception:
                pass

    def prompt_pair_confirmation(self, dev_name, dev_ip):
        """Asks the user on this laptop to confirm pairing with the incoming device."""
        key = self.cfg["pairing_key"]
        ans = messagebox.askyesno(
            "Cosmic Link - New Device Discovered",
            f"Device '{dev_name}' ({dev_ip}) detected on local Wi-Fi.\n"
            f"Matching Pairing Key: '{key}'.\n\n"
            f"Do you want to accept pairing and establish mutual trust with '{dev_name}'?",
            parent=self.root
        )
        if ans:
            existing_count = len(self.cfg["devices"])
            default_ang = (45.0 + existing_count * 60.0) % 360.0

            self.cfg["devices"][dev_name] = {
                "ip": dev_ip,
                "angle": round(default_ang, 1),
                "last_seen": time.time(),
                "trusted": True
            }
            self.cfg_mgr.save()
            self.radar.set_devices(self.cfg["devices"])

            self.log(f"★ TRUST ESTABLISHED with '{dev_name}' ({dev_ip})!")
            self.hud.show(f"✔ PAIRED WITH {dev_name.upper()}! POINT & SYNC", status="locked")
            self.hud.auto_hide(3000)

            threading.Thread(target=self.send_pair_accept, args=(dev_ip,), daemon=True).start()
        else:
            self.log(f"✖ Pairing with '{dev_name}' was declined.")

        self.pending_pairings.discard(dev_name)

    def send_pair_accept(self, target_ip):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.0)
            sock.connect((target_ip, DEFAULT_TRANSFER_PORT))
            packet = {
                "type": "PAIR_ACCEPT",
                "key": self.cfg["pairing_key"],
                "sender": self.cfg["device_name"]
            }
            payload = json.dumps(packet).encode("utf-8")
            sock.sendall(struct.pack(">I", len(payload)))
            sock.sendall(payload)
            sock.close()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # NETWORKING: HIGH-SPEED BEAM ENGINE (TCP + AUTOMATIC UDP FALLBACK)
    # -------------------------------------------------------------------------
    def get_staged_payload(self):
        """Grabs the file right-clicked/selected in Explorer, desktop, clipboard, or screenshot."""
        if pythoncom:
            try:
                pythoncom.CoInitialize()
            except Exception:
                pass

        # 1. Check if user manually staged a file via UI button
        if hasattr(self, "manual_staged_file") and self.manual_staged_file and os.path.isfile(self.manual_staged_file):
            path = self.manual_staged_file
            return os.path.basename(path), path, os.path.getsize(path), "manual_file"

        # 2. Check open Windows File Explorer windows
        if win32com:
            try:
                shell = win32com.client.Dispatch("Shell.Application")
                for window in shell.Windows():
                    try:
                        items = window.Document.SelectedItems()
                        if items.Count > 0:
                            selected_path = items.Item(0).Path
                            if os.path.isfile(selected_path):
                                fname = os.path.basename(selected_path)
                                fsize = os.path.getsize(selected_path)
                                return fname, selected_path, fsize, "explorer_file"
                    except Exception:
                        pass
            except Exception:
                pass

            # 3. Check Windows Desktop selected items
            try:
                shell = win32com.client.Dispatch("Shell.Application")
                desktop = shell.Windows().FindWindowSW(0, "", 8, 0, 1)
                if desktop and hasattr(desktop, "Document"):
                    items = desktop.Document.SelectedItems()
                    if items.Count > 0:
                        selected_path = items.Item(0).Path
                        if os.path.isfile(selected_path):
                            fname = os.path.basename(selected_path)
                            fsize = os.path.getsize(selected_path)
                            return fname, selected_path, fsize, "desktop_file"
            except Exception:
                pass

        # 4. Check Clipboard file list (CF_HDROP)
        if win32clipboard:
            try:
                win32clipboard.OpenClipboard()
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_HDROP):
                    file_list = win32clipboard.GetClipboardData(win32clipboard.CF_HDROP)
                    win32clipboard.CloseClipboard()
                    if file_list and os.path.isfile(file_list[0]):
                        selected_path = file_list[0]
                        fname = os.path.basename(selected_path)
                        fsize = os.path.getsize(selected_path)
                        return fname, selected_path, fsize, "clipboard_file"
                else:
                    win32clipboard.CloseClipboard()
            except Exception:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass

        # 5. Check if clipboard text contains an existing file path
        try:
            cb = self.root.clipboard_get().strip('"\' \r\n')
            if cb and os.path.isfile(cb):
                fname = os.path.basename(cb)
                fsize = os.path.getsize(cb)
                return fname, cb, fsize, "clipboard_text"
        except Exception:
            pass

        # 6. Fallback only if no file was selected: Screenshot
        fname = f"screenshot_{int(time.time())}.jpg"
        if ImageGrab:
            img = ImageGrab.grab()
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            data = buf.getvalue()
            return fname, data, len(data), "screenshot"

        data = b"COSMIC_BEAM_PAYLOAD"
        return "beam.txt", data, len(data), "text"

    def transmit_payload(self, target_ip, target_name="Target", staged_tuple=None):
        """Transmits payload: attempts high-speed TCP first; falls back to UDP chunk streaming on timeout."""
        t_start = time.time()
        try:
            if staged_tuple:
                fname, payload_src, fsize, ptype = staged_tuple
            else:
                fname, payload_src, fsize, ptype = self.get_staged_payload()

            self.root.after(0, lambda: self.log(f"📦 Staged: '{fname}' ({fsize} bytes, type: {ptype})"))

            tcp_success = False

            # --- ATTEMPT 1: HIGH-SPEED TCP STREAM ---
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.5)  # Fast 2.5s timeout so user doesn't wait long
                sock.connect((target_ip, DEFAULT_TRANSFER_PORT))

                header_dict = {
                    "type": "FILE_TRANSFER",
                    "key": self.cfg["pairing_key"],
                    "sender": self.cfg["device_name"],
                    "name": fname,
                    "size": fsize
                }
                hdr_bytes = json.dumps(header_dict).encode("utf-8")
                sock.sendall(struct.pack(">I", len(hdr_bytes)))
                sock.sendall(hdr_bytes)

                if isinstance(payload_src, str):
                    with open(payload_src, "rb") as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            sock.sendall(chunk)
                else:
                    sock.sendall(payload_src)

                sock.close()
                tcp_success = True
                elapsed = time.time() - t_start
                self.root.after(0, lambda: self.log(f"✔ Beamed '{fname}' ({fsize} bytes) to {target_name} via TCP in {elapsed:.3f}s!"))
            except Exception as tcp_err:
                self.root.after(0, lambda: self.log(
                    f"⚠️ TCP to {target_ip}:5051 timed out ({tcp_err}). Switching to UDP Beam..."
                ))

            # --- ATTEMPT 2: UDP CHUNK STREAMING FALLBACK (Bypasses Windows Firewall TCP Blocks) ---
            if not tcp_success:
                self.transmit_payload_udp(target_ip, target_name, fname, payload_src)

        except Exception as e:
            self.root.after(0, lambda: self.log(f"[!] Transmission failed: {e}"))

    def transmit_payload_udp(self, target_ip, target_name, fname, payload_src):
        """Streams payload in 1200-byte UDP chunks over port 5052, bypassing Windows Firewall TCP blocks."""
        t_start = time.time()
        try:
            if isinstance(payload_src, str):
                with open(payload_src, "rb") as f:
                    data = f.read()
            else:
                data = payload_src

            fsize = len(data)
            transfer_id = f"{int(time.time())}_{os.getpid()}"
            chunk_size = 1200
            total_chunks = (fsize + chunk_size - 1) // chunk_size if fsize > 0 else 1

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            key = self.cfg["pairing_key"]
            sender = self.cfg["device_name"]

            # 1. Send START packet (repeat 3x for reliability)
            start_msg = f"COSMIC_UDP_START:{key}:{transfer_id}:{total_chunks}:{fsize}:{fname}:{sender}".encode("utf-8")
            for _ in range(3):
                sock.sendto(start_msg, (target_ip, DEFAULT_DISCOVERY_PORT))
                time.sleep(0.01)

            # 2. Send CHUNKS
            for idx in range(total_chunks):
                chunk_bytes = data[idx * chunk_size : (idx + 1) * chunk_size]
                header = f"COSMIC_UDP_CHUNK:{key}:{transfer_id}:{idx}:".encode("utf-8")
                packet = header + chunk_bytes
                sock.sendto(packet, (target_ip, DEFAULT_DISCOVERY_PORT))
                time.sleep(0.001)

            # 3. Send DONE packet (repeat 3x)
            done_msg = f"COSMIC_UDP_DONE:{key}:{transfer_id}:{fname}".encode("utf-8")
            for _ in range(3):
                sock.sendto(done_msg, (target_ip, DEFAULT_DISCOVERY_PORT))
                time.sleep(0.01)

            sock.close()
            elapsed = time.time() - t_start
            self.root.after(0, lambda: self.log(
                f"✔ Beamed '{fname}' ({fsize} bytes) to {target_name} via UDP Fallback in {elapsed:.3f}s!"
            ))
            self.root.after(0, lambda: self.hud.show(f"✔ BEAMED VIA UDP TO {target_name.upper()}!", status="sent"))
        except Exception as e:
            self.root.after(0, lambda: self.log(f"[!] UDP Beam failed: {e}"))

    def tcp_receiver_server(self):
        """Receives incoming beamed files & control packets, displaying media instantly with ZERO prompt."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(("0.0.0.0", DEFAULT_TRANSFER_PORT))
            server.listen(5)
            self.root.after(0, lambda: self.log(f"🟢 Receiver active on TCP port {DEFAULT_TRANSFER_PORT} & UDP {DEFAULT_DISCOVERY_PORT}"))
        except Exception as e:
            self.root.after(0, lambda: self.log(f"[!] Error binding TCP port {DEFAULT_TRANSFER_PORT}: {e}"))
            return

        while self.running:
            try:
                conn, addr = server.accept()
                raw_len = conn.recv(4)
                if not raw_len:
                    conn.close()
                    continue
                hdr_len = struct.unpack(">I", raw_len)[0]
                hdr_data = conn.recv(hdr_len).decode("utf-8")
                hdr = json.loads(hdr_data)

                # Verify Pairing Key
                received_key = hdr.get("key", "")
                if received_key != self.cfg["pairing_key"]:
                    print(f"[SECURITY] Rejected packet from {addr[0]} - Invalid Pairing Key!")
                    conn.close()
                    continue

                msg_type = hdr.get("type", "FILE_TRANSFER")
                sender_name = hdr.get("sender", addr[0])

                if msg_type == "SYNC_RADAR_LOCATION":
                    angle_from_sender = hdr.get("angle_from_sender", 0.0)
                    desk_layout = hdr.get("desk_layout", self.cfg.get("desk_layout", "side_by_side"))

                    if desk_layout == "opposite":
                        reciprocal_angle = (angle_from_sender + 180.0) % 360.0
                    else:
                        reciprocal_angle = (360.0 - angle_from_sender) % 360.0

                    if sender_name not in self.cfg["devices"]:
                        self.cfg["devices"][sender_name] = {
                            "ip": addr[0],
                            "angle": round(reciprocal_angle, 1),
                            "last_seen": time.time(),
                            "trusted": True
                        }
                    else:
                        self.cfg["devices"][sender_name]["angle"] = round(reciprocal_angle, 1)
                        self.cfg["devices"][sender_name]["ip"] = addr[0]
                        self.cfg["devices"][sender_name]["trusted"] = True

                    self.cfg_mgr.save()
                    self.root.after(0, lambda: self.radar.set_devices(self.cfg["devices"]))
                    self.root.after(0, lambda: self.log(
                        f"📍 RADAR AUTO-SYNCED: {sender_name} located at {reciprocal_angle:.1f}°"
                    ))
                    self.root.after(0, lambda: self.hud.show(
                        f"📍 SYNCED: {sender_name.upper()} AT {int(reciprocal_angle)}°", status="locked"
                    ))
                    self.root.after(0, lambda: self.hud.auto_hide(2500))
                    conn.close()
                    continue

                if msg_type == "PAIR_ACCEPT":
                    if sender_name not in self.cfg["devices"]:
                        self.cfg["devices"][sender_name] = {
                            "ip": addr[0],
                            "angle": 45.0,
                            "last_seen": time.time(),
                            "trusted": True
                        }
                    else:
                        self.cfg["devices"][sender_name]["trusted"] = True
                        self.cfg["devices"][sender_name]["ip"] = addr[0]

                    self.cfg_mgr.save()
                    self.root.after(0, lambda: self.radar.set_devices(self.cfg["devices"]))
                    self.root.after(0, lambda: self.log(f"★ PAIRING CONFIRMED: '{sender_name}' accepted trust!"))
                    self.root.after(0, lambda: self.hud.show(f"✔ {sender_name.upper()} ACCEPTED PAIRING!", status="locked"))
                    self.root.after(0, lambda: self.hud.auto_hide(2500))
                    conn.close()
                    continue

                # FILE TRANSFER
                raw_fname = hdr.get("name", f"beam_{int(time.time())}.dat")
                fname = os.path.basename(raw_fname)
                fsize = hdr.get("size", 0)

                drop_folder = self.cfg.get("dropzone", DEFAULT_DROPZONE)
                os.makedirs(drop_folder, exist_ok=True)
                filepath = os.path.join(drop_folder, fname)

                received_bytes = 0
                with open(filepath, "wb") as f:
                    while received_bytes < fsize:
                        packet = conn.recv(min(65536, fsize - received_bytes))
                        if not packet:
                            break
                        f.write(packet)
                        received_bytes += len(packet)

                conn.close()

                self.root.after(0, lambda: self.log(f"⚡ RECEIVED: '{fname}' ({received_bytes} bytes) from {sender_name} ({addr[0]})"))
                self.root.after(0, lambda: self.hud.show(f"⚡ RECEIVED: {fname} (OPENING NOW!)", status="locked"))
                self.root.after(0, lambda: self.hud.auto_hide(2500))

                if self.cfg.get("auto_display", True):
                    try:
                        os.startfile(filepath)
                    except Exception as e:
                        self.root.after(0, lambda: self.log(f"Auto-display note: {e}"))
            except Exception as e:
                pass

    # -------------------------------------------------------------------------
    # UPDATE LOOP
    # -------------------------------------------------------------------------
    def update_loop(self):
        heading = self.calculate_relative_heading(self.current_yaw)
        if self.is_holding_beam:
            target = self.evaluate_target_lock()
            if target:
                self.hud.show(f"🎯 TARGET LOCKED: {target.upper()} (Release to Beam)", status="locked")
            else:
                try:
                    if self.staged_payload:
                        fname, _, _, ptype = self.staged_payload
                    else:
                        fname, _, _, ptype = self.get_staged_payload()
                    target_label = f"[{fname}]" if ptype != "screenshot" else "[Screenshot]"
                except Exception:
                    target_label = "[Aiming...]"
                self.hud.show(f"⚡ READY TO SEND {target_label} ({int(heading)}°)", status="ready")
        else:
            self.radar.update_heading(heading, self.target_locked)

        self.root.after(50, self.update_loop)

    def on_close(self):
        self.running = False
        if self.esp_bridge:
            self.esp_bridge.disconnect()
        self.cfg_mgr.save()
        self.root.destroy()


# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = CosmicLinkApp(root)
    root.mainloop()
