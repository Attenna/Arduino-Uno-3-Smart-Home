#ifndef RAIN_SENSOR_H
#define RAIN_SENSOR_H

#include <Arduino.h>

// 雨滴传感器（模拟量）
// 阈值 RAIN_THRESHOLD 为硬件标定常数，低于该值视为有雨。
class RainSensor {
public:
    void begin();
    bool read();
    bool isRaining() const; // true=检测到雨
    int getRaw() const;     // 模拟量 0~1023
private:
    int _raw;
};

#endif
