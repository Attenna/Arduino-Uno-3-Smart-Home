#ifndef LIGHT_SENSOR_H
#define LIGHT_SENSOR_H

#include <Arduino.h>

// 光敏传感器（模拟量）
// 只输出原始值，由 Home Assistant 判断明暗。
class LightSensor {
public:
    void begin();
    bool read();
    int getRaw() const;   // 0~1023
private:
    int _raw;
};

#endif
