#include "../src/drivers/LightMath.h"

// 用 avr-g++ -std=gnu++11 -mmcu=atmega328p -fsyntax-only 编译；无需连接 Uno。
static_assert(sizeof(int) == 2, "Run this regression with the AVR compiler");
static_assert(scaleLightChannel(255, 255) == 255, "Full white must not overflow");
static_assert(scaleLightChannel(255, 128) == 128, "Half brightness at overflow boundary");
static_assert(scaleLightChannel(128, 255) == 128, "Full brightness preserves color");
static_assert(scaleLightChannel(128, 128) == 64, "Mid-range scaling");
static_assert(scaleLightChannel(255, 0) == 0, "Zero brightness is dark");
static_assert(scaleLightChannel(0, 255) == 0, "Black remains black");
