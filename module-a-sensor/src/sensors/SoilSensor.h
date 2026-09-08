#ifndef SOIL_SENSOR_H
#define SOIL_SENSOR_H

#include <Arduino.h>

// 土壤湿度传感器（数字干湿 + 模拟量）
// 兼容 YL-69 / FC-28 等常见土壤湿度模块（同时读取 DO 与 AO）。
class SoilSensor {
public:
    void begin();
    bool read();
    bool isDry() const;        // 数字输出：true=干燥
    int getMoisture() const;   // 模拟量 0~1023（越高越干）
private:
    bool _dry;
    int _moisture;
};

#endif
