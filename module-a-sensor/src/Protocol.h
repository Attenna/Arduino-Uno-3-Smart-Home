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
#include "outputs/Light.h"
#include "outputs/Fan.h"

class Protocol {
public:
    static void init();

    // 上行：周期状态上报 / 事件推送
    static void sendReport(const SensorManager& s, const FanOutput& fan);
    static void sendEvent(const Event& e);

    // 下行（可选）：REPORT / INTERVAL:<ms> / WHO / light / fan
    static void handleInput(SensorManager& s, LightOutput& light, FanOutput& fan);

    static unsigned long reportInterval();

private:
    static unsigned long _interval;

    static void printFloat(float v);
    static void printBool(bool v);
    static void processLine(char* line, SensorManager& s, LightOutput& light,
                            FanOutput& fan);
    static bool processLightJson(char* line, LightOutput& light);
    static bool processLightCompact(char* line, LightOutput& light);
    static bool processFanJson(char* line, FanOutput& fan);
    static bool processFanCompact(char* line, FanOutput& fan);
    static void respondFan(bool ok, const char* action, long id, const FanOutput& fan);
    static void respondWho();
};

#endif // PROTOCOL_A_H
