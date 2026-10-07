#include "Light.h"
#include "../Config.h"
#include <Adafruit_NeoPixel.h>

static Adafruit_NeoPixel strip(RGB_LED_COUNT, RGB_PIN, NEO_GRB + NEO_KHZ800);

void LightOutput::begin() {
    _level = 0;
    _count = 0;
    strip.begin();
    strip.setBrightness(RGB_SAFE_BRIGHTNESS);
    off();
}

void LightOutput::off() {
    _level = 0;
    _count = 0;
    strip.clear();
    strip.show();
}

void LightOutput::show(int r, int g, int b, int level, byte count) {
    level = constrain(level, 0, 255);
    count = constrain(count, 1, RGB_LED_COUNT);
    uint8_t rr = (uint32_t)constrain(r, 0, 255) * level / 255;
    uint8_t gg = (uint32_t)constrain(g, 0, 255) * level / 255;
    uint8_t bb = (uint32_t)constrain(b, 0, 255) * level / 255;
    _level = level;
    _count = count;
    strip.clear();
    strip.fill(strip.Color(rr, gg, bb), (RGB_LED_COUNT - count) / 2, count);
    strip.show();
}

void LightOutput::white(int level, byte count) {
    show(255, 255, 255, level, count);
}

void LightOutput::rgb(int r, int g, int b, int level, byte count) {
    show(r, g, b, level, count);
}
