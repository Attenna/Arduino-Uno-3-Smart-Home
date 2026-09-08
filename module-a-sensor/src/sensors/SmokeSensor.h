#ifndef SMOKE_SENSOR_H
#define SMOKE_SENSOR_H

#include <Arduino.h>

// MQ-2 烟雾传感器（数字报警 + 模拟量）
// 数字输出由 MQ-2 模块上的电位器设定阈值，报警状态来自硬件比较器。
class SmokeSensor {
public:
    void begin();
    bool read();
    bool isAlarm() const;   // true=报警
    int getRaw() const;     // 模拟量 0~1023
private:
    bool _alarm;
    int _raw;
};

#endif
