#include "Ultrasonic.h"
#include "../Config.h"

void Ultrasonic::begin() {
    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);
    pinMode(ULTRASONIC_TRIG_PIN, OUTPUT);
    pinMode(ULTRASONIC_ECHO_PIN, INPUT);
    _lastTrigger = millis();
}

unsigned long Ultrasonic::measure() {
    // Unsigned subtraction also handles millis() rollover. No cached readings.
    unsigned long elapsed = millis() - _lastTrigger;
    if (elapsed < ULTRASONIC_INTERVAL_MS) {
        delay(ULTRASONIC_INTERVAL_MS - elapsed);
    }
    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);
    delayMicroseconds(2);
    _lastTrigger = millis();
    digitalWrite(ULTRASONIC_TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);
    // Keep interrupts enabled for Serial, Servo and millis(). Bounded to 25 ms.
    return pulseInLong(ULTRASONIC_ECHO_PIN, HIGH, ULTRASONIC_TIMEOUT_US);
}
