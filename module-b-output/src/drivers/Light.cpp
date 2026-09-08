#include "Light.h"
#include "../Config.h"
#include <Adafruit_NeoPixel.h>

static Adafruit_NeoPixel _strip(LED_COUNT, RGB_PIN, NEO_GRB + NEO_KHZ800);

void Light::begin() {
    _level = 0;
    _strip.begin();
    _strip.setBrightness(LIGHT_BRIGHTNESS);
#if LIGHT_BOOT_ON
    white(LIGHT_BOOT_LEVEL);   // 上电默认点亮（注意：需独立供电，否则易欠压复位）
#else
    off();                     // 上电熄灭（默认，稳定）
#endif
}

void Light::setRgb(int r, int g, int b) {
    _level = max(r, max(g, b));
    _strip.fill(_strip.Color(r, g, b), 0, LED_COUNT);
    _strip.show();
}

void Light::off() {
    _level = 0;
    _strip.clear();
    _strip.show();
}

void Light::white(int level) {
    level = constrain(level, 0, 255);
    setRgb(level, level, level);
}

void Light::red()    { setRgb(255, 0, 0); }
void Light::green()  { setRgb(0, 255, 0); }
void Light::blue()   { setRgb(0, 0, 255); }
void Light::yellow() { setRgb(255, 180, 0); }
void Light::purple() { setRgb(160, 0, 255); }
void Light::cyan()   { setRgb(0, 180, 255); }

void Light::rgb(int r, int g, int b) {
    setRgb(constrain(r, 0, 255), constrain(g, 0, 255), constrain(b, 0, 255));
}

int Light::getLevel() const { return _level; }
