#ifndef PIR_SENSOR_H
#define PIR_SENSOR_H

#include <Arduino.h>

// PIR 人体红外传感器（SR602 / HC-SR501 等，输出高电平表示检测到运动）
class PIRSensor {
public:
    void begin();
    bool read();
    bool isMotion() const;   // true=检测到人体运动
private:
    bool _motion;
};

#endif
