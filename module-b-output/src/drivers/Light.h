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
    uint16_t _shows;
    void setRgb(int r, int g, int b);
};

#endif
