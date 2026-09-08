#ifndef BUZZER_H
#define BUZZER_H

#include <Arduino.h>

// 蜂鸣器：持续响 / 间歇蜂鸣（非阻塞）
class Buzzer {
public:
    void begin();
    void on();                       // 持续响
    void off();                      // 停止
    void beep(int count, unsigned long onMs, unsigned long offMs);
    void update();                   // 主循环调用：处理间歇蜂鸣
    bool isActive() const;
private:
    bool _on;
    struct {
        int count;
        unsigned long onMs;
        unsigned long offMs;
        unsigned long nextToggle;
        bool active;
        bool isOn;
    } _beep;

    void setOutput(bool on);
};

#endif
