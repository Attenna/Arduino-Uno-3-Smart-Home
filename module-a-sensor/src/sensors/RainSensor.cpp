#include "RainSensor.h"
#include "../Config.h"

void RainSensor::begin() {
    pinMode(RAIN_ANALOG_PIN, INPUT);
    _raw = 1023;
}

bool RainSensor::read() {
    _raw = analogRead(RAIN_ANALOG_PIN);
    return isRaining();
}

bool RainSensor::isRaining() const {
    return _raw < RAIN_THRESHOLD;
}

int RainSensor::getRaw() const { return _raw; }
