#ifndef DHT_SENSOR_H
#define DHT_SENSOR_H

#include <Arduino.h>

// DHT11 温湿度传感器
// 只负责读取温湿度，不做任何业务判断。
class DHTSensor {
public:
    DHTSensor();
    void begin();
    bool read();                    // 读取一次，返回是否成功
    float getTemperature() const;   // 摄氏度，失败返回 NAN
    float getHumidity() const;      // 百分比，失败返回 NAN
private:
    float _temperature;
    float _humidity;
    unsigned long _lastRead;
};

#endif
