#include "Light.h"
#include "LightMath.h"
#include "../Config.h"
#include <Adafruit_NeoPixel.h>
#include <avr/pgmspace.h>

static Adafruit_NeoPixel _strip(LED_COUNT, RGB_PIN, NEO_GRB + NEO_KHZ800);

// 色温 → RGB 查表（2700K 暖黄 → 6500K 冷白）。
// 放 PROGMEM：表本身只有几十字节，但 Uno 的 2KB RAM 里 .data 每字节都紧，
// 又因为下面的插值只用到相邻两点，查表比引入 log()/浮点库省得多（flash 才是真瓶颈）。
struct TempPoint {
    int16_t k;
    uint8_t r, g, b;
};

static const TempPoint TEMP_TABLE[] PROGMEM = {
    {2700, 255, 169, 87},
    {3000, 255, 180, 107},
    {3500, 255, 196, 137},
    {4000, 255, 209, 163},
    {4500, 255, 219, 186},
    {5000, 255, 228, 206},
    {5700, 255, 237, 224},
    {6500, 255, 249, 253},
};

namespace {

const byte TEMP_POINTS = sizeof(TEMP_TABLE) / sizeof(TEMP_TABLE[0]);

int interpChannel(uint8_t v0, uint8_t v1, int w, int span) {
    return (int)v0 + ((int)v1 - (int)v0) * w / span;
}

} // namespace

void Light::begin() {
    _level = 0;
    _r = _g = _b = 0;
    _count = 0;
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
    _count = 0;                // 整条灯带
    _strip.fill(_strip.Color(_r, _g, _b), 0, LED_COUNT);
    _strip.show();
    _shows++;
}

void Light::off() {
    _level = 0;
    _r = _g = _b = 0;
    _count = 0;
    _strip.clear();
    _strip.show();
    _shows++;
}

void Light::white(int level) {
    level = constrain(level, 0, 255);
    setRgb(level, level, level);
}

void Light::night(int level) {
    level = constrain(level, 0, 255);
    byte count = LIGHT_NIGHT_COUNT;
    if (count > LED_COUNT) count = LED_COUNT;
    if (count < 1) count = 1;
    byte start = (LED_COUNT - count) / 2;   // 居中：8 颗取 2 颗时点亮第 4、5 颗

    _level = level;
    _r = _g = _b = (uint8_t)level;
    _count = count;
    _strip.clear();                          // 先整条熄灭，再只点中间几颗
    _strip.fill(_strip.Color(_r, _g, _b), start, count);
    _strip.show();
    _shows++;
}

void Light::temp(int kelvin, int level) {
    kelvin = constrain(kelvin, LIGHT_TEMP_MIN, LIGHT_TEMP_MAX);
    level = constrain(level, 0, 255);

    int r, g, b;
    if (kelvin <= (int)pgm_read_word(&TEMP_TABLE[0].k)) {
        r = pgm_read_byte(&TEMP_TABLE[0].r);
        g = pgm_read_byte(&TEMP_TABLE[0].g);
        b = pgm_read_byte(&TEMP_TABLE[0].b);
    } else if (kelvin >= (int)pgm_read_word(&TEMP_TABLE[TEMP_POINTS - 1].k)) {
        r = pgm_read_byte(&TEMP_TABLE[TEMP_POINTS - 1].r);
        g = pgm_read_byte(&TEMP_TABLE[TEMP_POINTS - 1].g);
        b = pgm_read_byte(&TEMP_TABLE[TEMP_POINTS - 1].b);
    } else {
        byte i = 0;
        while (i + 1 < TEMP_POINTS &&
               kelvin > (int)pgm_read_word(&TEMP_TABLE[i + 1].k)) i++;
        int k0 = (int)pgm_read_word(&TEMP_TABLE[i].k);
        int k1 = (int)pgm_read_word(&TEMP_TABLE[i + 1].k);
        int w = kelvin - k0;
        int span = k1 - k0;                  // 表按 k 递增排列，span > 0
        r = interpChannel(pgm_read_byte(&TEMP_TABLE[i].r),
                          pgm_read_byte(&TEMP_TABLE[i + 1].r), w, span);
        g = interpChannel(pgm_read_byte(&TEMP_TABLE[i].g),
                          pgm_read_byte(&TEMP_TABLE[i + 1].g), w, span);
        b = interpChannel(pgm_read_byte(&TEMP_TABLE[i].b),
                          pgm_read_byte(&TEMP_TABLE[i + 1].b), w, span);
    }

    // level 是整体亮度缩放：色温决定「什么颜色」，level 决定「多亮」
    // AVR int 只有 16 位，乘积最大 65025，必须先提升再相乘。
    r = scaleLightChannel(r, level);
    g = scaleLightChannel(g, level);
    b = scaleLightChannel(b, level);
    setRgb(r, g, b);
}

void Light::red()    { setRgb(255, 0, 0); }
void Light::green()  { setRgb(0, 255, 0); }
void Light::blue()   { setRgb(0, 0, 255); }
void Light::yellow() { setRgb(255, 180, 0); }
void Light::purple() { setRgb(160, 0, 255); }
void Light::cyan()   { setRgb(0, 180, 255); }

void Light::rgb(int r, int g, int b, int level) {
    level = constrain(level, 0, 255);
    r = scaleLightChannel(constrain(r, 0, 255), level);
    g = scaleLightChannel(constrain(g, 0, 255), level);
    b = scaleLightChannel(constrain(b, 0, 255), level);
    setRgb(r, g, b);
}

int Light::getLevel() const { return _level; }
uint8_t Light::litCount() const { return _count; }
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
    if (_count > 0 && _count < LED_COUNT) {
        // 夜灯：只恢复被点亮的那一段，否则自检会把「只亮两颗」变成整条常亮
        _strip.clear();
        _strip.fill(_strip.Color(_r, _g, _b), (LED_COUNT - _count) / 2, _count);
    } else {
        _strip.fill(_strip.Color(_r, _g, _b), 0, LED_COUNT);
    }
    _strip.show();
}
