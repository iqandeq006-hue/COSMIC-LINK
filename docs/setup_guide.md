# 📚 Cosmic Air Mouse & Cosmic Link - Setup & Testing Guide

## 1. Overview & Hardware Architecture

- **ESP32 Board**: Standard **ESP32 Dev Module** (Dual-Core ESP32 WROOM-32, **NOT** ESP32-C3).
- **Communication Flow**:
  1. **ESP32 Air Mouse ↔ Active Laptop**: Communicates purely via **Bluetooth Low Energy (BLE HID)** as a wireless mouse. (No Wi-Fi connection is required on the ESP32 board).
  2. **Laptop A ↔ Laptop B**: Communicates over your local **2.4 GHz / 5 GHz Wi-Fi network** via `cosmic.py` (UDP 5052 for beacon discovery, TCP 5051 for instant high-speed file transfer).

---

## 2. Hardware Wiring (Standard ESP32 Dev Module)

| Component | Pin | ESP32 GPIO | Description |
| :--- | :--- | :--- | :--- |
| **MPU6050** | SDA | **GPIO 21** | I2C Data |
| **MPU6050** | SCL | **GPIO 22** | I2C Clock |
| **MPU6050** | VCC / GND | **3.3V / GND** | Power |
| **Button 1** | Terminal | **GPIO 18** | Left Click / Scroll Up (Internal Pull-Up) |
| **Button 2** | Terminal | **GPIO 19** | Right Click / Scroll Down (Internal Pull-Up) |
| **Button 3** | Terminal | **GPIO 23** | Multi-function "Stark" Button (Internal Pull-Up) |

*Note: All buttons connect between the designated GPIO pin and GND.*

---

## 3. Step-by-Step Setup & Testing Guide

### 3.1 Prerequisites

| Tool | Recommended Version |
| :--- | :--- |
| **Arduino IDE** | 2.3+ |
| **ESP32 Board Package (`esp32` by Espressif)** | 2.0.12+ (or 3.x) |
| **Libraries** | `MPU6050_tockn` by tockn, `HijelHID_BLEMouse` (or BleMouse) |
| **Python** | 3.10+ (with `pynput`, `Pillow`, `pywin32`) |
| **Wi-Fi Network** | Any local Wi-Fi router that both laptops can join |

---

### 3.2 Flash the Firmware

1. Open [`ESP32-AIR-MOUSE.ino`](file:///c:/Users/iqand/Downloads/COMET-AIR-MOUSE-main/ESP32-AIR-MOUSE/ESP32-AIR-MOUSE.ino) in **Arduino IDE**.
2. Go to **Tools > Board > esp32** and select:
   👉 **`ESP32 Dev Module`** *(Do NOT select ESP32-C3 Dev Module!)*
3. Verify board settings:
   - **Upload Speed**: `921600` (or `115200`)
   - **Flash Frequency**: `80MHz`
   - **Flash Mode**: `QIO`
   - **Partition Scheme**: `Default 4MB with spiffs`
   - **Core Debug Level**: `None`
4. Click **Verify (Checkmark)** – it compiles cleanly without any `'setDeviceName' was not declared in this scope` error because dynamic object re-creation is implemented in `applyProfileSlot()`.
5. Connect your ESP32 via USB and click **Upload**.
6. Open **Arduino IDE Serial Monitor** (`Ctrl + Shift + M` or `Tools > Serial Monitor`) and set baud rate to **`115200`**.
   - Keep the Air Mouse completely flat and still for 2 seconds while gyro calibrates.
   - You will see:
     ```text
     [CONFIG] Loaded settings from Flash:
       Sensitivity: 0.20 | Smoothing: 0.82 | Deadzone: 1 | Profile Slot: 1
     [BLE] Profile Slot 1 Active
     [BLE] Advertising as "COSMIC AIRMOUSE-A" (slot 1)
     BLE Started. Waiting for connection...
     ```

---

### 3.3 Run the Desktop Side (`cosmic.py`)

Run `cosmic.py` on both laptops connected to the same Wi-Fi:

```powershell
# In PowerShell:
cd C:\Users\iqand\Downloads\COMET-AIR-MOUSE-main
python cosmic.py
```

- When the application starts, you will see your **Laptop's Wi-Fi IP** in the header:
  `Local IP: 192.168.1.xxx | Key: COSMIC-8492`
- When both laptops run `cosmic.py`, they discover each other on the Wi-Fi network:
  1. An interactive dialog prompts: `"Device detected. Do you want to accept pairing with Key: COSMIC-8492?"`.
  2. Click **Yes** on both laptops to establish mutual trust (`[TRUSTED: ✔]`).
  3. On **Laptop A** (with Air Mouse), aim physically at Laptop B and click **`📍 Point & Sync to Peer`**.
  4. **Automatic Spatial Synchronization**: Laptop A streams its bearing to Laptop B over Wi-Fi. Laptop B automatically computes the reciprocal angle (e.g. if B is at $+45^\circ$, A is placed at $315^\circ$ on B's radar!). Neither laptop requires manual angle typing!

---

### 3.4 Pair with Laptop A (Profile Slot 1)

1. On **Laptop A**, open Windows **Settings > Bluetooth & devices**.
2. Click **Add device > Bluetooth**.
3. Scan for devices → Select **`COSMIC AIRMOUSE-A`**.
4. Once paired:
   - Move the Air Mouse: cursor moves smoothly across the screen.
   - The Serial Monitor in Arduino IDE outputs:
     `BLE MOUSE CONNECTED!`

---

### 3.5 Switch to Laptop B (Profile Slot 2)

1. **Short-click Button 3** (GPIO 23) on the Air Mouse (quick press < 400 ms).
2. The ESP32 re-initializes advertising under Profile 2.
3. In **Arduino IDE Serial Monitor**, you will see:
   ```text
   [BLE] Short Click: Switching Bluetooth Profile Slot...
   [BLE] Profile Slot 2 Active
   [BLE] Advertising as "COSMIC AIRMOUSE-B" (slot 2)
   ```
4. On **Laptop B**, open **Settings > Bluetooth & devices > Add device**.
5. Select and pair with **`COSMIC AIRMOUSE-B`**.
6. Now both laptops remember their respective Bluetooth profiles:
   - **Short-click Button 3** at any time to toggle between controlling **Laptop A** and **Laptop B**!

---

### 3.6 Using the Spatial File "Beam" Feature

To beam a file from the active laptop to the other laptop:

1. **Right-click the target file** in Windows File Explorer (this selects/stages the file).
2. **Press and hold Button 3** (GPIO 23) on the Air Mouse:
   - Floating HUD pill appears: `⚡ READY TO SEND [filename.ext]`.
3. **Point the Air Mouse** in physical space towards the target laptop:
   - The radar reticle moves in real-time tracking your aim.
   - When pointing within ~25° of the other laptop's blip on the radar, the HUD turns green:
     `🎯 TARGET LOCKED: [LAPTOP_NAME] (Release to Beam)`.
4. **Release Button 3**:
   - `cosmic.py` streams the file directly over high-speed TCP.
   - The HUD confirms: `✔ SENT TO [LAPTOP_NAME]!`.
   - The receiving laptop instantly saves the file to its `Documents\CosmicDropZone` folder and opens it full screen automatically with zero prompts!

---

### 3.7 Air Mouse Live Tuning (Freeze & Calibrate)

You can tune the mouse cursor sensitivity and motion smoothing on-the-fly and write it directly to ESP32 Flash memory:

1. Plug the ESP32 into a USB port on your laptop.
2. In `cosmic.py`, choose the detected **COM Port** in the Hardware Tuning section and click **Connect**.
3. Click **`❄️ FREEZE AIR MOUSE FOR TUNING`**:
   - The ESP32 immediately ignores gyro movements and button clicks so the cursor freezes in place.
   - This prevents erratic mouse movement while you adjust sliders on your screen.
4. Adjust the **Sensitivity** and **Smoothing** sliders to your desired values.
5. Click **`🚀 CONFIRM, FLASH & CALIBRATE GYRO`**:
   - A confirmation prompt will ask to proceed.
   - Keep the Air Mouse completely flat and still on your desk for 2 seconds.
   - Cosmic Link writes the new settings to the ESP32's flash (`<Preferences.h>`), recalculates gyro calibration offsets, and automatically unfreezes the mouse!
