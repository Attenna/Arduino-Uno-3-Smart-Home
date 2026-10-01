#include "Fan.h"
#include "../Config.h"

namespace {
// 引脚是否仍是 OUTPUT。别的外设初始化（U8x8 的 SPI.begin() 等）会把共用引脚改回
// INPUT，此后对它的 digitalWrite 会静默失效——IR.cpp 已记录过 D12 的同类事故。
bool isOutputPin(uint8_t pin) {
    uint8_t port = digitalPinToPort(pin);
    if (port == NOT_A_PIN) return false;
    return (*(portModeRegister(port)) & digitalPinToBitMask(pin)) != 0;
}
} // namespace

void Fan::begin() {
    _speed = 0;
    _reclaim = 0;
    _lastReportMs = 0;
    pinReady();
    digitalWrite(FAN_INA, LOW);
    digitalWrite(FAN_INB, LOW);
}

// 抢回风扇两脚为 OUTPUT：每次写入前都先重设方向寄存器，避免被 SPI/OLED 等抢走。
void Fan::pinReady() {
    pinMode(FAN_INA, OUTPUT);
    pinMode(FAN_INB, OUTPUT);
}

void Fan::setSpeed(int speed) {
    speed = constrain(speed, 0, 255);
    _speed = speed;
    pinReady();
    digitalWrite(FAN_INB, LOW); // 方向固定：正转
    // D8 非 PWM 引脚：退化为开关控制（0=停，>0=全速）
    digitalWrite(FAN_INA, speed > 0 ? HIGH : LOW);
}

void Fan::stop() { setSpeed(0); }
void Fan::full() { setSpeed(255); }
int Fan::getSpeed() const { return _speed; }

// 每个 loop 自愈：一旦发现 D7/D8 不再是 OUTPUT（被外设改回高阻），立刻抢回并按目标
// 转速重新驱动。否则半桥输入悬空 → 风扇自己转，而软件以为已关（面板 0% 但物理在转）。
void Fan::update() {
    if (isOutputPin(FAN_INA) && isOutputPin(FAN_INB)) return; // 正常路径零开销
    _reclaim++;
    pinReady();
    digitalWrite(FAN_INB, LOW);
    digitalWrite(FAN_INA, _speed > 0 ? HIGH : LOW);
    reportReclaim();
}

void Fan::reportReclaim() {
    unsigned long now = millis();
    // 前 3 次立即上报，之后最多每 5s 一条，避免持续被抢时刷屏
    if (_reclaim > 3 && (now - _lastReportMs) < 5000UL) return;
    _lastReportMs = now;
    Serial.print(F("{\"module\":\"output\",\"type\":\"alert\","
                   "\"event\":\"fan_pin_reclaim\",\"count\":"));
    Serial.print(_reclaim);
    Serial.print(F(",\"speed\":"));
    Serial.print(_speed);
    Serial.println(F("}"));
}
