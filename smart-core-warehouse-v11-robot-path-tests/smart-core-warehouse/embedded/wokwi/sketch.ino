const int ENTRY_PIN = 25;
const int X_LIMIT_PIN = 26;
const int Z_LIMIT_PIN = 27;
const int FORK_PIN = 14;
const int ESTOP_PIN = 12;
const int WEIGHT_PIN = 34;
const int ONLINE_LED = 18;
const int TASK_LED = 19;
const int FAULT_LED = 21;

unsigned long lastPrint = 0;

bool activeLow(int pin) {
  return digitalRead(pin) == LOW;
}

void setup() {
  Serial.begin(115200);
  pinMode(ENTRY_PIN, INPUT_PULLUP);
  pinMode(X_LIMIT_PIN, INPUT_PULLUP);
  pinMode(Z_LIMIT_PIN, INPUT_PULLUP);
  pinMode(FORK_PIN, INPUT_PULLUP);
  pinMode(ESTOP_PIN, INPUT_PULLUP);
  pinMode(ONLINE_LED, OUTPUT);
  pinMode(TASK_LED, OUTPUT);
  pinMode(FAULT_LED, OUTPUT);
  digitalWrite(ONLINE_LED, HIGH);
  Serial.println("SOPALTEC ESP32 entry station simulation ready");
}

void loop() {
  bool entryPresent = activeLow(ENTRY_PIN);
  bool xLimit = activeLow(X_LIMIT_PIN);
  bool zLimit = activeLow(Z_LIMIT_PIN);
  bool forkExtended = activeLow(FORK_PIN);
  bool estop = activeLow(ESTOP_PIN);
  int rawWeight = analogRead(WEIGHT_PIN);
  float weightKg = (rawWeight / 4095.0) * 25.0;

  digitalWrite(TASK_LED, entryPresent ? HIGH : LOW);
  digitalWrite(FAULT_LED, estop ? HIGH : LOW);

  if (millis() - lastPrint >= 1000) {
    lastPrint = millis();
    Serial.print("{\"device_id\":\"ESP32-ENTRY-01\",");
    Serial.print("\"entry_present\":");
    Serial.print(entryPresent ? "true" : "false");
    Serial.print(",\"weight_kg\":");
    Serial.print(weightKg, 2);
    Serial.print(",\"x_limit\":");
    Serial.print(xLimit ? "true" : "false");
    Serial.print(",\"z_limit\":");
    Serial.print(zLimit ? "true" : "false");
    Serial.print(",\"fork_extended\":");
    Serial.print(forkExtended ? "true" : "false");
    Serial.print(",\"estop\":");
    Serial.print(estop ? "true" : "false");
    Serial.println("}");
  }
}
