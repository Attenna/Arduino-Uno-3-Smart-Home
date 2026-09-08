#include "Buzzer.h"
#include "../Config.h"

void Buzzer::begin() {
    pinMode(BUZZER_PIN, OUTPUT);
    _on = false;
    _beep.active = false;
    _beep.count = 0;
    setOutput(BUZZER_DEFAULT_OFF ? false : true); // 上电默认关闭（静音）
}

void Buzzer::setOutput(bool on) {
    digitalWrite(BUZZER_PIN, BUZZER_ACTIVE_LOW ? !on : on);
}

void Buzzer::on() {
    _beep.active = false;
    _on = true;
    setOutput(true);
}

void Buzzer::off() {
    _beep.active = false;
    _on = false;
    setOutput(false);
}

void Buzzer::beep(int count, unsigned long onMs, unsigned long offMs) {
    if (count <= 0) return;
    _on = false;
    _beep.count = count;
    _beep.onMs = max(onMs, 30UL);
    _beep.offMs = max(offMs, 30UL);
    _beep.active = true;
    _beep.isOn = false;
    _beep.nextToggle = 0;
}

void Buzzer::update() {
    if (!_beep.active || _beep.count == 0) return;
    unsigned long now = millis();
    if (now >= _beep.nextToggle) {
        if (!_beep.isOn) {
            setOutput(true);
            _beep.isOn = true;
            _beep.nextToggle = now + _beep.onMs;
        } else {
            setOutput(false);
            _beep.isOn = false;
            _beep.count--;
            _beep.nextToggle = now + _beep.offMs;
            if (_beep.count == 0) _beep.active = false;
        }
    }
}

bool Buzzer::isActive() const {
    return _on || _beep.active;
}
