#include "Fan.h"
#include "../Config.h"

void Fan::begin() {
    pinMode(FAN_INA, OUTPUT);
    pinMode(FAN_INB, OUTPUT);
    digitalWrite(FAN_INA, LOW);
    digitalWrite(FAN_INB, LOW);
    _speed = 0;
}

void Fan::setSpeed(int speed) {
    speed = constrain(speed, 0, 255);
    _speed = speed;
    digitalWrite(FAN_INB, LOW); // 方向固定：正转
    // D8 非 PWM 引脚：退化为开关控制（0=停，>0=全速）
    digitalWrite(FAN_INA, speed > 0 ? HIGH : LOW);
}

void Fan::stop() { setSpeed(0); }
void Fan::full() { setSpeed(255); }
int Fan::getSpeed() const { return _speed; }
