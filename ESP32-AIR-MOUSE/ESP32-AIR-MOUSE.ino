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
unsigned long leftPressStart  = 0;
unsigned long rightPressStart = 0;
unsigned long starkPressStart = 0;
unsigned long lastStarkClick  = 0;

bool leftHeld  = false;
bool rightHeld = false;
bool starkHeld = false;

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

  Serial.println("\n[CONFIG] Loaded settings from Flash:");
  Serial.printf("  Sensitivity: %.2f | Smoothing: %.2f | Deadzone: %d | Profile Slot: %d\n\n",
                sensitivity, smoothing, deadzone, activeSlot);
}

void saveSetting(const char* key, float val) {
  prefs.begin("airmouse", false);
  prefs.putFloat(key, val);
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
// Re-instantiates mouse dynamically to avoid 'setDeviceName' compiler errors
// on all versions of HijelBLEMouse / BleMouse.
// =============================================================================
void applyProfileSlot(int slot) {
  if (mouse != nullptr) {
    mouse->beforeSleep();
    delay(250);
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

  // Load preferences from flash
  loadPreferences();

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

  // BLE HID Setup with active profile slot
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
  }
}


// =============================================================================
// MAIN LOOP
// =============================================================================
void loop() {
  checkSerialCommands();
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
  // Double-Click: Recenter
  // Hold: Spatial Grab Mode (Middle Mouse Down for Comet Link app)
  // Short Click: Switch Bluetooth Profile (Slot 1 <-> Slot 2)
  // ---------------------------------------------------------------------------
  if (digitalRead(STARK_BUTTON) == LOW) {
    if (starkPressStart == 0) {
      starkPressStart = now;
      starkHeld = false;
    }
    // Hold Threshold Reached -> Enter Stark Spatial Grab Mode!
    if (!starkHeld && (now - starkPressStart >= holdThreshold)) {
      starkHeld = true;
      if (paired) {
        mouse->press(MouseButton::Middle);  // Signals Comet Link overlay
        Serial.println("[STARK] Spatial Grab Active (Middle Mouse DOWN)");
      }
    }
  } else {
    if (starkPressStart != 0) {
      unsigned long duration = now - starkPressStart;

      if (starkHeld) {
        // Release from Stark Grab Mode
        if (paired) {
          mouse->release(MouseButton::Middle);
          Serial.println("[STARK] Spatial Grab Released (Beaming Payload!)");
        }
      } else {
        // Check for Double-Click (Recenter Forward)
        if (now - lastStarkClick < 350) {
          Serial.println("[STARK] Double-Click Detected: RECENTER FORWARD!");
          fX = 0;
          fY = 0;
          lastStarkClick = 0;
        } else {
          lastStarkClick = now;
          // Short Click: Switch Bluetooth Profile
          Serial.println("[BLE] Short Click: Switching Bluetooth Profile Slot...");
          activeSlot = (activeSlot == 1) ? 2 : 1;
          saveSetting("slot", (float)activeSlot);
          applyProfileSlot(activeSlot);
        }
      }
      starkPressStart = 0;
      starkHeld = false;
    }
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
