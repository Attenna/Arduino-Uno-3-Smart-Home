#include "Fan.h"
#include "../Config.h"

void FanOutput::begin() {
    _on = false;
    pinMode(FAN_PIN, OUTPUT);
    digitalWrite(FAN_PIN, FAN_ACTIVE_HIGH ? LOW : HIGH);
}

void FanOutput::set(bool on) {
    _on = on;
    bool level = FAN_ACTIVE_HIGH ? on : !on;
    digitalWrite(FAN_PIN, level ? HIGH : LOW);
}
