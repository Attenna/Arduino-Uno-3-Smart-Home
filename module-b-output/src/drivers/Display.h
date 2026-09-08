#ifndef DISPLAY_H
#define DISPLAY_H

#include <Arduino.h>

// TM1637 四位数码管
class Display {
public:
    void begin();
    void showNumber(int value);       // -999 ~ 9999
    void showTime(byte hour, byte minute);
    void clear();
    void update();                    // 主循环调用：每秒刷新时钟
private:
    byte _hour;
    byte _minute;
    bool _hasTime;
    unsigned long _lastRefresh;

    void start();
    void stop();
    void writeByte(byte b);
    void setBrightness(byte b);
    void writeDigits(byte a, byte b, byte c, byte d);
    void showClock(byte h, byte m);
};

#endif
