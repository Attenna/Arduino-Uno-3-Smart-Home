#ifndef LIGHT_H
#define LIGHT_H

#include <Arduino.h>

// NeoPixel RGB 灯带
class Light {
public:
    void begin();
    void off();
    void white(int level);      // 0~255 整条灯带白光
    // 夜灯：只点亮居中 LIGHT_NIGHT_COUNT 颗灯珠（其余熄灭），level 0~255。
    // 与 white() 的区别是「亮几颗」而不是「整条多亮」，用于小夜灯场景。
    void night(int level);
    // 色温白光：kelvin（LIGHT_TEMP_MIN~LIGHT_TEMP_MAX）选冷暖，level 0~255 定亮度。
    void temp(int kelvin, int level);
    void red();
    void green();
    void blue();
    void yellow();
    void purple();
    void cyan();
    // rgb 的 level 是「整体亮度缩放」0~255，缺省 255 = 原样输出（与旧行为一致）。
    void rgb(int r, int g, int b, int level = 255);
    int getLevel() const;
    // 夜灯诊断用：当前实际点亮的灯珠数（0 = 整条都亮/熄灭由 level 决定）。
    uint8_t litCount() const;
    // 诊断用：show() 实际被调用的次数 + 灯带当前全局亮度。
    // getLevel() 只是「意图值」，无法证明数据真的推到了灯带；配合 show 次数
    // 才能区分「固件没执行」和「执行了但物理层没亮」。
    uint16_t showCount() const;
    uint8_t stripBrightness() const;
    // 直接操作 RGB_PIN（绕过 NeoPixel 库），用于自检引脚是否被短路/带不动。
    // 读回值写入 outHigh/outLow（1=读到高，0=读到低）。测试后自动恢复灯带输出。
    void rawPinTest(int* outHigh, int* outLow);
private:
    int _level;
    uint8_t _r, _g, _b;      // 最近一次颜色，rawPinTest 后据此恢复上屏
    uint8_t _count;          // 最近一次点亮的灯珠数（0 = 整条），夜灯只点中间几颗
    uint16_t _shows;
    void setRgb(int r, int g, int b);
};

#endif
