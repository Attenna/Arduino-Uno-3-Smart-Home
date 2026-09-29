#include "KeypadSensor.h"
#include "../Config.h"

void KeypadSensor::begin() {
    pinMode(KEYPAD_ROW_PIN, OUTPUT);
    digitalWrite(KEYPAD_ROW_PIN, LOW);       // 行恒低；列上拉，未按=高，按下=低
    pinMode(KEYPAD_COL_PIN, INPUT_PULLUP);

    _level = true;                           // 初始视为未按
    _armed = true;
    _latched = false;
    _changeMs = millis();
}

void KeypadSensor::read() {
    bool raw = (digitalRead(KEYPAD_COL_PIN) == HIGH);
    unsigned long now = millis();

    // 电平变化 → 重置防抖计时
    if (raw != _level) {
        _level = raw;
        _changeMs = now;
        return;
    }

    if (!_level) {
        // 持续低电平：防抖确认后【仅锁存一次】，等 takePress 取走
        if (_armed && now - _changeMs >= KEYPAD_DEBOUNCE_MS) {
            _armed = false;
            _latched = true;
        }
    } else {
        // 持续高电平（松开），保持足够时间后重新武装
        if (!_armed && now - _changeMs >= KEYPAD_RELEASE_MS) {
            _armed = true;
        }
    }
}

bool KeypadSensor::takePress() {
    bool v = _latched;
    _latched = false;
    return v;
}

char KeypadSensor::key() const {
    return '1';
}
