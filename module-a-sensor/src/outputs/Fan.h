#ifndef MODULE_A_FAN_H
#define MODULE_A_FAN_H

#include <Arduino.h>

// 直流风扇单线开关（2026-11 从 B 板迁到 A1）
// 接线：A1(D15) → 驱动板 INA；INB → GND；电机电源独立 5V，GND 与 A 板共地。
// 只做开/关，不做 PWM；上电/复位时先把引脚锁成"停"，避免高阻误导通。
class FanOutput {
public:
    void begin();
    void set(bool on);
    bool isOn() const { return _on; }
private:
    bool _on;
};

#endif
