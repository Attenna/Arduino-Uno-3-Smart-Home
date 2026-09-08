#ifndef WINDOW_H
#define WINDOW_H

#include <Arduino.h>
#include <Servo.h>

// 窗舵机（SG90）
class Window {
public:
    void begin();
    void open();    // 120°
    void close();   // 0°
    void normal();  // 45°
    void update();
    int getState() const; // 0=normal, 1=closed, 2=open
private:
    Servo _servo;
    bool _attached;
    int _state;
    unsigned long _detachAt;

    void writeAngle(byte angle);
};

#endif
