// Temporary Module A diagnostic. Restore production firmware after capture.
// A1 fan stays LOW; no actuator commands are accepted.
#include <Arduino.h>
#define IR_USE_AVR_TIMER1
#include <IRremote.hpp>

static unsigned long edges = 0;
static unsigned long frames = 0;
static unsigned long lastReport = 0;
static uint8_t lastLevel;

void setup() {
    digitalWrite(A1, LOW);
    pinMode(A1, OUTPUT);
    Serial.begin(115200);
    IrReceiver.begin(3, DISABLE_LED_FEEDBACK);
    lastLevel = digitalRead(3);
    Serial.println(F("IR_LINK_DIAGNOSTIC_READY pin=3 fan=off"));
}

void loop() {
    uint8_t level = digitalRead(3);
    if (level != lastLevel) {
        ++edges;
        lastLevel = level;
    }
    if (IrReceiver.decode()) {
        ++frames;
        Serial.print(F("FRAME protocol="));
        Serial.print(IrReceiver.decodedIRData.protocol);
        Serial.print(F(" address="));
        Serial.print(IrReceiver.decodedIRData.address);
        Serial.print(F(" command="));
        Serial.print(IrReceiver.decodedIRData.command);
        Serial.print(F(" flags="));
        Serial.print(IrReceiver.decodedIRData.flags);
        Serial.print(F(" bits="));
        Serial.print(IrReceiver.decodedIRData.numberOfBits);
        Serial.print(F(" rawlen="));
        Serial.println(IrReceiver.decodedIRData.rawlen);
        IrReceiver.resume();
    }
    if (millis() - lastReport >= 1000) {
        lastReport = millis();
        Serial.print(F("INPUT level="));
        Serial.print(level);
        Serial.print(F(" edges="));
        Serial.print(edges);
        Serial.print(F(" frames="));
        Serial.println(frames);
    }
}
