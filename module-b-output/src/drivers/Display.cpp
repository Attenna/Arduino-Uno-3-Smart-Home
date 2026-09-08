#include "Display.h"
#include "../Config.h"

// 7 段数码管段码 (0-9)，存于 flash
static const byte SEG[] PROGMEM = {
    0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F
};
#define SEG_MINUS 0x40  // 段 G（负号）

static byte segOf(byte d) { return pgm_read_byte(&SEG[d]); }
static void bitDelay() { delayMicroseconds(10); }

void Display::begin() {
    pinMode(TM_CLK, OUTPUT);
    pinMode(TM_DIO, OUTPUT);
    digitalWrite(TM_CLK, HIGH);
    digitalWrite(TM_DIO, HIGH);
    _hasTime = false;
    _lastRefresh = 0;
    clear();
}

void Display::start() {
    pinMode(TM_DIO, OUTPUT);
    digitalWrite(TM_DIO, HIGH);
    digitalWrite(TM_CLK, HIGH);
    bitDelay();
    digitalWrite(TM_DIO, LOW);
    bitDelay();
}

void Display::stop() {
    pinMode(TM_DIO, OUTPUT);
    digitalWrite(TM_CLK, LOW);
    bitDelay();
    digitalWrite(TM_DIO, LOW);
    bitDelay();
    digitalWrite(TM_CLK, HIGH);
    bitDelay();
    digitalWrite(TM_DIO, HIGH);
    bitDelay();
}

void Display::writeByte(byte b) {
    pinMode(TM_DIO, OUTPUT);
    for (byte i = 0; i < 8; i++) {
        digitalWrite(TM_CLK, LOW);
        bitDelay();
        digitalWrite(TM_DIO, (b & 0x01) ? HIGH : LOW);
        bitDelay();
        digitalWrite(TM_CLK, HIGH);
        bitDelay();
        b >>= 1;
    }
    // ACK
    digitalWrite(TM_CLK, LOW);
    pinMode(TM_DIO, INPUT_PULLUP);
    bitDelay();
    digitalWrite(TM_CLK, HIGH);
    bitDelay();
    digitalWrite(TM_CLK, LOW);
    bitDelay();
    pinMode(TM_DIO, OUTPUT);
    digitalWrite(TM_DIO, HIGH);
}

void Display::setBrightness(byte b) {
    start();
    writeByte(0x88 | (b & 0x07));
    stop();
}

void Display::writeDigits(byte a, byte b, byte c, byte d) {
    start();
    writeByte(0x40); // 自动地址递增
    stop();
    start();
    writeByte(0xC0); // 地址 0
    writeByte(a);
    writeByte(b);
    writeByte(c);
    writeByte(d);
    stop();
    setBrightness(7);
}

void Display::showClock(byte h, byte m) {
    byte d0 = segOf(h / 10);
    byte d1 = segOf(h % 10) | 0x80; // 冒号
    byte d2 = segOf(m / 10);
    byte d3 = segOf(m % 10);
    writeDigits(d0, d1, d2, d3);
}

void Display::showNumber(int value) {
    _hasTime = false;
    if (value < 0) {
        int a = -value;
        if (a > 999) a = 999;
        writeDigits(SEG_MINUS, segOf(a / 100), segOf((a / 10) % 10), segOf(a % 10));
    } else {
        if (value > 9999) value = 9999;
        writeDigits(segOf(value / 1000), segOf((value / 100) % 10),
                    segOf((value / 10) % 10), segOf(value % 10));
    }
}

void Display::showTime(byte hour, byte minute) {
    if (hour > 23 || minute > 59) return;
    _hour = hour;
    _minute = minute;
    _hasTime = true;
    showClock(hour, minute);
    _lastRefresh = millis();
}

void Display::clear() {
    _hasTime = false;
    writeDigits(0x00, 0x00, 0x00, 0x00);
}

void Display::update() {
    if (!_hasTime) return;
    unsigned long now = millis();
    if (now - _lastRefresh >= 1000UL) {
        _lastRefresh = now;
        showClock(_hour, _minute);
    }
}
