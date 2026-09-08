#ifndef ULTRASONIC_SENSOR_H
#define ULTRASONIC_SENSOR_H

#include <Arduino.h>

// HC-SR04 超声波测距
// 只负责测距，不做业务判断。
class UltrasonicSensor {
public:
    UltrasonicSensor();
    void begin();
    bool read();                  // 读取一次，返回是否在量程内
    float getDistanceCm() const;  // 距离(cm)，-1 表示超范围/无回波
private:
    float _distance;
    unsigned long _lastRead;
};

#endif
