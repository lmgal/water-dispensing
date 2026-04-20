/*
 * Water Dispensing Station — ESP8266 Firmware
 * Team 18 — CS 145
 *
 * Hardware:
 *   - ESP8266 (NodeMCU / D1 Mini)
 *   - GM861S QR Code Scanner (UART)
 *   - Push Button (GPIO)
 *   - Relay Module (GPIO) → Water Pump
 *   - Flow Sensor (GPIO interrupt)
 *   - LED (GPIO) — Green/Red status
 *   - Buzzer (GPIO)
 */

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>
#include <SoftwareSerial.h>
#include <ArduinoJson.h>

// === WiFi Configuration ===
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// === Server Configuration ===
const char* SERVER_URL = "http://YOUR_SERVER_IP:8000";
const int   STATION_ID = 1;

// === Pin Definitions ===
#define QR_RX_PIN      D5   // GM861S TX → ESP RX
#define QR_TX_PIN      D6   // GM861S RX → ESP TX
#define BUTTON_PIN     D2   // Push button (active LOW with pullup)
#define RELAY_PIN      D1   // Relay module (active HIGH)
#define FLOW_PIN       D7   // Flow sensor (pulse input)
#define LED_GREEN_PIN  D3   // Green LED
#define LED_RED_PIN    D4   // Red LED
#define BUZZER_PIN     D8   // Buzzer

// === Flow Sensor Calibration ===
// Pulses per liter (adjust for your sensor)
const float PULSES_PER_ML = 0.45;

// === State Machine ===
enum State {
  STATE_IDLE,
  STATE_SCANNING,
  STATE_VERIFYING,
  STATE_AUTHORIZED,
  STATE_DISPENSING,
  STATE_ERROR
};

State currentState = STATE_IDLE;

// === Global Variables ===
SoftwareSerial qrSerial(QR_RX_PIN, QR_TX_PIN);
WiFiClient wifiClient;

volatile unsigned long flowPulseCount = 0;
float totalVolumeML = 0;
float remainingML = 0;
int authorizedResidentId = -1;

unsigned long lastHeartbeat = 0;
unsigned long lastButtonCheck = 0;
unsigned long dispensingStartTime = 0;

const unsigned long HEARTBEAT_INTERVAL = 30000;  // 30 seconds
const unsigned long BUTTON_DEBOUNCE = 200;        // 200ms

String qrBuffer = "";

// === Flow Sensor ISR ===
IRAM_ATTR void flowPulseISR() {
  flowPulseCount++;
}

// === Setup ===
void setup() {
  Serial.begin(115200);
  qrSerial.begin(9600);

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(FLOW_PIN, INPUT_PULLUP);
  pinMode(LED_GREEN_PIN, OUTPUT);
  pinMode(LED_RED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);

  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(LED_GREEN_PIN, LOW);
  digitalWrite(LED_RED_PIN, LOW);
  digitalWrite(BUZZER_PIN, LOW);

  attachInterrupt(digitalPinToInterrupt(FLOW_PIN), flowPulseISR, RISING);

  // Connect to WiFi
  Serial.printf("Connecting to %s", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nConnected! IP: %s\n", WiFi.localIP().toString().c_str());

  indicateReady();
}

// === Main Loop ===
void loop() {
  // Heartbeat
  if (millis() - lastHeartbeat >= HEARTBEAT_INTERVAL) {
    sendHeartbeat();
    lastHeartbeat = millis();
  }

  switch (currentState) {
    case STATE_IDLE:
      readQRScanner();
      break;

    case STATE_AUTHORIZED:
      checkButton();
      // Timeout after 30s of no button press
      if (millis() - dispensingStartTime > 30000) {
        Serial.println("Authorization timeout.");
        resetToIdle();
      }
      break;

    case STATE_DISPENSING:
      updateDispensing();
      checkButton();
      break;

    default:
      break;
  }
}

// === QR Scanner ===
void readQRScanner() {
  while (qrSerial.available()) {
    char c = qrSerial.read();
    if (c == '\n' || c == '\r') {
      if (qrBuffer.length() > 0) {
        Serial.printf("QR Scanned: %s\n", qrBuffer.c_str());
        verifyQR(qrBuffer);
        qrBuffer = "";
      }
    } else {
      qrBuffer += c;
    }
  }
}

// === Verify QR via Server ===
void verifyQR(String qrData) {
  currentState = STATE_VERIFYING;
  indicateProcessing();

  HTTPClient http;
  String url = String(SERVER_URL) + "/api/auth";
  http.begin(wifiClient, url);
  http.addHeader("Content-Type", "application/json");

  JsonDocument doc;
  doc["station_id"] = STATION_ID;
  doc["qr_data"] = qrData;

  String body;
  serializeJson(doc, body);

  int httpCode = http.POST(body);

  if (httpCode == 200) {
    String response = http.getString();
    JsonDocument resDoc;
    deserializeJson(resDoc, response);

    bool authorized = resDoc["authorized"];
    if (authorized) {
      authorizedResidentId = resDoc["resident_id"];
      remainingML = resDoc["remaining_ml"];
      Serial.printf("Authorized! Resident %d, remaining %.0f mL\n", authorizedResidentId, remainingML);
      currentState = STATE_AUTHORIZED;
      dispensingStartTime = millis();
      indicateAuthorized();
    } else {
      const char* reason = resDoc["reason"];
      Serial.printf("Denied: %s\n", reason);
      indicateDenied();
      resetToIdle();
    }
  } else {
    Serial.printf("HTTP Error: %d\n", httpCode);
    indicateError();
    resetToIdle();
  }

  http.end();
}

// === Button Handling ===
void checkButton() {
  if (millis() - lastButtonCheck < BUTTON_DEBOUNCE) return;
  lastButtonCheck = millis();

  bool pressed = (digitalRead(BUTTON_PIN) == LOW);

  if (currentState == STATE_AUTHORIZED && pressed) {
    startDispensing();
  } else if (currentState == STATE_DISPENSING && !pressed) {
    stopDispensing();
  }
}

// === Dispensing Control ===
void startDispensing() {
  Serial.println("Starting dispensing...");
  currentState = STATE_DISPENSING;
  flowPulseCount = 0;
  totalVolumeML = 0;
  dispensingStartTime = millis();

  digitalWrite(RELAY_PIN, HIGH);  // Turn on pump
  indicateDispensing();
}

void updateDispensing() {
  // Calculate volume from flow sensor pulses
  noInterrupts();
  unsigned long pulses = flowPulseCount;
  interrupts();

  totalVolumeML = pulses / PULSES_PER_ML;

  // Check if we've reached the limit
  if (totalVolumeML >= remainingML) {
    Serial.println("Allocation limit reached.");
    stopDispensing();
  }
}

void stopDispensing() {
  Serial.printf("Stopping. Dispensed: %.0f mL\n", totalVolumeML);
  digitalWrite(RELAY_PIN, LOW);  // Turn off pump

  // Report to server
  reportDispense(totalVolumeML);

  resetToIdle();
}

// === Report Dispense to Server ===
void reportDispense(float volumeML) {
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/dispense";
  http.begin(wifiClient, url);
  http.addHeader("Content-Type", "application/json");

  JsonDocument doc;
  doc["station_id"] = STATION_ID;
  doc["resident_id"] = authorizedResidentId;
  doc["volume_ml"] = volumeML;

  String body;
  serializeJson(doc, body);

  int httpCode = http.POST(body);

  if (httpCode == 200) {
    String response = http.getString();
    JsonDocument resDoc;
    deserializeJson(resDoc, response);
    float newRemaining = resDoc["remaining_ml"];
    Serial.printf("Recorded. Remaining today: %.0f mL\n", newRemaining);
  } else {
    Serial.printf("Report failed: %d\n", httpCode);
  }

  http.end();
}

// === Heartbeat ===
void sendHeartbeat() {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  String url = String(SERVER_URL) + "/api/station/heartbeat";
  http.begin(wifiClient, url);
  http.addHeader("Content-Type", "application/json");

  JsonDocument doc;
  doc["station_id"] = STATION_ID;
  doc["water_level"] = 75;  // TODO: read from actual sensor

  String body;
  serializeJson(doc, body);

  int httpCode = http.POST(body);
  http.end();

  if (httpCode == 200) {
    Serial.println("Heartbeat sent.");
  }
}

// === Indicator Functions ===
void indicateReady() {
  digitalWrite(LED_GREEN_PIN, HIGH);
  digitalWrite(LED_RED_PIN, LOW);
  digitalWrite(BUZZER_PIN, LOW);
}

void indicateProcessing() {
  digitalWrite(LED_GREEN_PIN, HIGH);
  digitalWrite(LED_RED_PIN, HIGH);
}

void indicateAuthorized() {
  digitalWrite(LED_GREEN_PIN, HIGH);
  digitalWrite(LED_RED_PIN, LOW);
  // Short beep
  digitalWrite(BUZZER_PIN, HIGH);
  delay(100);
  digitalWrite(BUZZER_PIN, LOW);
}

void indicateDenied() {
  digitalWrite(LED_GREEN_PIN, LOW);
  digitalWrite(LED_RED_PIN, HIGH);
  // Three short beeps
  for (int i = 0; i < 3; i++) {
    digitalWrite(BUZZER_PIN, HIGH);
    delay(150);
    digitalWrite(BUZZER_PIN, LOW);
    delay(100);
  }
}

void indicateDispensing() {
  digitalWrite(LED_GREEN_PIN, HIGH);
  digitalWrite(LED_RED_PIN, LOW);
}

void indicateError() {
  digitalWrite(LED_GREEN_PIN, LOW);
  digitalWrite(LED_RED_PIN, HIGH);
  // Long beep
  digitalWrite(BUZZER_PIN, HIGH);
  delay(500);
  digitalWrite(BUZZER_PIN, LOW);
}

void resetToIdle() {
  currentState = STATE_IDLE;
  authorizedResidentId = -1;
  remainingML = 0;
  totalVolumeML = 0;
  flowPulseCount = 0;
  indicateReady();
}
