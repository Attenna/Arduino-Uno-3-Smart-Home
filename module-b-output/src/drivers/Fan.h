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
    int getSpeed() const;
private:
    int _speed;
};

#endif
