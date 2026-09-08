#include "LightSensor.h"
#include "../Config.h"

void LightSensor::begin() {
    pinMode(LIGHT_PIN, INPUT);
    _raw = 0;
}

bool LightSensor::read() {
    _raw = analogRead(LIGHT_PIN);
    return true;
}

int LightSensor::getRaw() const { return _raw; }
