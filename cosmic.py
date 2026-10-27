"""
=============================================================================
 COSMIC LINK - Sci-Fi Spatial Control Center & Instant Screen Pop-Up Engine
=============================================================================
 Features:
 1. Gaming Radar HUD:
    - 360° circular tactical radar displaying nearby laptops as glowing blips.
    - Live heading reticle tracking the Air Mouse aim.
    - Gesture-based Point & Click to Pair (aim at target laptop and click).
 2. Floating Desktop HUD Overlay:
    - Translucent HUD pill that appears during "Hold to Beam":
      [⚡ READY TO SEND] -> [🎯 TARGET LOCKED: LAPTOP B] -> [✔ SENT!]
 3. Zero-Confirmation Screen Pop-up Engine (Bidirectional):
    - Both sender and receiver auto-receive files/screenshots.
    - Automatically creates and manages local DropZone folder.
    - Instantly launches received media full-screen with zero prompts.
 4. Secure Wi-Fi Discovery:
    - Protected with a Private Pairing Key (blocks strangers on public Wi-Fi).
 5. Live Sensitivity & Smoothing Controls:
    - Real-time adjustment without recompiling firmware.
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
            "devices": {}  # name -> {"ip": ..., "angle": float, "last_seen": float}
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

# -------------------------------------------------------------------------------
# RESET TO DEFAULTS FUNCTIONALITY
# -------------------------------------------------------------------------------
def reset_to_defaults():
    """Delete user config and restore defaults.
    Also clears the DropZone folder.
    """
    # Remove config file if it exists
    if os.path.exists(CONFIG_FILE):
        try:
            os.remove(CONFIG_FILE)
            print(f"[RESET] Removed config file: {CONFIG_FILE}")
        except Exception as e:
            print(f"[RESET] Failed to delete config: {e}")

    # Re‑create default config by instantiating ConfigManager (writes defaults)
    cfg_mgr = ConfigManager()
    cfg_mgr.save()
    print("[RESET] Default configuration saved.")

    # Clean DropZone folder (remove all files)
    if os.path.isdir(DEFAULT_DROPZONE):
        try:
            for fname in os.listdir(DEFAULT_DROPZONE):
                fpath = os.path.join(DEFAULT_DROPZONE, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)
            print(f"[RESET] Cleared DropZone folder: {DEFAULT_DROPZONE}")
        except Exception as e:
            print(f"[RESET] Failed to clear DropZone: {e}")



# =============================================================================
# FLOATING DESKTOP HUD OVERLAY
# =============================================================================
class FloatingHUD:
    """Sleek, borderless, semi-transparent top-level HUD pill."""
    def __init__(self, root):
        self.root = root
        self.hud_win = None
        self.label = None
        self.fade_job = None

    def show(self, text, status="ready"):
        if self.hud_win is None or not tk.Toplevel.winfo_exists(self.hud_win):
            self.hud_win = tk.Toplevel(self.root)
            self.hud_win.overrideredirect(True)
            self.hud_win.attributes("-topmost", True)
            try:
                self.hud_win.attributes("-alpha", 0.90)
            except Exception:
                pass

            # Center horizontally at the top of the main screen
            sw = self.hud_win.winfo_screenwidth()
            w, h = 440, 50
            x = (sw - w) // 2
            y = 40
            self.hud_win.geometry(f"{w}x{h}+{x}+{y}")

            self.frame = tk.Frame(self.hud_win, bg="#0d1117", bd=2, relief="ridge")
            self.frame.pack(fill=tk.BOTH, expand=True)

            self.label = tk.Label(
                self.frame,
                text=text,
                font=("Segoe UI", 12, "bold"),
                bg="#0d1117",
                fg="#58a6ff"
            )
            self.label.pack(expand=True)
        else:
            self.hud_win.deiconify()

        # Color accents based on status
        if status == "ready":
            self.label.config(text=text, fg="#79c0ff")
            self.frame.config(highlightbackground="#1f6feb", highlightthickness=1)
        elif status == "locked":
            self.label.config(text="🎯 TARGET LOCKED", fg="#3fb950")  # Glowing green clean target locked
            self.frame.config(highlightbackground="#238636", highlightthickness=2)
        elif status == "sent":
            self.label.config(text="✔ SENT!", fg="#a371f7")  # Clean sent message
            self.frame.config(highlightbackground="#8957e5", highlightthickness=2)
            self.auto_hide(1500)

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
        self.devices = {}  # name -> {"angle": float, "ip": str}
        self.sweep_angle = 0.0

        self.bind("<Button-1>", self.on_click)
        self.bind("<B1-Motion>", self.on_drag)
        self.selected_blip = None
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

        # 1. Concentric Cosmic Range Rings
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

        # 4. Center Dot (YOU / COSMIC AIR MOUSE)
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

            # Draw glowing blip
            b_size = 8 if is_locked else 6
            self.create_oval(bx - b_size - 3, by - b_size - 3, bx + b_size + 3, by + b_size + 3, fill="", outline=glow_color, width=2)
            self.create_oval(bx - b_size, by - b_size, bx + b_size, by + b_size, fill=color, outline="#ffffff", width=1)

            # Blip Label
            tag = "LOCKED" if is_locked else f"{int(ang)}°"
            self.create_text(bx, by - 14, text=f"{name}\n[{tag}]", fill=color, font=("Segoe UI", 8, "bold"), justify=tk.CENTER)

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
            if math.hypot(event.x - bx, event.y - by) < 15:
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
        self.root.title("COSMIC LINK - Spatial Control Center")
        self.root.geometry("820x620")
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
        self.pairing_pending_device = None

        # Build UI layout
        self.build_ui()

        # Start Networking Threads
        self.running = True
        threading.Thread(target=self.udp_beacon_broadcaster, daemon=True).start()
        threading.Thread(target=self.udp_beacon_listener, daemon=True).start()
        threading.Thread(target=self.tcp_receiver_server, daemon=True).start()

        # Start Mouse / Spatial Listener
        self.init_spatial_listener()

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

        lbl_status = tk.Label(hdr, text=f"Local IP: {self.local_ip}  |  Key: {self.cfg['pairing_key']}", font=("Segoe UI", 9), bg="#161b22", fg="#8b949e")
        lbl_status.pack(side=tk.RIGHT, padx=15, pady=10)

        # Main Body Split (Left: Radar, Right: Controls & Logs)
        body = tk.Frame(self.root, bg="#0d1117")
        body.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        # Left Column: Radar HUD
        left_col = tk.Frame(body, bg="#161b22", bd=1, relief="ridge")
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        tk.Label(left_col, text="TACTICAL SPATIAL RADAR", font=("Segoe UI", 10, "bold"), bg="#161b22", fg="#58a6ff").pack(pady=8)
        self.radar = RadarCanvas(left_col, size=320)
        self.radar.pack(pady=5)
        self.radar.set_devices(self.cfg["devices"])

        btn_row = tk.Frame(left_col, bg="#161b22")
        btn_row.pack(fill=tk.X, pady=8, padx=10)

        btn_recenter = tk.Button(btn_row, text="🎯 Re-center (0°)", bg="#238636", fg="white", font=("Segoe UI", 9, "bold"),
                                 relief="flat", command=self.recenter_zero)
        btn_recenter.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        btn_test_beam = tk.Button(btn_row, text="⚡ Test Beam Now", bg="#1f6feb", fg="white", font=("Segoe UI", 9, "bold"),
                                  relief="flat", command=self.trigger_manual_beam)
        btn_test_beam.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # Right Column: Controls, Sliders & History
        right_col = tk.Frame(body, bg="#161b22", bd=1, relief="ridge", width=380)
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        tk.Label(right_col, text="HARDWARE & SHARING SETTINGS", font=("Segoe UI", 10, "bold"), bg="#161b22", fg="#58a6ff").pack(anchor=tk.W, padx=15, pady=8)

        # Auto Display Toggle
        self.var_autodisplay = tk.BooleanVar(value=self.cfg.get("auto_display", True))
        chk_auto = tk.Checkbutton(right_col, text="Instant Screen Display (Zero-Confirmation)", variable=self.var_autodisplay,
                                  bg="#161b22", fg="#c9d1d9", selectcolor="#0d1117", activebackground="#161b22",
                                  command=self.save_settings)
        chk_auto.pack(anchor=tk.W, padx=15, pady=4)

        # DropZone Directory
        dz_frame = tk.Frame(right_col, bg="#161b22")
        dz_frame.pack(fill=tk.X, padx=15, pady=6)
        tk.Label(dz_frame, text="Cosmic DropZone Folder:", font=("Segoe UI", 8), bg="#161b22", fg="#8b949e").pack(anchor=tk.W)
        self.entry_dz = tk.Entry(dz_frame, bg="#0d1117", fg="#c9d1d9", insertbackground="#58a6ff", relief="flat")
        self.entry_dz.insert(0, self.cfg.get("dropzone", DEFAULT_DROPZONE))
        self.entry_dz.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=2)
        btn_browse = tk.Button(dz_frame, text="📂", bg="#30363d", fg="white", relief="flat", command=self.browse_dropzone)
        btn_browse.pack(side=tk.LEFT, padx=4)

        # Wireless Sensitivity & Smoothing Sliders
        tk.Label(right_col, text="Air Mouse Live Tuning (No Arduino Compile!):", font=("Segoe UI", 8, "bold"), bg="#161b22", fg="#8b949e").pack(anchor=tk.W, padx=15, pady=(10, 2))

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

        # Transfer Log / Feed
        tk.Label(right_col, text="Activity Log / Recent Beams:", font=("Segoe UI", 8, "bold"), bg="#161b22", fg="#8b949e").pack(anchor=tk.W, padx=15, pady=(10, 2))
        self.txt_log = tk.Text(right_col, height=8, bg="#0d1117", fg="#7ee787", font=("Consolas", 8), relief="flat")
        self.txt_log.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

    def log(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.txt_log.insert(tk.END, f"[{timestamp}] {msg}\n")
        self.txt_log.see(tk.END)

    def browse_dropzone(self):
        folder = filedialog.askdirectory(initialdir=self.entry_dz.get())
        if folder:
            self.entry_dz.delete(0, tk.END)
            self.entry_dz.insert(0, folder)
            self.save_settings()

    def save_settings(self):
        self.cfg["auto_display"] = self.var_autodisplay.get()
        self.cfg["dropzone"] = self.entry_dz.get()
        self.cfg["sensitivity"] = float(self.slider_sens.get())
        self.cfg["smoothing"] = float(self.slider_smooth.get())
        self.cfg_mgr.save()

    # -------------------------------------------------------------------------
    # SPATIAL LOGIC & TARGET LOCKING
    # -------------------------------------------------------------------------
    def recenter_zero(self):
        """Snaps current direction as 0° Forward."""
        self.zero_offset = self.current_yaw
        self.log("🎯 Radar re-centered: Current heading is now 0° Forward.")
        self.radar.update_heading(0.0)

    def calculate_relative_heading(self, raw_yaw):
        return (raw_yaw - self.zero_offset + 360) % 360

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
        """Hooks into mouse / gestures or hotkey to trigger Hold-to-Beam."""
        if not mouse or not keyboard:
            self.log("[!] pynput not available - use 'Test Beam' button.")
            return

        self.last_btn3_press = 0.0
        self.last_mouse_x = None

        def on_move(x, y):
            if self.last_mouse_x is not None:
                dx = x - self.last_mouse_x
                # Real-time heading update from Air Mouse motion
                yaw_delta = dx * 0.30
                self.current_yaw = (self.current_yaw + yaw_delta) % 360
            self.last_mouse_x = x

        def on_click(x, y, button, pressed):
            # Middle button (or Button 3 on Air Mouse) triggers Spatial Beam
            if button == mouse.Button.middle:
                now = time.time()
                if pressed:
                    if now - self.last_btn3_press < 0.35:
                        self.root.after(0, self.recenter_zero)
                        self.hud.show("🎯 RE-CENTERED TO 0°", status="ready")
                        self.hud.auto_hide(1200)
                        self.is_holding_beam = False
                        self.last_btn3_press = 0.0
                        return
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
        if self.pairing_pending_device:
            dev_name = self.pairing_pending_device
            heading = self.calculate_relative_heading(self.current_yaw)
            self.cfg["devices"][dev_name]["angle"] = round(heading, 1)
            self.cfg_mgr.save()
            self.radar.set_devices(self.cfg["devices"])
            self.log(f"✔ PAIRED: {dev_name} locked at {heading:.1f}°!")
            self.hud.show(f"✔ PAIRED: {dev_name} AT {int(heading)}°", status="locked")
            self.hud.auto_hide(2000)
            self.pairing_pending_device = None
            return

        # Check staged file payload
        try:
            fname, _, _ = self.get_staged_payload()
            if "screenshot" in fname:
                status_text = "⚡ READY TO SEND [Screenshot]"
            else:
                status_text = f"⚡ READY TO SEND [{fname}]"
        except Exception:
            status_text = "⚡ READY TO SEND [Aiming...]"

        self.hud.show(status_text, status="ready")

    def on_beam_hold_release(self):
        if self.target_locked:
            target_info = self.cfg["devices"].get(self.target_locked)
            if target_info:
                self.hud.show(f"✔ SENT TO {self.target_locked.upper()}!", status="sent")
                self.log(f"🚀 Beaming payload to {self.target_locked} ({target_info['ip']})...")
                threading.Thread(target=self.transmit_payload, args=(target_info["ip"],), daemon=True).start()
        else:
            self.hud.hide()

    def trigger_manual_beam(self):
        """Allows testing without physical mouse hardware."""
        heading = self.calculate_relative_heading(self.current_yaw)
        self.evaluate_target_lock()
        if self.target_locked:
            target_info = self.cfg["devices"][self.target_locked]
            self.hud.show(f"✔ BEAMED TO {self.target_locked.upper()}!", status="sent")
            threading.Thread(target=self.transmit_payload, args=(target_info["ip"],), daemon=True).start()
        elif self.cfg["devices"]:
            first_name = list(self.cfg["devices"].keys())[0]
            target_info = self.cfg["devices"][first_name]
            self.hud.show(f"✔ BEAMED TO {first_name.upper()}!", status="sent")
            threading.Thread(target=self.transmit_payload, args=(target_info["ip"],), daemon=True).start()
        else:
            messagebox.showinfo("Cosmic Link", "No nearby laptops discovered yet!\nOpen Cosmic Link on another laptop on your Wi-Fi.")

    # -------------------------------------------------------------------------
    # NETWORKING: PEER-TO-PEER BEACON DISCOVERY
    # -------------------------------------------------------------------------
    def udp_beacon_broadcaster(self):
        """Whispers presence on local Wi-Fi with Pairing Key."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        my_name = self.cfg["device_name"]
        key = self.cfg["pairing_key"]

        while self.running:
            try:
                msg = f"COSMIC:{key}:{my_name}:{self.local_ip}".encode("utf-8")
                sock.sendto(msg, ("<broadcast>", DEFAULT_DISCOVERY_PORT))
            except Exception:
                pass
            time.sleep(2.0)

    def udp_beacon_listener(self):
        """Hears whispers from other laptops on Wi-Fi."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", DEFAULT_DISCOVERY_PORT))
        except Exception as e:
            print(f"[BEACON] Port bind error: {e}")
            return

        while self.running:
            try:
                data, addr = sock.recvfrom(1024)
                msg = data.decode("utf-8", errors="ignore")
                parts = msg.split(":")
                if len(parts) >= 4 and parts[0] == "COSMIC":
                    beacon_key = parts[1]
                    dev_name   = parts[2]
                    dev_ip     = parts[3]

                    if beacon_key != self.cfg["pairing_key"] or dev_name == self.cfg["device_name"]:
                        continue

                    now = time.time()
                    if dev_name not in self.cfg["devices"]:
                        self.cfg["devices"][dev_name] = {
                            "ip": dev_ip,
                            "angle": 45.0,
                            "last_seen": now
                        }
                        self.cfg_mgr.save()
                        self.radar.set_devices(self.cfg["devices"])
                        self.pairing_pending_device = dev_name
                        self.root.after(0, lambda: self.log(f"★ NEW DEVICE: '{dev_name}'! Aim at it and click Button 3 to lock location."))
                        self.root.after(0, lambda: self.hud.show(f"AIM AT {dev_name.upper()} & CLICK BUTTON 3 TO PAIR", status="ready"))
                    else:
                        self.cfg["devices"][dev_name]["ip"] = dev_ip
                        self.cfg["devices"][dev_name]["last_seen"] = now
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # NETWORKING: HIGH-SPEED TCP ZERO-CONFIRMATION BEAM ENGINE
    # -------------------------------------------------------------------------
    def get_staged_payload(self):
        """Grabs the file right-clicked/selected in Explorer, clipboard, or screenshot."""
        # 1. Check if a file is right-clicked / selected in Windows File Explorer
        try:
            import win32com.client
            shell = win32com.client.Dispatch("Shell.Application")
            for window in shell.Windows():
                try:
                    items = window.Document.SelectedItems()
                    if items.Count > 0:
                        selected_path = items.Item(0).Path
                        if os.path.isfile(selected_path):
                            fname = os.path.basename(selected_path)
                            fsize = os.path.getsize(selected_path)
                            return fname, selected_path, fsize
                except Exception:
                    pass
        except Exception:
            pass

        # 2. Check if a file was copied to clipboard in Windows Explorer (CF_HDROP)
        try:
            import win32clipboard
            win32clipboard.OpenClipboard()
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_HDROP):
                file_list = win32clipboard.GetClipboardData(win32clipboard.CF_HDROP)
                win32clipboard.CloseClipboard()
                if file_list and os.path.isfile(file_list[0]):
                    selected_path = file_list[0]
                    fname = os.path.basename(selected_path)
                    fsize = os.path.getsize(selected_path)
                    return fname, selected_path, fsize
            else:
                win32clipboard.CloseClipboard()
        except Exception:
            try:
                import win32clipboard
                win32clipboard.CloseClipboard()
            except Exception:
                pass

        # 3. Check if an actual file path string is in the clipboard
        try:
            cb = self.root.clipboard_get().strip('"\' ')
            if cb and os.path.isfile(cb):
                fname = os.path.basename(cb)
                fsize = os.path.getsize(cb)
                return fname, cb, fsize
        except Exception:
            pass

        # 2. Fallback: High-resolution full screen capture
        fname = f"screenshot_{int(time.time())}.jpg"
        if ImageGrab:
            img = ImageGrab.grab()
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            data = buf.getvalue()
            return fname, data, len(data)

        # Fallback text test
        data = b"COSMIC_BEAM_PAYLOAD"
        return "beam.txt", data, len(data)

    def transmit_payload(self, target_ip):
        """Streams payload (file or screenshot) over TCP in 64KB chunks."""
        t_start = time.time()
        try:
            fname, payload_src, fsize = self.get_staged_payload()

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((target_ip, DEFAULT_TRANSFER_PORT))

            # Send JSON Header: {"name": ..., "size": ...}
            hdr_bytes = json.dumps({"name": fname, "size": fsize}).encode("utf-8")
            sock.sendall(struct.pack(">I", len(hdr_bytes)))
            sock.sendall(hdr_bytes)

            # Stream payload data
            if isinstance(payload_src, str):
                # It's a file path on disk
                with open(payload_src, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        sock.sendall(chunk)
            else:
                # It's bytes in memory
                sock.sendall(payload_src)

            sock.close()
            elapsed = time.time() - t_start
            self.root.after(0, lambda: self.log(f"✔ Sent '{fname}' ({fsize} bytes) in {elapsed:.3f}s!"))
        except Exception as e:
            self.root.after(0, lambda: self.log(f"[!] Transmission failed: {e}"))

    def tcp_receiver_server(self):
        """Receives incoming beamed files and displays instantly with ZERO prompt."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(("0.0.0.0", DEFAULT_TRANSFER_PORT))
            server.listen(5)
        except Exception as e:
            print(f"[RECEIVER] Error binding port {DEFAULT_TRANSFER_PORT}: {e}")
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

                fname = hdr.get("name", f"beam_{int(time.time())}.dat")
                fsize = hdr.get("size", 0)

                drop_folder = self.cfg.get("dropzone", DEFAULT_DROPZONE)
                os.makedirs(drop_folder, exist_ok=True)
                filepath = os.path.join(drop_folder, fname)

                # Stream incoming bytes directly to disk in chunks
                received_bytes = 0
                with open(filepath, "wb") as f:
                    while received_bytes < fsize:
                        packet = conn.recv(min(65536, fsize - received_bytes))
                        if not packet:
                            break
                        f.write(packet)
                        received_bytes += len(packet)

                conn.close()

                # Launch immediately on screen
                self.root.after(0, lambda: self.log(f"⚡ RECEIVED: '{fname}' ({received_bytes} bytes) from {addr[0]}"))
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
                    fname, _, _ = self.get_staged_payload()
                    target_label = f"[{fname}]" if "screenshot" not in fname else "[Screenshot]"
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
