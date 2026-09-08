#ifndef OLED_DISPLAY_H
#define OLED_DISPLAY_H

#include <Arduino.h>

// SH1106 / SSD1306 OLED（U8x8 文本模式，8 行 x 16 列）
// 只负责显示传入的文本，不组合业务状态。
class OLEDDisplay {
public:
    void begin();
    void showText(byte line, const char* text); // line 0~7，最多 16 字符
    void clearLine(byte line);
    void clear();
private:
    bool _ready;
    char _lines[8][17];
};

#endif
