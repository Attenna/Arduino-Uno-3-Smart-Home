#ifndef FAN_H
#define FAN_H

#include <Arduino.h>

// 直流风扇（INA/INB 半桥驱动）
// 注意：INA=D8、INB=D7 均非硬件 PWM 引脚，风扇为开关控制（0=停，>0=全速）。
class Fan {
public:
    void begin();
    void setSpeed(int speed); // 0=停，>0=全速
    void stop();
    void full();
    void update();            // 主循环调用：引脚被外设改回 INPUT 时自愈
    int getSpeed() const;
private:
    void pinReady();          // 抢回 D7/D8 为 OUTPUT
    void reportReclaim();     // 串口上报自愈事件（限频）
    int _speed;
    uint16_t _reclaim;        // 累计自愈次数（诊断）
    unsigned long _lastReportMs;
};

#endif
