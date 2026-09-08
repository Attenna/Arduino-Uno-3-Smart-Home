#include "Door.h"
#include "../Config.h"

void Door::begin() {
    _attached = false;
    _open = false;
    _detachAt = 0;
}

void Door::writeAngle(byte angle) {
    if (!_attached) {
        _servo.attach(DOOR_SERVO_PIN);
        _attached = true;
    }
    _servo.write(angle);
    _detachAt = millis() + SERVO_SETTLE_TIME;
}

void Door::open() {
    _open = true;
    writeAngle(DOOR_OPEN_ANGLE);
}

void Door::close() {
    _open = false;
    writeAngle(DOOR_CLOSED_ANGLE);
}

void Door::update() {
    if (_attached && _detachAt > 0 && millis() >= _detachAt) {
        _servo.detach();
        _attached = false;
        _detachAt = 0;
    }
}

bool Door::isOpen() const { return _open; }
