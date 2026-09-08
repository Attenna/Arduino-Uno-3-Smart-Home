#include "PIRSensor.h"
#include "../Config.h"

void PIRSensor::begin() {
    pinMode(PIR_PIN, INPUT);
    _motion = false;
}

bool PIRSensor::read() {
    _motion = (digitalRead(PIR_PIN) == HIGH);
    return _motion;
}

bool PIRSensor::isMotion() const { return _motion; }
