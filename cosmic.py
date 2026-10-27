"""
=============================================================================
 COSMIC LINK - Sci-Fi Spatial Control Center & Instant Screen Pop-Up Engine
=============================================================================
 Features:
 1. 360° Tactical Spatial Radar:
    - Clean circular radar tracking physical air mouse heading.
    - Re-center (0°) button to calibrate forward direction.
    - Interactive drag-to-position for paired laptops.
 2. Bidirectional Nearby Discovery & Key-Based Pairing:
    - Both laptops automatically detect each other over local Wi-Fi.
    - Interactive pairing prompt ensures both enter/confirm the shared key together.
    - Mutual trust is established simultaneously on both laptops.
    - Dedicated [❌ Remove] button to unpair/forget devices anytime.
 3. Tony Stark Gesture Workflow:
    - Select/right-click file on Desktop or in Explorer.
    - Hold Button 3 (middle click) on Air Mouse & turn arm toward target laptop.
    - Release Button 3: Transmits file over Wi-Fi directly to target laptop.
    - Single-click Button 3: Switches BLE control profile between Laptop A & B.
 4. DropZone & Instant Screen Display:
    - Automatically displays/opens received images, documents, and files full-screen.
 5. Resilient Streaming:
    - High-speed direct TCP streaming with automatic UDP chunk fallback.
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
import queue
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

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
            "radar_sensitivity": 0.18,
            "aim_only_on_hold": True,
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
        self.create_text(cx + r - 16, cy, text="+90°", fill="#58a6ff", font=("Segoe UI", 7))
        self.create_text(cx - r + 16, cy, text="-90°", fill="#58a6ff", font=("Segoe UI", 7))
        self.create_text(cx, cy + r - 8, text="180° BEHIND", fill="#8b949e", font=("Segoe UI", 7))

        # 3. Rotating Radar Sweep Beam
        rad = math.radians(self.sweep_angle - 90)
        sx = cx + r * math.cos(rad)
        sy = cy + r * math.sin(rad)
        self.create_line(cx, cy, sx, sy, fill="#005533", width=2)

        # 4. Center Dot (YOU / AIR MOUSE)
        self.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill="#58a6ff", outline="#79c0ff", width=2)
        self.create_text(cx, cy + 14, text="YOU", fill="#79c0ff", font=("Segoe UI", 8, "bold"))

        # 5. Paired Device Blips
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
            self.create_text(bx, by - 14, text=f"{name} ✔\n[{tag}]", fill=color, font=("Segoe UI", 8, "bold"), justify=tk.CENTER)

        # 6. Current Air Mouse Aim Reticle
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
# COSMIC LINK MAIN APPLICATION (CLEAN STREAMLINED EDITION)
# =============================================================================
class CosmicLinkApp:
    def __init__(self, root):
        self.root = root
        self.root.title("COSMIC LINK - Spatial Control Center (Stark Edition)")
        self.root.geometry("860x650")
        self.root.minsize(820, 600)
        self.root.configure(bg="#0d1117")

        self.cfg_mgr = ConfigManager()
        self.cfg = self.cfg_mgr.config

        self.hud = FloatingHUD(self.root)
        self.local_ip = get_local_ip()

        # Motion & Spatial States
        self.current_yaw = 0.0
        self.zero_offset = 0.0
        self.is_holding_beam = False
        self.target_locked = None
        self.last_mouse_x = None

        # Staged payload cache
        self.staged_payload = None

        # Active pairing tracking to avoid duplicate prompts
        self.active_pair_prompts = set()

        # UDP fallback transfers in progress
        self.udp_transfers = {}

        # Thread-safe log queue
        self.log_queue = queue.Queue()

        # Build UI layout
        self.build_ui()

        # Start Networking & Gesture Threads safely after mainloop begins
        self.running = True
        self.root.after(100, self.start_background_services)

        # Periodic refresh loop
        self.root.after(50, self.update_loop)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def start_background_services(self):
        """Starts background threads safely once Tkinter mainloop is active."""
        threading.Thread(target=self.udp_beacon_broadcaster, daemon=True).start()
        threading.Thread(target=self.udp_beacon_listener, daemon=True).start()
        threading.Thread(target=self.tcp_receiver_server, daemon=True).start()
        self.init_spatial_listener()

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
        hdr = tk.Frame(self.root, bg="#161b22", height=48)
        hdr.pack(fill=tk.X, side=tk.TOP)

        lbl_title = tk.Label(hdr, text="🌌 COSMIC LINK", font=("Segoe UI", 13, "bold"), bg="#161b22", fg="#58a6ff")
        lbl_title.pack(side=tk.LEFT, padx=15, pady=8)

        self.lbl_status = tk.Label(
            hdr,
            text=f"My Device: {self.cfg['device_name']}  |  IP: {self.local_ip}",
            font=("Segoe UI", 9, "bold"),
            bg="#161b22",
            fg="#8b949e"
        )
        self.lbl_status.pack(side=tk.RIGHT, padx=15, pady=8)

        # Main Body Split (Left: Radar, Right: Pairing & Sharing)
        body = tk.Frame(self.root, bg="#0d1117")
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        # ----------------- Left Column: Radar HUD -----------------
        left_col = tk.Frame(body, bg="#161b22", bd=1, relief="ridge", width=360)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=6, pady=4)

        tk.Label(left_col, text="TACTICAL SPATIAL RADAR", font=("Segoe UI", 10, "bold"), bg="#161b22", fg="#58a6ff").pack(pady=(8, 4))
        self.radar = RadarCanvas(left_col, size=320)
        self.radar.pack(pady=4)
        self.radar.set_devices(self.cfg["devices"])

        # Radar Control: Single Re-center Button
        btn_recenter = tk.Button(
            left_col, text="🎯 Re-center (0°)", bg="#238636", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", command=self.recenter_zero
        )
        btn_recenter.pack(fill=tk.X, padx=16, pady=(4, 4))

        # Radar Spin Sensitivity Controls
        sens_box = tk.Frame(left_col, bg="#161b22")
        sens_box.pack(fill=tk.X, padx=16, pady=(2, 6))

        cur_sens = self.cfg.get("radar_sensitivity", 0.18)
        self.lbl_sens_val = tk.Label(
            sens_box,
            text=f"Radar Spin Speed: {int(cur_sens * 100)}%",
            font=("Segoe UI", 8, "bold"),
            bg="#161b22",
            fg="#58a6ff"
        )
        self.lbl_sens_val.pack(anchor=tk.W)

        self.slider_radar_sens = tk.Scale(
            sens_box, from_=0.04, to=0.50, resolution=0.01, orient=tk.HORIZONTAL,
            bg="#161b22", fg="#79c0ff", highlightthickness=0, showvalue=False,
            command=self.on_radar_sens_change
        )
        self.slider_radar_sens.set(cur_sens)
        self.slider_radar_sens.pack(fill=tk.X, pady=(1, 2))

        self.var_aim_only = tk.BooleanVar(value=self.cfg.get("aim_only_on_hold", True))
        chk_aim = tk.Checkbutton(
            sens_box, text="Spin only when holding Button 3", variable=self.var_aim_only,
            bg="#161b22", fg="#8b949e", selectcolor="#0d1117", activebackground="#161b22", font=("Segoe UI", 8),
            command=self.save_settings
        )
        chk_aim.pack(anchor=tk.W)

        # Workflow Instructions
        lbl_hint = tk.Label(
            left_col,
            text="✨ Tony Stark Spatial Workflow:\n\n"
                 "1. Right-click or select file in Explorer / Desktop.\n"
                 "2. Hold Button 3 & aim Air Mouse at target laptop.\n"
                 "3. Release Button 3: Transmits & auto-pops up!\n"
                 "4. Single-click Button 3: Switch control Laptop A/B.",
            font=("Segoe UI", 8),
            bg="#161b22",
            fg="#8b949e",
            justify=tk.LEFT
        )
        lbl_hint.pack(fill=tk.X, padx=16, pady=(4, 10))

        # ----------------- Right Column: Pairing, DropZone & Activity -----------------
        right_col = tk.Frame(body, bg="#161b22", bd=1, relief="ridge")
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=6, pady=4)

        # 1. Pairing & Key Setup
        tk.Label(right_col, text="PAIRING & CONNECTED LAPTOPS", font=("Segoe UI", 9, "bold"), bg="#161b22", fg="#58a6ff").pack(anchor=tk.W, padx=15, pady=(8, 2))

        key_box = tk.Frame(right_col, bg="#161b22")
        key_box.pack(fill=tk.X, padx=15, pady=2)
        tk.Label(key_box, text="Pairing Key:", bg="#161b22", fg="#c9d1d9").pack(side=tk.LEFT)
        self.entry_key = tk.Entry(key_box, bg="#0d1117", fg="#58a6ff", font=("Segoe UI", 9, "bold"), width=16, relief="flat")
        self.entry_key.insert(0, self.cfg.get("pairing_key", DEFAULT_PAIRING_KEY))
        self.entry_key.pack(side=tk.LEFT, padx=6)
        btn_set_key = tk.Button(key_box, text="Set Key", bg="#21262d", fg="#79c0ff", relief="flat", command=self.update_pairing_key)
        btn_set_key.pack(side=tk.LEFT, padx=2)

        btn_manual_pair = tk.Button(key_box, text="➕ Pair with IP", bg="#21262d", fg="#7ee787", relief="flat", command=self.manual_pair_prompt)
        btn_manual_pair.pack(side=tk.RIGHT)

        # Paired Devices Container
        self.devices_frame = tk.Frame(right_col, bg="#0d1117", bd=1, relief="sunken", height=110)
        self.devices_frame.pack(fill=tk.X, padx=15, pady=(4, 8))
        self.devices_frame.pack_propagate(False)

        self.refresh_devices_ui()

        # 2. Sharing & DropZone Settings
        tk.Label(right_col, text="SHARING & DROPZONE", font=("Segoe UI", 9, "bold"), bg="#161b22", fg="#58a6ff").pack(anchor=tk.W, padx=15, pady=(4, 2))

        self.var_autodisplay = tk.BooleanVar(value=self.cfg.get("auto_display", True))
        chk_auto = tk.Checkbutton(
            right_col, text="Instant Screen Display (Auto-Popup on Receive)", variable=self.var_autodisplay,
            bg="#161b22", fg="#c9d1d9", selectcolor="#0d1117", activebackground="#161b22",
            command=self.save_settings
        )
        chk_auto.pack(anchor=tk.W, padx=15, pady=2)

        dz_frame = tk.Frame(right_col, bg="#161b22")
        dz_frame.pack(fill=tk.X, padx=15, pady=2)
        tk.Label(dz_frame, text="DropZone Path:", font=("Segoe UI", 8), bg="#161b22", fg="#8b949e").pack(side=tk.LEFT)
        self.entry_dz = tk.Entry(dz_frame, bg="#0d1117", fg="#c9d1d9", insertbackground="#58a6ff", relief="flat")
        self.entry_dz.insert(0, self.cfg.get("dropzone", DEFAULT_DROPZONE))
        self.entry_dz.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        btn_browse = tk.Button(dz_frame, text="📂 Browse", bg="#30363d", fg="white", relief="flat", command=self.browse_dropzone)
        btn_browse.pack(side=tk.LEFT)

        # 3. Activity Log / Recent Beams
        tk.Label(right_col, text="ACTIVITY LOG & RECENT BEAMS", font=("Segoe UI", 8, "bold"), bg="#161b22", fg="#8b949e").pack(anchor=tk.W, padx=15, pady=(8, 2))
        self.txt_log = tk.Text(right_col, height=8, bg="#0d1117", fg="#7ee787", font=("Consolas", 8), relief="flat")
        self.txt_log.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

    def log(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        entry = f"[{timestamp}] {msg}"
        try:
            if hasattr(self, "log_queue"):
                self.log_queue.put(entry)
            else:
                print(entry)
        except Exception:
            print(entry)

    def refresh_devices_ui(self):
        """Rebuilds the Paired Devices List with clean [❌ Remove] buttons."""
        for widget in self.devices_frame.winfo_children():
            widget.destroy()

        devices = self.cfg.get("devices", {})
        if not devices:
            lbl_empty = tk.Label(
                self.devices_frame,
                text="No laptops paired yet.\nTurn on Wi-Fi and open Cosmic Link on both laptops to discover.",
                font=("Segoe UI", 8),
                bg="#0d1117",
                fg="#6e7681",
                justify=tk.CENTER
            )
            lbl_empty.pack(expand=True, pady=10)
            return

        for name, data in list(devices.items()):
            row = tk.Frame(self.devices_frame, bg="#161b22", bd=1, relief="ridge")
            row.pack(fill=tk.X, padx=6, pady=2)

            ip = data.get("ip", "Unknown IP")
            ang = data.get("angle", 0.0)

            lbl_dev = tk.Label(
                row,
                text=f"💻 {name}  ({ip})  |  Radar: {int(ang)}°",
                font=("Segoe UI", 8, "bold"),
                bg="#161b22",
                fg="#58a6ff"
            )
            lbl_dev.pack(side=tk.LEFT, padx=8, pady=4)

            btn_del = tk.Button(
                row,
                text="❌ Remove",
                bg="#b62324",
                fg="white",
                font=("Segoe UI", 7, "bold"),
                relief="flat",
                command=lambda d=name: self.remove_paired_device(d)
            )
            btn_del.pack(side=tk.RIGHT, padx=6, pady=2)

    def remove_paired_device(self, name):
        """Removes device from local paired list and notifies remote device."""
        if name in self.cfg["devices"]:
            target_ip = self.cfg["devices"][name].get("ip")
            del self.cfg["devices"][name]
            self.cfg_mgr.save()
            self.radar.set_devices(self.cfg["devices"])
            self.refresh_devices_ui()
            self.log(f"🗑️ Removed '{name}' from paired devices.")

            # Notify peer to also unpair
            if target_ip:
                threading.Thread(
                    target=self.send_unpair_notify,
                    args=(target_ip,),
                    daemon=True
                ).start()

    def send_unpair_notify(self, target_ip):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            my_name = self.cfg["device_name"]
            msg = f"COSMIC_UNPAIR:{my_name}".encode("utf-8")
            sock.sendto(msg, (target_ip, DEFAULT_DISCOVERY_PORT))
            sock.close()
        except Exception:
            pass

    def browse_dropzone(self):
        folder = filedialog.askdirectory(initialdir=self.entry_dz.get())
        if folder:
            self.entry_dz.delete(0, tk.END)
            self.entry_dz.insert(0, folder)
            self.save_settings()

    def update_pairing_key(self):
        new_key = self.entry_key.get().strip()
        if new_key:
            self.cfg["pairing_key"] = new_key
            self.cfg_mgr.save()
            self.log(f"🔑 Shared Pairing Key updated to '{new_key}'.")
            messagebox.showinfo("Pairing Key", f"Pairing Key set to:\n{new_key}\n\nEnter this exact key on your other laptop.")

    def on_radar_sens_change(self, val):
        sens = float(val)
        self.cfg["radar_sensitivity"] = round(sens, 2)
        if hasattr(self, "lbl_sens_val"):
            self.lbl_sens_val.config(text=f"Radar Spin Speed: {int(sens * 100)}%")
        self.cfg_mgr.save()

    def save_settings(self):
        self.cfg["auto_display"] = self.var_autodisplay.get()
        self.cfg["dropzone"] = self.entry_dz.get()
        if hasattr(self, "var_aim_only"):
            self.cfg["aim_only_on_hold"] = self.var_aim_only.get()
        if hasattr(self, "slider_radar_sens"):
            self.cfg["radar_sensitivity"] = float(self.slider_radar_sens.get())
        self.cfg_mgr.save()

    def recenter_zero(self):
        """Snaps current air mouse heading as 0° Forward."""
        self.zero_offset = self.current_yaw
        self.log("🎯 Radar re-centered: Current heading is now 0° Forward.")
        self.radar.update_heading(0.0)

    def calculate_relative_heading(self, raw_yaw):
        return (raw_yaw - self.zero_offset + 360) % 360

    def evaluate_target_lock(self):
        """Finds if current air mouse aim points at any paired laptop (within ±25°)."""
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
            self.log("[!] pynput not available - install pynput for spatial gestures.")
            return

        self.mouse_controller = mouse.Controller()

        def on_move(x, y):
            if self.last_mouse_x is not None:
                dx = x - self.last_mouse_x
                aim_only = self.cfg.get("aim_only_on_hold", True)

                # Only spin radar reticle if holding Button 3, or if aim_only_on_hold is turned off
                if self.is_holding_beam or not aim_only:
                    sens = self.cfg.get("radar_sensitivity", 0.18)
                    yaw_delta = dx * sens
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
                if pressed:
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
        # Stage payload immediately when Button 3 is pressed down
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

    # -------------------------------------------------------------------------
    # NETWORKING: BIDIRECTIONAL DISCOVERY & MUTUAL KEY PAIRING
    # -------------------------------------------------------------------------
    def udp_beacon_broadcaster(self):
        """Broadcasts nearby presence on Wi-Fi every 2 seconds."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        while self.running:
            try:
                my_name = self.cfg["device_name"]
                msg = f"COSMIC_NEARBY:{my_name}:{self.local_ip}".encode("utf-8")
                sock.sendto(msg, ("<broadcast>", DEFAULT_DISCOVERY_PORT))
            except Exception:
                pass
            time.sleep(2.0)

    def udp_beacon_listener(self):
        """Hears nearby announcements, pairing handshakes, and UDP file chunks."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", DEFAULT_DISCOVERY_PORT))
        except Exception as e:
            self.log(f"[BEACON] Port bind error on {DEFAULT_DISCOVERY_PORT}: {e}")
            return

        while self.running:
            try:
                data, addr = sock.recvfrom(65536)

                # 1. Nearby Device Announcement
                if data.startswith(b"COSMIC_NEARBY:"):
                    msg = data.decode("utf-8", errors="ignore")
                    parts = msg.split(":")
                    if len(parts) >= 3:
                        dev_name = parts[1]
                        dev_ip = parts[2]

                        # Ignore self
                        if dev_name == self.cfg["device_name"]:
                            continue

                        # If already paired, update IP & last_seen
                        if dev_name in self.cfg["devices"]:
                            self.cfg["devices"][dev_name]["ip"] = dev_ip
                            self.cfg["devices"][dev_name]["last_seen"] = time.time()
                            continue

                        # If not paired and not already prompting, alert user
                        if dev_name not in self.active_pair_prompts:
                            self.active_pair_prompts.add(dev_name)
                            self.root.after(0, lambda d=dev_name, ip=dev_ip: self.prompt_mutual_pair(d, ip))
                    continue

                # 2. Incoming Pair Request with Key
                if data.startswith(b"COSMIC_PAIR_REQ:"):
                    msg = data.decode("utf-8", errors="ignore")
                    parts = msg.split(":")
                    if len(parts) >= 4:
                        sender_key = parts[1]
                        dev_name   = parts[2]
                        dev_ip     = parts[3]

                        if dev_name == self.cfg["device_name"]:
                            continue

                        # Prompt user on this laptop to confirm the pairing key
                        self.root.after(0, lambda k=sender_key, d=dev_name, ip=dev_ip: self.handle_incoming_pair_req(k, d, ip))
                    continue

                # 3. Incoming Pair Acceptance Handshake
                if data.startswith(b"COSMIC_PAIR_ACK:"):
                    msg = data.decode("utf-8", errors="ignore")
                    parts = msg.split(":")
                    if len(parts) >= 4:
                        sender_key = parts[1]
                        dev_name   = parts[2]
                        dev_ip     = parts[3]

                        if sender_key == self.cfg["pairing_key"]:
                            existing_count = len(self.cfg["devices"])
                            assigned_angle = (45.0 + existing_count * 60.0) % 360.0
                            self.cfg["devices"][dev_name] = {
                                "ip": dev_ip,
                                "angle": round(assigned_angle, 1),
                                "last_seen": time.time(),
                                "trusted": True
                            }
                            self.cfg_mgr.save()
                            self.root.after(0, lambda: self.radar.set_devices(self.cfg["devices"]))
                            self.root.after(0, self.refresh_devices_ui)
                            self.root.after(0, lambda: self.log(f"★ MUTUAL PAIRING SUCCESS with '{dev_name}' ({dev_ip})!"))
                            self.root.after(0, lambda: self.hud.show(f"✔ PAIRED WITH {dev_name.upper()}!", status="locked"))
                            self.root.after(0, lambda: self.hud.auto_hide(2500))
                    continue

                # 4. Peer Unpaired Notification
                if data.startswith(b"COSMIC_UNPAIR:"):
                    msg = data.decode("utf-8", errors="ignore")
                    parts = msg.split(":")
                    if len(parts) >= 2:
                        unpair_name = parts[1]
                        if unpair_name in self.cfg["devices"]:
                            del self.cfg["devices"][unpair_name]
                            self.cfg_mgr.save()
                            self.root.after(0, lambda: self.radar.set_devices(self.cfg["devices"]))
                            self.root.after(0, self.refresh_devices_ui)
                            self.root.after(0, lambda: self.log(f"ℹ️ '{unpair_name}' unpaired."))
                    continue

                # 5. UDP File Transfer Fallback
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

                            full_bytes = b"".join([chunks_dict.get(i, b"") for i in range(total)])
                            drop_folder = self.cfg.get("dropzone", DEFAULT_DROPZONE)
                            os.makedirs(drop_folder, exist_ok=True)
                            filepath = os.path.join(drop_folder, fname)

                            with open(filepath, "wb") as f:
                                f.write(full_bytes)

                            del self.udp_transfers[tid]

                            sender = t_info.get("sender", addr[0])
                            self.root.after(0, lambda: self.log(
                                f"⚡ RECEIVED: '{fname}' ({len(full_bytes)} bytes) via UDP from {sender}!"
                            ))
                            self.root.after(0, lambda: self.hud.show(f"⚡ RECEIVED: {fname} (OPENING NOW!)", status="locked"))
                            self.root.after(0, lambda: self.hud.auto_hide(2500))

                            if self.cfg.get("auto_display", True):
                                try:
                                    os.startfile(filepath)
                                except Exception as e:
                                    self.root.after(0, lambda: self.log(f"Auto-display note: {e}"))
                    continue

            except Exception:
                pass

    def prompt_mutual_pair(self, dev_name, dev_ip):
        """Alerts the user that a nearby laptop was found and asks to pair."""
        ans = messagebox.askyesno(
            "Cosmic Link - Nearby Laptop Detected",
            f"Nearby Laptop Detected on Local Wi-Fi!\n\n"
            f"• Device Name: {dev_name}\n"
            f"• IP Address: {dev_ip}\n\n"
            f"Would you like to pair with '{dev_name}' using your Pairing Key ({self.cfg['pairing_key']})?",
            parent=self.root
        )
        if ans:
            # Send pair request packet to peer
            self.send_pair_request(dev_ip, dev_name)
        else:
            self.log(f"ℹ️ Ignored nearby discovery for '{dev_name}'.")

    def send_pair_request(self, target_ip, target_name):
        """Sends a pairing request containing our key to the peer laptop."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            my_key = self.cfg["pairing_key"]
            my_name = self.cfg["device_name"]
            msg = f"COSMIC_PAIR_REQ:{my_key}:{my_name}:{self.local_ip}".encode("utf-8")
            sock.sendto(msg, (target_ip, DEFAULT_DISCOVERY_PORT))
            sock.close()
            self.log(f"📡 Sent pairing request to '{target_name}' ({target_ip}). Awaiting confirmation...")
        except Exception as e:
            self.log(f"[!] Error sending pair request: {e}")

    def handle_incoming_pair_req(self, sender_key, sender_name, sender_ip):
        """Prompts this user when another laptop requests pairing."""
        my_key = self.cfg["pairing_key"]

        # Check if keys match or prompt user to verify
        if sender_key == my_key:
            msg_text = (
                f"Laptop '{sender_name}' ({sender_ip}) wants to pair!\n\n"
                f"Their Pairing Key matches yours: '{my_key}'.\n\n"
                f"Accept pairing and establish mutual connection?"
            )
            ans = messagebox.askyesno("Incoming Pairing Request", msg_text, parent=self.root)
        else:
            entered = simpledialog.askstring(
                "Pairing Key Verification",
                f"Laptop '{sender_name}' ({sender_ip}) is requesting to pair.\n\n"
                f"Please enter the shared Pairing Key to verify:",
                parent=self.root
            )
            ans = (entered and entered.strip() == sender_key)
            if ans:
                my_key = entered.strip()
                self.cfg["pairing_key"] = my_key
                self.cfg_mgr.save()
                self.entry_key.delete(0, tk.END)
                self.entry_key.insert(0, my_key)

        if ans:
            # Pair accepted! Add to devices list
            existing_count = len(self.cfg["devices"])
            assigned_angle = (315.0 - existing_count * 60.0 + 360.0) % 360.0
            self.cfg["devices"][sender_name] = {
                "ip": sender_ip,
                "angle": round(assigned_angle, 1),
                "last_seen": time.time(),
                "trusted": True
            }
            self.cfg_mgr.save()
            self.radar.set_devices(self.cfg["devices"])
            self.refresh_devices_ui()

            # Send ACK back to the requesting laptop so it pairs simultaneously!
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                my_name = self.cfg["device_name"]
                ack_msg = f"COSMIC_PAIR_ACK:{my_key}:{my_name}:{self.local_ip}".encode("utf-8")
                sock.sendto(ack_msg, (sender_ip, DEFAULT_DISCOVERY_PORT))
                sock.close()
            except Exception:
                pass

            self.log(f"★ TRUST ESTABLISHED with '{sender_name}' ({sender_ip})!")
            self.hud.show(f"✔ PAIRED WITH {sender_name.upper()}!", status="locked")
            self.hud.auto_hide(2500)
        else:
            self.log(f"✖ Pairing request from '{sender_name}' was declined.")

        self.active_pair_prompts.discard(sender_name)

    def manual_pair_prompt(self):
        """Allows pairing directly with IP if Wi-Fi router blocks UDP broadcast."""
        ip = simpledialog.askstring("Pair with IP", "Enter peer laptop IP address:", parent=self.root)
        if ip and ip.strip():
            target_ip = ip.strip()
            self.send_pair_request(target_ip, f"Laptop@{target_ip}")

    # -------------------------------------------------------------------------
    # NETWORKING: HIGH-SPEED BEAM TRANSMITTER & RECEIVER
    # -------------------------------------------------------------------------
    def get_staged_payload(self):
        """Grabs the file right-clicked/selected in Explorer, desktop, clipboard, or screenshot."""
        if pythoncom:
            try:
                pythoncom.CoInitialize()
            except Exception:
                pass

        # 1. Check open Windows File Explorer windows
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

            # 2. Check Windows Desktop selected items
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

        # 3. Check Clipboard file list (CF_HDROP)
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

        # 4. Check if clipboard text contains an existing file path
        try:
            cb = self.root.clipboard_get().strip('"\' \r\n')
            if cb and os.path.isfile(cb):
                fname = os.path.basename(cb)
                fsize = os.path.getsize(cb)
                return fname, cb, fsize, "clipboard_text"
        except Exception:
            pass

        # 5. Fallback only if no file was selected: Screenshot
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
        """Transmits payload: attempts direct TCP first, falls back to UDP streaming if needed."""
        t_start = time.time()
        try:
            if staged_tuple:
                fname, payload_src, fsize, ptype = staged_tuple
            else:
                fname, payload_src, fsize, ptype = self.get_staged_payload()

            self.root.after(0, lambda: self.log(f"📦 Payload: '{fname}' ({fsize} bytes, type: {ptype})"))

            tcp_success = False

            # --- ATTEMPT 1: HIGH-SPEED TCP STREAM ---
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.5)
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
                self.root.after(0, lambda: self.log(f"✔ Beamed '{fname}' ({fsize} bytes) to {target_name} in {elapsed:.3f}s!"))
            except Exception as tcp_err:
                self.root.after(0, lambda: self.log(
                    f"⚠️ Direct TCP timed out ({tcp_err}). Switching to UDP Fallback Beam..."
                ))

            # --- ATTEMPT 2: UDP CHUNK STREAMING FALLBACK ---
            if not tcp_success:
                self.transmit_payload_udp(target_ip, target_name, fname, payload_src)

        except Exception as e:
            self.root.after(0, lambda: self.log(f"[!] Transmission failed: {e}"))

    def transmit_payload_udp(self, target_ip, target_name, fname, payload_src):
        """Streams payload in 1200-byte UDP chunks over port 5052."""
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

            # 1. Send START packet (3x for UDP reliability)
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

            # 3. Send DONE packet (3x)
            done_msg = f"COSMIC_UDP_DONE:{key}:{transfer_id}:{fname}".encode("utf-8")
            for _ in range(3):
                sock.sendto(done_msg, (target_ip, DEFAULT_DISCOVERY_PORT))
                time.sleep(0.01)

            sock.close()
            elapsed = time.time() - t_start
            self.root.after(0, lambda: self.log(
                f"✔ Beamed '{fname}' ({fsize} bytes) to {target_name} via UDP in {elapsed:.3f}s!"
            ))
            self.root.after(0, lambda: self.hud.show(f"✔ BEAMED VIA UDP TO {target_name.upper()}!", status="sent"))
        except Exception as e:
            self.root.after(0, lambda: self.log(f"[!] UDP Beam failed: {e}"))

    def tcp_receiver_server(self):
        """Receives incoming beamed files & control packets, displaying media instantly with zero prompt."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(("0.0.0.0", DEFAULT_TRANSFER_PORT))
            server.listen(5)
            self.log(f"🟢 Receiver ready on TCP {DEFAULT_TRANSFER_PORT} & UDP {DEFAULT_DISCOVERY_PORT}")
        except Exception as e:
            self.log(f"[!] Error binding TCP port {DEFAULT_TRANSFER_PORT}: {e}")
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

                sender_name = hdr.get("sender", addr[0])

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
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # UPDATE LOOP
    # -------------------------------------------------------------------------
    def update_loop(self):
        # Drain log queue safely in the Tkinter main thread
        while not self.log_queue.empty():
            try:
                msg = self.log_queue.get_nowait()
                self.txt_log.insert(tk.END, f"{msg}\n")
                self.txt_log.see(tk.END)
            except Exception:
                break

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
        self.cfg_mgr.save()
        self.root.destroy()


# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = CosmicLinkApp(root)
    root.mainloop()
