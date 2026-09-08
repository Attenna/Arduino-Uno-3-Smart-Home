#ifndef LIGHT_H
#define LIGHT_H

#include <Arduino.h>

// NeoPixel RGB 灯带
class Light {
public:
    void begin();
    void off();
    void white(int level);  // 0~255
    void red();
    void green();
    void blue();
    void yellow();
    void purple();
    void cyan();
    void rgb(int r, int g, int b);
    int getLevel() const;
private:
    int _level;
    void setRgb(int r, int g, int b);
};

#endif
