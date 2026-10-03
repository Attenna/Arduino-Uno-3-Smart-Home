#ifndef LIGHT_MATH_H
#define LIGHT_MATH_H

#include <stdint.h>

// 输入已夹取到 0..255；AVR 的 int 为 16 位，乘法必须使用宽整数。
constexpr uint8_t scaleLightChannel(uint8_t channel, uint8_t level) {
    return (uint32_t)channel * level / 255;
}

#endif
