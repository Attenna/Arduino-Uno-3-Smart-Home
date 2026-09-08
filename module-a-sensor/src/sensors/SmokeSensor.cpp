#include "SmokeSensor.h"
#include "../Config.h"

void SmokeSensor::begin() {
    pinMode(SMOKE_DIGITAL_PIN, INPUT);
    pinMode(SMOKE_ANALOG_PIN, INPUT);
    _alarm = false;
    _raw = 0;
}

bool SmokeSensor::read() {
    _alarm = (digitalRead(SMOKE_DIGITAL_PIN) == HIGH);
    _raw = analogRead(SMOKE_ANALOG_PIN);
    return _alarm;
}

bool SmokeSensor::isAlarm() const { return _alarm; }
int  SmokeSensor::getRaw() const  { return _raw; }
