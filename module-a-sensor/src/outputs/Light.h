#ifndef MODULE_A_LIGHT_H
#define MODULE_A_LIGHT_H

#include <Arduino.h>

class LightOutput {
public:
    void begin();
    void off();
    void white(int level, byte count);
    void rgb(int r, int g, int b, int level, byte count);
    int level() const { return _level; }
    byte count() const { return _count; }
private:
    int _level;
    byte _count;
    void show(int r, int g, int b, int level, byte count);
};

#endif
