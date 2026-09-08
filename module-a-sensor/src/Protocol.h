// ============================================
// Protocol — Module A 串口协议层
// ============================================
// 负责：SensorManager 数据 → JSON → USB Serial。
// 数据流：Sensor → Manager → Protocol → Serial
// ============================================

#ifndef PROTOCOL_A_H
#define PROTOCOL_A_H

#include <Arduino.h>
#include "core/SensorManager.h"

class Protocol {
public:
    static void init();

    // 上行：周期状态上报 / 事件推送
    static void sendReport(const SensorManager& s);
    static void sendEvent(const Event& e);

    // 下行（可选）：REPORT / INTERVAL:<ms> / WHO
    static void handleInput(SensorManager& s);

    static unsigned long reportInterval();

private:
    static unsigned long _interval;

    static void printFloat(float v);
    static void printBool(bool v);
    static void processLine(char* line, SensorManager& s);
    static void respondWho();
};

#endif // PROTOCOL_A_H
