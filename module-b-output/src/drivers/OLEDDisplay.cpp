#include "OLEDDisplay.h"
#include "../Config.h"
#include <U8x8lib.h>

// SPI 接口（4 线）：SCK=D13、MOSI=D11 走硬件 SPI 固定引脚，
// 其余三根由构造参数指定：reset=RES、dc=DC、cs=CS。
// 构造顺序为 (reset, dc, cs)。
#if OLED_IS_SH1106
static U8X8_SH1106_128X64_NONAME_4W_HW_SPI _oled(/*cs=*/OLED_CS_PIN, /*dc=*/OLED_DC_PIN, /*reset=*/OLED_RES_PIN);
#else
static U8X8_SSD1306_128X64_NONAME_4W_HW_SPI _oled(/*cs=*/OLED_CS_PIN, /*dc=*/OLED_DC_PIN, /*reset=*/OLED_RES_PIN);
#endif

void OLEDDisplay::begin() {
    _ready = false;
    memset(_lines, ' ', sizeof(_lines));
    for (byte i = 0; i < 8; i++) _lines[i][16] = '\0';

    _oled.begin();
    _oled.setFont(u8x8_font_chroma48medium8_r);
    _ready = true;
    clear();
}

void OLEDDisplay::showText(byte line, const char* text) {
    if (!_ready || line >= 8) return;

    char buf[17];
    for (byte i = 0; i < 16; i++) buf[i] = ' ';
    buf[16] = '\0';
    for (byte i = 0; text[i] && i < 16; i++) buf[i] = text[i];

    if (memcmp(buf, _lines[line], 16) == 0) return; // 未变化则跳过
    memcpy(_lines[line], buf, 16);
    _oled.drawString(0, line, buf);
}

void OLEDDisplay::clearLine(byte line) {
    showText(line, "");
}

void OLEDDisplay::clear() {
    for (byte i = 0; i < 8; i++) clearLine(i);
}
