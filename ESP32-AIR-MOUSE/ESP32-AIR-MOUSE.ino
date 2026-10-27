/*
 * =============================================================================
 * COSMIC AIR MOUSE - STARK EDITION (Standard Dual-Core ESP32)
 * For use with COSMIC LINK Desktop App
 * =============================================================================
 * Features:
 * - 6-Axis MPU6050 Motion tracking (Gyro + Accel).
 * - Button 1 (GPIO 18): Left Click / Scroll Down on hold.
 * - Button 2 (GPIO 19): Right Click / Scroll Up on hold.
 * - Button 3 (GPIO 23) - Multi-Function "Stark" Button:
 *     * Click (<400ms): Switch Bluetooth Profile (Slot 1 <-> Slot 2).
 *     * Double-Click (<350ms): Quick Recenter Forward (0°).
 *     * Hold (>400ms): Spatial Grab Mode (Triggers Cosmic Link Beam).
 * - Live Sensitivity Tuning:
 *     * Sensitivity & Smoothing stored in ESP32 Flash (<Preferences.h>).
 *     * Adjustable on-the-fly via Serial/BLE without recompiling!
 *
 * Pinout (Standard ESP32 WROOM / DevKit):
 * - MPU6050 SDA  -> GPIO 21
 * - MPU6050 SCL  -> GPIO 22
 * - Left Button  -> GPIO 18
 * - Right Button -> GPIO 19
 * - Third Button -> GPIO 23
 * =============================================================================
 */

#include <Wire.h>
#include <MPU6050_tockn.h>
#include <HijelHID_BLEMouse.h>
#include <Preferences.h>
#include <esp_system.h>
#if __has_include(<esp_mac.h>)
  #include <esp_mac.h>
#endif

// -----------------------------------------------------------------------------
// HARDWARE PINS
// -----------------------------------------------------------------------------
#define SDA_PIN 21
#define SCL_PIN 22

#define LEFT_BUTTON   18
#define RIGHT_BUTTON  19
#define STARK_BUTTON  23  // Button 3 for Stark Beaming & Profile Switching

// -----------------------------------------------------------------------------
// PERSISTENT PREFERENCES (Internal Flash Memory)
// -----------------------------------------------------------------------------
Preferences prefs;

float sensitivity = 0.20;
float smoothing   = 0.82;
int   deadzone    = 1;
int   activeSlot  = 1;  // 1 = Laptop A, 2 = Laptop B

// -----------------------------------------------------------------------------
// BLE MOUSE INSTANCE (Dynamic Pointer for Profile Switching)
// -----------------------------------------------------------------------------
HijelBLEMouse* mouse = nullptr;

MPU6050 mpu6050(Wire);

// Filter & Gyro variables
float gyroBiasZ = 0;
float gyroBiasY = 0;
float fX = 0;
float fY = 0;

// Button State Tracking
unsigned long leftPressStart    = 0;
unsigned long rightPressStart   = 0;
unsigned long starkPressStart   = 0;
unsigned long lastStarkRelease  = 0;
bool pendingStarkClick          = false;

bool leftHeld  = false;
bool rightHeld = false;
bool starkHeld = false;
bool isFrozen  = false;  // Frozen during desktop app tuning

const unsigned long clickThreshold = 180;
const unsigned long holdThreshold  = 400;

unsigned long lastScrollTime = 0;
const unsigned long scrollDelay = 120;


// =============================================================================
// PREFERENCES: LOAD & SAVE SETTINGS
// =============================================================================
void loadPreferences() {
  prefs.begin("airmouse", false);
  sensitivity = prefs.getFloat("sens", 0.20);
  smoothing   = prefs.getFloat("smooth", 0.82);
  deadzone    = prefs.getInt("dead", 1);
  activeSlot  = prefs.getInt("slot", 1);
  prefs.end();

  if (activeSlot != 1 && activeSlot != 2) {
    activeSlot = 1;
  }

  Serial.println("\n[CONFIG] Loaded settings from Flash:");
  Serial.printf("  Sensitivity: %.2f | Smoothing: %.2f | Deadzone: %d | Profile Slot: %d\n\n",
                sensitivity, smoothing, deadzone, activeSlot);
}

void saveSetting(const char* key, float val) {
  prefs.begin("airmouse", false);
  prefs.putFloat(key, val);
  prefs.end();
}

void saveSettingInt(const char* key, int val) {
  prefs.begin("airmouse", false);
  prefs.putInt(key, val);
  prefs.end();
}


// =============================================================================
// CALIBRATION
// =============================================================================
void calibrateGyro() {
  Serial.println("========================================");
  Serial.println("  Calibrating Gyro (Keep Still!)");
  Serial.println("========================================");

  float sumZ = 0;
  float sumY = 0;
  const int samples = 400;

  for (int i = 0; i < samples; i++) {
    mpu6050.update();
    sumZ += mpu6050.getGyroZ();
    sumY += mpu6050.getGyroY();
    delay(3);
  }

  gyroBiasZ = sumZ / samples;
  gyroBiasY = sumY / samples;
  Serial.printf("Gyro Biases: Z=%.2f, Y=%.2f\n\n", gyroBiasZ, gyroBiasY);
}


// =============================================================================
// BLE PROFILE MANAGEMENT (Slot 1 <-> Slot 2)
// Re-instantiates mouse dynamically with dedicated MAC address and device name
// so Laptop A and Laptop B are treated as two distinct Bluetooth devices.
// =============================================================================
void applyProfileSlot(int slot) {
  if (mouse != nullptr) {
    mouse->beforeSleep();
    delay(100);
    delete mouse;
    mouse = nullptr;
  }

  const char* devName = (slot == 1) ? "COSMIC AIRMOUSE-A" : "COSMIC AIRMOUSE-B";
  Serial.println("\n----------------------------------------");
  Serial.printf("[BLE] Profile Slot %d Active\n", slot);
  Serial.printf("[BLE] Advertising as \"%s\" (slot %d)\n", devName, slot);
  Serial.println("----------------------------------------");

  mouse = new HijelBLEMouse(devName, "COSMIC", 100, 5, true);
  mouse->setUpdateRate(HIDRate::Hz125);
  mouse->setBatteryLevel(100);
  mouse->setLogLevel(HIDLogLevel::Normal);
  mouse->begin();

  uint8_t curMac[6];
  if (esp_read_mac(curMac, ESP_MAC_BT) == ESP_OK) {
    Serial.printf("[BLE] Active Bluetooth MAC: %02X:%02X:%02X:%02X:%02X:%02X\n\n",
                  curMac[0], curMac[1], curMac[2], curMac[3], curMac[4], curMac[5]);
  }
}

// Switches slot, saves to Flash, and reboots ESP32 cleanly to activate
// the dedicated hardware MAC address for the target laptop.
void switchProfileSlot(int newSlot) {
  Serial.println("\n----------------------------------------");
  Serial.printf("[BLE] Switching to Profile Slot %d...\n", newSlot);
  saveSettingInt("slot", newSlot);

  if (mouse != nullptr) {
    mouse->beforeSleep();
    delay(100);
  }

  Serial.println("[BLE] Restarting ESP32 to activate dedicated hardware MAC address...");
  Serial.println("----------------------------------------\n");
  delay(150);
  ESP.restart();
}


// =============================================================================
// SETUP
// =============================================================================
void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("\n========================================");
  Serial.println("     COMET AIR MOUSE - STARK EDITION    ");
  Serial.println("========================================");

  // 1. Load preferences from flash first
  loadPreferences();

  // 2. Configure unique hardware MAC address for the active profile slot.
  // CRITICAL: Must be called BEFORE BLEDevice::init() / mouse->begin().
  // Slot 1 uses factory base MAC (Laptop A).
  // Slot 2 uses modified base MAC (Laptop B).
  // Because the MAC addresses are different, Laptop A will NOT auto-connect
  // or hijack the connection when Slot 2 is active!
  uint8_t baseMac[6];
  if (esp_efuse_mac_get_default(baseMac) == ESP_OK) {
    if (activeSlot == 2) {
      baseMac[4] ^= 0x02; // Change byte 4 for Slot 2
    }
    esp_base_mac_addr_set(baseMac);
  }

  // Pin Configuration
  pinMode(LEFT_BUTTON,  INPUT_PULLUP);
  pinMode(RIGHT_BUTTON, INPUT_PULLUP);
  pinMode(STARK_BUTTON, INPUT_PULLUP);

  // I2C & MPU6050
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);
  delay(100);

  mpu6050.begin();
  mpu6050.calcGyroOffsets(true);
  calibrateGyro();

  // BLE HID Setup with active profile slot & dedicated MAC
  applyProfileSlot(activeSlot);

  Serial.println("BLE Started. Waiting for connection...");
}


// =============================================================================
// SERIAL LIVE TUNING PARSER
// Allows Comet Link app to change sensitivity without flashing!
// Format: SENS:0.35 or SMOOTH:0.85
// =============================================================================
void checkSerialCommands() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();

    if (line.startsWith("SENS:")) {
      sensitivity = line.substring(5).toFloat();
      saveSetting("sens", sensitivity);
      Serial.printf("[UPDATE] Sensitivity set to %.2f and saved to Flash!\n", sensitivity);
    }
    else if (line.startsWith("SMOOTH:")) {
      smoothing = line.substring(7).toFloat();
      saveSetting("smooth", smoothing);
      Serial.printf("[UPDATE] Smoothing set to %.2f and saved to Flash!\n", smoothing);
    }
    else if (line.startsWith("RECENTER")) {
      fX = 0;
      fY = 0;
      Serial.println("[RECENTER] Recenter forward acknowledged.");
    }
    else if (line.startsWith("FREEZE")) {
      isFrozen = true;
      Serial.println("[FREEZE] Air Mouse movement frozen for desktop tuning.");
    }
    else if (line.startsWith("UNFREEZE")) {
      isFrozen = false;
      Serial.println("[UNFREEZE] Air Mouse unfrozen.");
    }
    else if (line.startsWith("CALIBRATE")) {
      Serial.println("[CALIBRATE] Calibrating Gyro (Keep Still!)...");
      calibrateGyro();
      fX = 0;
      fY = 0;
      isFrozen = false;
      Serial.println("[CALIBRATE_OK] Gyro calibrated and mouse unfrozen!");
    }
    else if (line.startsWith("SLOT:")) {
      int s = line.substring(5).toInt();
      if (s == 1 || s == 2) {
        switchProfileSlot(s);
      }
    }
    else if (line.equalsIgnoreCase("TOGGLE")) {
      switchProfileSlot((activeSlot == 1) ? 2 : 1);
    }
  }
}


// =============================================================================
// MAIN LOOP
// =============================================================================
void loop() {
  checkSerialCommands();

  // If frozen for live desktop tuning, halt all motion and button output
  if (isFrozen) {
    delay(20);
    return;
  }

  mpu6050.update();

  unsigned long now = millis();
  bool paired = (mouse != nullptr) && mouse->isPaired();

  // ---------------------------------------------------------------------------
  // BUTTON 1: LEFT CLICK / SCROLL UP
  // ---------------------------------------------------------------------------
  if (digitalRead(LEFT_BUTTON) == LOW) {
    if (leftPressStart == 0) {
      leftPressStart = now;
      leftHeld = false;
    }
    if (!leftHeld && (now - leftPressStart >= clickThreshold)) {
      leftHeld = true;
    }
    if (leftHeld && paired && (now - lastScrollTime >= scrollDelay)) {
      mouse->addScroll(1);  // Scroll UP
      lastScrollTime = now;
    }
  } else {
    if (leftPressStart != 0) {
      if (!leftHeld && (now - leftPressStart < clickThreshold) && paired) {
        mouse->click(MouseButton::Left, 20);
      }
      leftPressStart = 0;
      leftHeld = false;
    }
  }

  // ---------------------------------------------------------------------------
  // BUTTON 2: RIGHT CLICK / SCROLL DOWN
  // ---------------------------------------------------------------------------
  if (digitalRead(RIGHT_BUTTON) == LOW) {
    if (rightPressStart == 0) {
      rightPressStart = now;
      rightHeld = false;
    }
    if (!rightHeld && (now - rightPressStart >= clickThreshold)) {
      rightHeld = true;
    }
    if (rightHeld && paired && (now - lastScrollTime >= scrollDelay)) {
      mouse->addScroll(-1);  // Scroll DOWN
      lastScrollTime = now;
    }
  } else {
    if (rightPressStart != 0) {
      if (!rightHeld && (now - rightPressStart < clickThreshold) && paired) {
        mouse->click(MouseButton::Right, 20);
      }
      rightPressStart = 0;
      rightHeld = false;
    }
  }

  // ---------------------------------------------------------------------------
  // BUTTON 3: MULTI-FUNCTION "STARK" BUTTON (GPIO 23)
  // Double-Click (<350ms): Recenter Forward (0°)
  // Hold (>400ms): Spatial Grab Mode (Middle Mouse Down for Cosmic Link app)
  // Single-Click: Switch Bluetooth Profile (Slot 1 <-> Slot 2)
  // ---------------------------------------------------------------------------
  if (digitalRead(STARK_BUTTON) == LOW) {
    if (starkPressStart == 0) {
      starkPressStart = now;
      starkHeld = false;
    }
    // Hold Threshold Reached -> Enter Stark Spatial Grab Mode!
    if (!starkHeld && (now - starkPressStart >= holdThreshold)) {
      starkHeld = true;
      pendingStarkClick = false; // Cancel pending click on hold
      if (paired) {
        mouse->press(MouseButton::Middle);  // Signals Cosmic Link overlay
        Serial.println("[STARK] Spatial Grab Active (Middle Mouse DOWN)");
      }
    }
  } else {
    if (starkPressStart != 0) {
      if (starkHeld) {
        // Release from Stark Grab Mode
        if (paired) {
          mouse->release(MouseButton::Middle);
          Serial.println("[STARK] Spatial Grab Released (Beaming Payload!)");
        }
      } else {
        // Button was released before hold threshold -> Check for Double-Click vs Single-Click
        if (pendingStarkClick && (now - lastStarkRelease < 350)) {
          // Double-Click Confirmed!
          Serial.println("[STARK] Double-Click Detected: RECENTER FORWARD!");
          fX = 0;
          fY = 0;
          pendingStarkClick = false;
        } else {
          // First click released: mark pending and wait briefly to see if second click arrives
          pendingStarkClick = true;
          lastStarkRelease = now;
        }
      }
      starkPressStart = 0;
      starkHeld = false;
    }
  }

  // If a single click was released and double-click window expired -> trigger profile switch!
  if (pendingStarkClick && (now - lastStarkRelease >= 350)) {
    pendingStarkClick = false;
    int targetSlot = (activeSlot == 1) ? 2 : 1;
    switchProfileSlot(targetSlot);
  }

  // ---------------------------------------------------------------------------
  // MOTION TRACKING & CURSOR MOVEMENT
  // ---------------------------------------------------------------------------
  if (!paired) {
    delay(5);
    return;
  }

  float gyroX = -(mpu6050.getGyroZ() - gyroBiasZ);
  float gyroY =   mpu6050.getGyroY() - gyroBiasY;

  // Smoothing
  fX = fX * smoothing + gyroX * (1.0 - smoothing);
  fY = fY * smoothing + gyroY * (1.0 - smoothing);

  // Sensitivity
  float moveX = fX * sensitivity;
  float moveY = fY * sensitivity;

  // Deadzone filter
  if (fabs(moveX) < deadzone) moveX = 0;
  if (fabs(moveY) < deadzone) moveY = 0;

  int mouseX = (int)moveX;
  int mouseY = (int)moveY;

  if (mouseX != 0 || mouseY != 0) {
    mouse->move(mouseX, mouseY);
  }

  delay(5);
}
