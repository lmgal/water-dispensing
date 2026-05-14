#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>
#include <SoftwareSerial.h>
#include <ArduinoJson.h>

#define QR_RX_PIN   D2
#define QR_TX_PIN   D6
#define BUTTON_PIN  D1
#define BUZZER_PIN  D5
#define LED_PIN     D7
#define PUMP_PIN    D3

const char* AP_SSID      = "Station-1-Setup";
const int   STATION_ID   = 1;
const char* API_KEY      = "5aac441c277094868c0d2d02c610b2e6ba3b11cf70074a22ce63a4cf3b03695a";
const char* SERVER_URL   = "http://178.128.99.170:8000";
const float FLOW_RATE_ML_S    = 20.0f;
const unsigned long HEARTBEAT_INTERVAL_MS = 30000;
const unsigned long AUTH_TIMEOUT_MS       = 30000;
const unsigned long INVALID_BEEP_MS       = 1000;
const unsigned long DEPLETED_BEEP_MS      = 1000;
const unsigned long BUTTON_DEBOUNCE_MS    = 30;
const unsigned long SCAN_GAP_MS           = 300;

enum State { PROVISIONING, IDLE, AUTHORIZED, DISPENSING };
State state = PROVISIONING;

SoftwareSerial scanner(QR_RX_PIN, QR_TX_PIN);
ESP8266WebServer server(80);
WiFiClient wifiClient;

bool wifiReady = false;
bool tryConnect = false;
String pendingSSID, pendingPW;

int   residentId = -1;
float remainingMl = 0;
unsigned long authStartMs = 0;
unsigned long pumpStartMs = 0;
unsigned long beepUntilMs = 0;

int  lastBtnReading = HIGH;
int  btnState = HIGH;
unsigned long lastBtnChange = 0;

unsigned long lastHeartbeatMs = 0;
unsigned long lastAliveMs = 0;
const unsigned long ALIVE_INTERVAL_MS = 5000;

const char* stateName(State s) {
  switch (s) {
    case PROVISIONING: return "PROVISIONING";
    case IDLE:         return "IDLE";
    case AUTHORIZED:   return "AUTHORIZED";
    case DISPENSING:   return "DISPENSING";
  }
  return "?";
}

void setState(State s) {
  if (state != s) {
    Serial.printf("[state] %s -> %s\n", stateName(state), stateName(s));
    state = s;
  }
}

const char INDEX_HTML[] PROGMEM = R"=====(
<!DOCTYPE html>
<html><head><title>Station 1 Setup</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:system-ui;max-width:400px;margin:2em auto;padding:1em}
label{display:block;margin-top:10px}
input{width:100%;padding:8px;box-sizing:border-box}
button{margin-top:14px;padding:10px 20px;background:#0a7;color:#fff;border:0;border-radius:4px;cursor:pointer}</style>
</head><body>
<h2>WiFi Setup</h2>
<form method="POST" action="/save">
<label>SSID<input name="ssid" required></label>
<label>Password<input name="pw" type="password"></label>
<button type="submit">Connect</button>
</form>
</body></html>
)=====";

void handleRoot() {
  server.send_P(200, "text/html", INDEX_HTML);
}

void handleSave() {
  if (!server.hasArg("ssid")) {
    server.send(400, "text/plain", "Missing ssid");
    return;
  }
  pendingSSID = server.arg("ssid");
  pendingPW = server.arg("pw");
  String body = "<html><body><h2>Connecting to " + pendingSSID +
                "...</h2><p>If this succeeds, the AP will shut down.</p></body></html>";
  server.send(200, "text/html", body);
  tryConnect = true;
}

bool connectSTA(const String& ssid, const String& pw) {
  Serial.printf("Connecting to '%s'...\n", ssid.c_str());
  WiFi.begin(ssid.c_str(), pw.c_str());
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Connected, IP=");
    Serial.println(WiFi.localIP());
    return true;
  }
  Serial.println("Connection failed");
  WiFi.disconnect();
  return false;
}

void provisionWiFi() {
  WiFi.mode(WIFI_AP);
  WiFi.setOutputPower(20.5);
  WiFi.softAP(AP_SSID);
  Serial.print("AP '");
  Serial.print(AP_SSID);
  Serial.print("' started, IP=");
  Serial.println(WiFi.softAPIP());

  server.on("/", HTTP_GET, handleRoot);
  server.on("/save", HTTP_POST, handleSave);
  server.begin();

  while (!wifiReady) {
    server.handleClient();
    if (tryConnect) {
      tryConnect = false;
      delay(500);
      WiFi.mode(WIFI_AP_STA);
      WiFi.setOutputPower(20.5);
      if (connectSTA(pendingSSID, pendingPW)) {
        server.stop();
        WiFi.softAPdisconnect(true);
        WiFi.mode(WIFI_STA);
        WiFi.setOutputPower(20.5);
        wifiReady = true;
      } else {
        WiFi.mode(WIFI_AP);
        WiFi.setOutputPower(20.5);
        WiFi.softAP(AP_SSID);
      }
    }
    delay(10);
  }
}

int postJson(const String& path, const String& body, String& response) {
  if (WiFi.status() != WL_CONNECTED) return -1;
  HTTPClient http;
  wifiClient.setTimeout(1500);
  http.setTimeout(2500);
  http.setReuse(false);
  http.begin(wifiClient, SERVER_URL + path);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);
  int code = http.POST(body);
  if (code > 0) response = http.getString();
  http.end();
  return code;
}

void sendHeartbeat() {
  JsonDocument doc;
  doc["station_id"] = STATION_ID;
  doc["water_level"] = 100;
  String body;
  serializeJson(doc, body);
  String response;
  int code = postJson("/api/station/heartbeat", body, response);
  Serial.printf("heartbeat -> %d\n", code);
}

void reportDispense(float volumeMl) {
  JsonDocument doc;
  doc["station_id"] = STATION_ID;
  doc["resident_id"] = residentId;
  doc["volume_ml"] = volumeMl;
  String body;
  serializeJson(doc, body);
  String response;
  int code = postJson("/api/dispense", body, response);
  Serial.printf("dispense %.1f mL -> %d\n", volumeMl, code);
  if (code == 200) Serial.println(response);
}

void startBeep(unsigned long ms) {
  digitalWrite(BUZZER_PIN, HIGH);
  beepUntilMs = millis() + ms;
}

void stopBeepIfDue() {
  if (beepUntilMs && (long)(millis() - beepUntilMs) >= 0) {
    digitalWrite(BUZZER_PIN, LOW);
    beepUntilMs = 0;
  }
}

void resetToIdle() {
  digitalWrite(LED_PIN, LOW);
  digitalWrite(PUMP_PIN, LOW);
  residentId = -1;
  remainingMl = 0;
  setState(IDLE);
}

String readScan() {
  if (!scanner.available()) return "";
  String data = "";
  unsigned long lastByte = millis();
  while (millis() - lastByte < SCAN_GAP_MS) {
    if (scanner.available()) {
      char c = scanner.read();
      if (c >= 0x20 && c <= 0x7E) data += c;
      lastByte = millis();
    }
  }
  return data;
}

void handleScan(const String& qr) {
  Serial.printf("Scanned: %s\n", qr.c_str());
  JsonDocument doc;
  doc["station_id"] = STATION_ID;
  doc["qr_data"] = qr;
  String body;
  serializeJson(doc, body);
  String response;
  int code = postJson("/api/auth", body, response);
  Serial.printf("auth -> %d\n", code);
  if (code != 200) {
    startBeep(INVALID_BEEP_MS);
    return;
  }
  JsonDocument resDoc;
  DeserializationError err = deserializeJson(resDoc, response);
  if (err) {
    Serial.printf("json parse: %s\n", err.c_str());
    startBeep(INVALID_BEEP_MS);
    return;
  }
  bool authorized = resDoc["authorized"];
  if (!authorized) {
    const char* reason = resDoc["reason"] | "denied";
    Serial.printf("Denied: %s\n", reason);
    startBeep(INVALID_BEEP_MS);
    return;
  }
  residentId = resDoc["resident_id"];
  remainingMl = resDoc["remaining_ml"];
  Serial.printf("Authorized resident=%d remaining=%.0f mL\n", residentId, remainingMl);
  digitalWrite(LED_PIN, HIGH);
  authStartMs = millis();
  setState(AUTHORIZED);
}

void pollButton() {
  int reading = digitalRead(BUTTON_PIN);
  if (reading != lastBtnReading) {
    lastBtnChange = millis();
    lastBtnReading = reading;
  }
  if (millis() - lastBtnChange > BUTTON_DEBOUNCE_MS && reading != btnState) {
    btnState = reading;
    Serial.printf("[btn] %s\n", btnState == LOW ? "press" : "release");
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n--- water_station ---");

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  pinMode(PUMP_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(LED_PIN, LOW);
  digitalWrite(PUMP_PIN, LOW);

  scanner.begin(9600);

  provisionWiFi();
  setState(IDLE);
  Serial.println("Ready.");
}

void loop() {
  stopBeepIfDue();
  pollButton();

  if (millis() - lastAliveMs >= ALIVE_INTERVAL_MS) {
    Serial.printf("[alive] state=%s wifi=%d rssi=%d heap=%u\n",
                  stateName(state), WiFi.status(), WiFi.RSSI(), ESP.getFreeHeap());
    lastAliveMs = millis();
  }

  if (millis() - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS) {
    sendHeartbeat();
    lastHeartbeatMs = millis();
  }

  switch (state) {
    case IDLE: {
      String qr = readScan();
      if (qr.length() > 0) handleScan(qr);
      break;
    }
    case AUTHORIZED: {
      if (btnState == LOW) {
        Serial.println("[pump] start");
        digitalWrite(PUMP_PIN, HIGH);
        pumpStartMs = millis();
        setState(DISPENSING);
      } else if (millis() - authStartMs > AUTH_TIMEOUT_MS) {
        Serial.println("[auth] timeout");
        resetToIdle();
      }
      break;
    }
    case DISPENSING: {
      float dispensedMl = (millis() - pumpStartMs) / 1000.0f * FLOW_RATE_ML_S;
      if (dispensedMl >= remainingMl) {
        Serial.printf("[pump] quota depleted at %.1f mL\n", dispensedMl);
        digitalWrite(PUMP_PIN, LOW);
        digitalWrite(LED_PIN, LOW);
        startBeep(DEPLETED_BEEP_MS);
        reportDispense(remainingMl);
        residentId = -1;
        remainingMl = 0;
        setState(IDLE);
      } else if (btnState == HIGH) {
        Serial.printf("[pump] stop @ %.1f mL\n", dispensedMl);
        digitalWrite(PUMP_PIN, LOW);
        digitalWrite(LED_PIN, LOW);
        reportDispense(dispensedMl);
        residentId = -1;
        remainingMl = 0;
        setState(IDLE);
      }
      break;
    }
    default:
      break;
  }
}
