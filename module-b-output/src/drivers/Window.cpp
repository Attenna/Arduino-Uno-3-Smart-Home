#include "Window.h"
#include "../Config.h"

void Window::begin() {
    _attached = false;
    _state = 0;
    _detachAt = 0;
}

void Window::writeAngle(byte angle) {
    if (!_attached) {
        _servo.attach(WINDOW_SERVO_PIN);
        _attached = true;
    }
    _servo.write(angle);
    _detachAt = millis() + SERVO_SETTLE_TIME;
}

void Window::open()   { _state = 2; writeAngle(WINDOW_OPEN_ANGLE); }
void Window::close()  { _state = 1; writeAngle(WINDOW_CLOSED_ANGLE); }
void Window::normal() { _state = 0; writeAngle(WINDOW_NORMAL_ANGLE); }

void Window::update() {
    if (_attached && _detachAt > 0 && millis() >= _detachAt) {
        _servo.detach();
        _attached = false;
        _detachAt = 0;
    }
}

int Window::getState() const { return _state; }
