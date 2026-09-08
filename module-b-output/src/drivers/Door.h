#ifndef DOOR_H
#define DOOR_H

#include <Arduino.h>
#include <Servo.h>

// 门舵机（SG90）
// 只负责 open()/close() 与舵机引脚释放，不含自动关门等业务逻辑。
class Door {
public:
    void begin();
    void open();        // 90°
    void close();       // 0°
    void update();      // 主循环调用：运动完成后释放舵机引脚
    bool isOpen() const;
private:
    Servo _servo;
    bool _attached;
    bool _open;
    unsigned long _detachAt;

    void writeAngle(byte angle);
};

#endif
