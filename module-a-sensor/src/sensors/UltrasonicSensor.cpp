#include "UltrasonicSensor.h"
#include "../Config.h"

UltrasonicSensor::UltrasonicSensor() : _distance(-1), _lastRead(0) {}

void UltrasonicSensor::begin() {
    pinMode(US_TRIG_PIN, OUTPUT);
    pinMode(US_ECHO_PIN, INPUT);
    digitalWrite(US_TRIG_PIN, LOW);
}

bool UltrasonicSensor::read() {
    unsigned long now = millis();
    if (now - _lastRead < US_INTERVAL_MS) {
        return _distance >= 0;
    }
    _lastRead = now;

    digitalWrite(US_TRIG_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(US_TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(US_TRIG_PIN, LOW);

    unsigned long pulse = pulseIn(US_ECHO_PIN, HIGH, US_TIMEOUT_US);
    if (pulse == 0) {
        _distance = -1;
        return false;
    }

    _distance = pulse * 0.034f / 2.0f;
    return (_distance >= US_MIN_CM && _distance <= US_MAX_CM);
}

float UltrasonicSensor::getDistanceCm() const { return _distance; }
