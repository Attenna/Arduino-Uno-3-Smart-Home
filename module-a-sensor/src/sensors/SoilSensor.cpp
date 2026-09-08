#include "SoilSensor.h"
#include "../Config.h"

void SoilSensor::begin() {
    pinMode(SOIL_DIGITAL_PIN, INPUT);
    pinMode(SOIL_ANALOG_PIN, INPUT);
    _dry = false;
    _moisture = 0;
}

bool SoilSensor::read() {
    _dry = (digitalRead(SOIL_DIGITAL_PIN) == HIGH);
    _moisture = analogRead(SOIL_ANALOG_PIN);
    return _dry;
}

bool SoilSensor::isDry() const { return _dry; }
int  SoilSensor::getMoisture() const { return _moisture; }
