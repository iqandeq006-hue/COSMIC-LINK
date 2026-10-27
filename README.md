# 🌌 COSMIC LINK & COSMIC AIR MOUSE (STARK EDITION)

> **Iron Man–inspired spatial file transfer and cross-device control using an ESP32 Air Mouse and local Wi-Fi beaming.**

Hold a physical button on your Air Mouse at your main screen, turn your arm toward any nearby laptop, and release: your active file or screenshot beams wirelessly over your local network in **under 0.3 seconds**—instantly launching full-screen on the target device with **zero confirmation popups** and **zero manual IP typing**.

---

## ⚡ Key Features

1. **Tactical Gaming Radar HUD (`cosmic.py`)**:
   - 360° circular tactical radar displaying nearby laptops as glowing blips.
   - Real-time reticle tracking your Air Mouse's horizontal heading (Yaw).
   - **Gesture Point & Click to Pair**: When a new laptop is discovered, point at it and click Button 3 to lock its radar position without typing angles.

2. **Floating Desktop HUD Overlay**:
   - Translucent top-level HUD pill that only appears during spatial holding:
     `[⚡ READY TO SEND]` $\to$ `[🎯 TARGET LOCKED: LAPTOP B]` $\to$ `[✔ SENT!]`.

3. **Zero-Confirmation Instant Screen Renderer (Bidirectional)**:
   - Both sender and receiver can seamlessly beam to each other.
   - Automatically creates and manages the `CosmicDropZone` directory.
   - Directly executes `os.startfile()` to launch received media full-screen immediately.

4. **Dual-Laptop Bluetooth Profile Switching**:
   - Short-click Button 3 to switch between **Slot 1 (`COSMIC AIRMOUSE-A`)** and **Slot 2 (`COSMIC AIRMOUSE-B`)**.
   - Dynamically re-advertises via `applyProfileSlot()` without compiler errors.

5. **Private Pairing Key (`COSMIC-8492`)**:
   - Automatic UDP discovery is cryptographically signed with your private key.
   - Blocks strangers and prevents unauthorized drops on shared/public Wi-Fi.

6. **Multi-Function "Stark" Button (ESP32)**:
   - **Hold (>400ms)**: Spatial Grab Mode (Triggers beam overlay).
   - **Double-Click (<350ms)**: Instant Re-center Forward ($0^\circ$).
   - **Short Click (<400ms)**: Toggles Bluetooth Profile (Slot 1 $\leftrightarrow$ Slot 2).

7. **Live Sensitivity & Smoothing Controls (No Recompiling!)**:
   - On-the-fly tuning via sliders in the desktop app.
   - Saved directly to ESP32 Flash memory (`<Preferences.h>`).

---

## 🛠️ Hardware Requirements & Pinout (Standard ESP32 Dev Module)

### Components:
- **ESP32** (Standard Dual-Core DevKit / WROOM, **not** C3)
- **MPU6050** (6-Axis Gyroscope & Accelerometer)
- **3x Tactile Push Buttons** (Left Click, Right Click, Stark Button)
- Jumper wires & breadboard / custom PCB

### Pin Configuration:
| Component | ESP32 GPIO Pin | Description |
| :--- | :--- | :--- |
| **MPU6050 SDA** | `GPIO 21` | I2C Data |
| **MPU6050 SCL** | `GPIO 22` | I2C Clock |
| **Left Button** | `GPIO 18` | Left Click / Scroll Down |
| **Right Button** | `GPIO 19` | Right Click / Scroll Up |
| **Stark Button** | `GPIO 23` | Spatial Grab, Recenter, Profile Switch |
| **VCC & GND** | `3.3V` & `GND` | Power Supply |

---

## 🚀 Getting Started

### 1. Flash the ESP32 Firmware
1. Open [`ESP32-AIR-MOUSE/ESP32-AIR-MOUSE.ino`](file:///c:/Users/iqand/Downloads/COMET-AIR-MOUSE-main/ESP32-AIR-MOUSE/ESP32-AIR-MOUSE.ino) in Arduino IDE.
2. Select board: **`ESP32 Dev Module`** under `Tools > Board > esp32`.
3. Install required libraries if prompted (`MPU6050_tockn`, `HijelHID_BLEMouse`).
4. Click **Upload**.

### 2. Pair Air Mouse via Bluetooth
- In Windows Bluetooth settings on Laptop A, add device and select **`COSMIC AIRMOUSE-A`**.
- To pair with Laptop B, short-click Button 3 to switch to **`COSMIC AIRMOUSE-B`** and pair on Laptop B.

### 3. Launch the Desktop App on Both Laptops
Ensure both laptops are on the same Wi-Fi network and run:
```bash
python cosmic.py
```

### 4. Point & Click Pairing
1. When Laptop B starts the app, Laptop A prompts:
   `AIM AT LAPTOP B & CLICK BUTTON 3 TO PAIR`.
2. Point your Air Mouse directly at physical Laptop B and click **Button 3**.
3. Laptop B's blip is now locked at that exact angle on your tactical radar.

### 5. Beam Across Devices (The Tony Stark Workflow)
1. **Right-click any file** in Windows Explorer (or have a file copied/screenshot).
2. **Press & Hold Button 3** $\to$ `[⚡ READY TO SEND [filename]]`.
3. **Turn your arm toward Laptop B** $\to$ `[🎯 TARGET LOCKED: LAPTOP B]`.
4. **Release Button 3** $\to$ The file streams over Wi-Fi in under 0.3s and opens full-screen on Laptop B!

---

## 📁 Repository Structure

```
├── cosmic.py                 # Main Desktop App (Radar HUD, Floating Overlay & Beam Engine)
├── ESP32-AIR-MOUSE/
│   └── ESP32-AIR-MOUSE.ino   # Standard ESP32 Firmware (Button 3, Flash Preferences, BLE HID)
├── docs/
│   └── setup_guide.md        # Detailed step-by-step setup and testing guide
├── README.md                 # Complete documentation and setup guide
├── LICENSE                   # Open-source license
└── .gitignore                # Git ignore rules
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
