#ifndef TOUCH_SENSOR_H
#define TOUCH_SENSOR_H

#include <Arduino.h>

// TTP223 触摸传感器
class TouchSensor {
public:
    void begin();
    bool read();
    bool isPressed() const;
private:
    bool _pressed;
};

#endif
