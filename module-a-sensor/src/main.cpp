// ============================================
// Module A — Sensor Node（入口）
// ============================================
// 职责：只负责采集传感器数据并上报，不做任何业务判断。
//
// 数据流：Sensor → SensorManager → Protocol → Serial
// 业务决策全部由 Orange Pi + Home Assistant 完成。
// ============================================

#include <Arduino.h>
#include "Config.h"
#include "core/SensorManager.h"
#include "Protocol.h"
#include "outputs/Light.h"
#include "outputs/Fan.h"

SensorManager sensors;
LightOutput light;
FanOutput fan;
unsigned long lastReport = 0;

void setup() {
    // 风扇已迁到 A1：先于串口等待/传感器初始化锁成"停"，避免上电或 DTR 复位
    // 期间引脚高阻、驱动板输入悬空导致风扇自己转。
    fan.begin();
    Protocol::init();
    sensors.begin();
    light.begin();

    // 上电就绪上报（含设备标识，供网关识别）
    Serial.print(F("{\"module\":\"sensor\",\"type\":\"ready\",\"board\":\""));
    Serial.print(BOARD_TYPE);
    Serial.print(F("\",\"role\":\""));
    Serial.print(BOARD_ROLE);
    Serial.print(F("\",\"version\":\""));
    Serial.print(FW_VERSION);
    Serial.println(F("\"}"));
}

void loop() {
    // 1. 读取所有传感器（驱动内部有各自的采样间隔）
    sensors.readAll();

    // 2. 周期性上报完整状态
    unsigned long now = millis();
    if (now - lastReport >= Protocol::reportInterval()) {
        lastReport = now;
        Protocol::sendReport(sensors, fan);
    }

    // 3. 事件推送（边沿触发，即时上报）
    Event ev;
    while (sensors.pollEvent(ev)) {
        Protocol::sendEvent(ev);
    }

    // 4. 可选下行控制命令（灯带 / 风扇）
    Protocol::handleInput(sensors, light, fan);
}
