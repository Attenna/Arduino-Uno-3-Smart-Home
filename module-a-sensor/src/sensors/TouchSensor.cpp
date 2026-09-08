#include "TouchSensor.h"
#include "../Config.h"

void TouchSensor::begin() {
    pinMode(TOUCH_PIN, INPUT);
    _pressed = false;
}

bool TouchSensor::read() {
    _pressed = (digitalRead(TOUCH_PIN) == HIGH);
    return _pressed;
}

bool TouchSensor::isPressed() const { return _pressed; }
