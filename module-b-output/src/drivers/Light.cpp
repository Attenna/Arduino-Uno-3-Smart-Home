#include "Light.h"
#include "../Config.h"
#include <Adafruit_NeoPixel.h>

static Adafruit_NeoPixel _strip(LED_COUNT, RGB_PIN, NEO_GRB + NEO_KHZ800);

void Light::begin() {
    _level = 0;
    _r = _g = _b = 0;
    _shows = 0;
    _strip.begin();
    _strip.setBrightness(LIGHT_BRIGHTNESS);
#if LIGHT_BOOT_ON
    white(LIGHT_BOOT_LEVEL);   // 上电默认点亮（注意：需独立供电，否则易欠压复位）
#else
    off();                     // 上电熄灭（默认，稳定）
#endif
    _shows = 0;                // 上电那一次不计入运行期统计
}

void Light::setRgb(int r, int g, int b) {
    _level = max(r, max(g, b));
    _r = (uint8_t)constrain(r, 0, 255);
    _g = (uint8_t)constrain(g, 0, 255);
    _b = (uint8_t)constrain(b, 0, 255);
    _strip.fill(_strip.Color(_r, _g, _b), 0, LED_COUNT);
    _strip.show();
    _shows++;
}

void Light::off() {
    _level = 0;
    _r = _g = _b = 0;
    _strip.clear();
    _strip.show();
    _shows++;
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
uint16_t Light::showCount() const { return _shows; }
uint8_t Light::stripBrightness() const { return _strip.getBrightness(); }

void Light::rawPinTest(int* outHigh, int* outLow) {
    // 绕过 NeoPixel 库直接驱动 RGB_PIN：把数据脚当普通 GPIO，先拉高读回、再拉低读回。
    // 引脚被短路到 GND 或带载过重时，拉高读回会是 0——这才是「固件执行了但灯不亮」
    // 与「引脚物理没信号」的二分判据。测完立刻复位灯带时序并重新上屏当前颜色。
    pinMode(RGB_PIN, OUTPUT);
    digitalWrite(RGB_PIN, HIGH);
    delayMicroseconds(20);
    *outHigh = digitalRead(RGB_PIN) ? 1 : 0;
    digitalWrite(RGB_PIN, LOW);
    delayMicroseconds(20);
    *outLow = digitalRead(RGB_PIN) ? 1 : 0;
    _strip.begin();
    _strip.setBrightness(LIGHT_BRIGHTNESS);
    _strip.fill(_strip.Color(_r, _g, _b), 0, LED_COUNT);
    _strip.show();
}
