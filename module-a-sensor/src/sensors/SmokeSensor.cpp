#include "SmokeSensor.h"
#include "../Config.h"

void SmokeSensor::begin() {
    pinMode(SMOKE_DIGITAL_PIN, INPUT);
    pinMode(SMOKE_ANALOG_PIN, INPUT);
    _alarm = false;
    _raw = 0;
}

bool SmokeSensor::read() {
    // MQ-2 模块 DO 为低电平有效：无烟时输出 HIGH，浓度超阈值时拉低。
    // （2026-09-30 实测：清洁空气 D5=HIGH，DO=HIGH 恒被判成报警 → 已修正极性）
    _alarm = (digitalRead(SMOKE_DIGITAL_PIN) == LOW);
    _raw = analogRead(SMOKE_ANALOG_PIN);
    return _alarm;
}

bool SmokeSensor::isAlarm() const { return _alarm; }
int  SmokeSensor::getRaw() const  { return _raw; }
