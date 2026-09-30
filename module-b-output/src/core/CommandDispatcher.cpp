#include "CommandDispatcher.h"
#include "../Config.h"

namespace {

uint8_t hexNibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return 0xFF;
}

// 把 "B2FD0B..." 解析成字节数组；遇到非法字符即停止，返回解析出的字节数。
uint8_t hexToBytes(const char* hex, uint8_t* out, uint8_t maxLen) {
    uint8_t n = 0;
    while (hex[0] && hex[1] && n < maxLen) {
        uint8_t hi = hexNibble(hex[0]);
        uint8_t lo = hexNibble(hex[1]);
        if (hi == 0xFF || lo == 0xFF) break;
        out[n++] = (uint8_t)((hi << 4) | lo);
        hex += 2;
    }
    return n;
}

} // namespace

void CommandDispatcher::begin() {
    _door.begin();
    _window.begin();
    _fan.begin();
    _light.begin();
    _buzzer.begin();
#if ENABLE_TM1637
    _display.begin();
#endif
    _oled.begin();
#if ENABLE_IR_TX
    _ir.begin();
#endif
}

bool CommandDispatcher::dispatch(const Command& cmd) {
    if (!cmd.valid) return false;

    if (strcmp(cmd.device, "door") == 0) {
        if (strcmp(cmd.action, "open") == 0)  { _door.open();  return true; }
        if (strcmp(cmd.action, "close") == 0) { _door.close(); return true; }
    }
    else if (strcmp(cmd.device, "window") == 0) {
        if (strcmp(cmd.action, "open") == 0)   { _window.open();   return true; }
        if (strcmp(cmd.action, "close") == 0)  { _window.close();  return true; }
        if (strcmp(cmd.action, "normal") == 0) { _window.normal(); return true; }
    }
    else if (strcmp(cmd.device, "fan") == 0) {
        if (strcmp(cmd.action, "set_speed") == 0) { _fan.setSpeed((int)cmd.value); return true; }
        if (strcmp(cmd.action, "on") == 0 || strcmp(cmd.action, "full") == 0) { _fan.full(); return true; }
        if (strcmp(cmd.action, "off") == 0 || strcmp(cmd.action, "stop") == 0) { _fan.stop(); return true; }
    }
    else if (strcmp(cmd.device, "light") == 0) {
        if (strcmp(cmd.action, "off") == 0)   { _light.off();  return true; }
        if (strcmp(cmd.action, "white") == 0) { _light.white((int)cmd.value); return true; }
        if (strcmp(cmd.action, "red") == 0)   { _light.red();    return true; }
        if (strcmp(cmd.action, "green") == 0) { _light.green();  return true; }
        if (strcmp(cmd.action, "blue") == 0)  { _light.blue();   return true; }
        if (strcmp(cmd.action, "yellow") == 0){ _light.yellow(); return true; }
        if (strcmp(cmd.action, "purple") == 0){ _light.purple(); return true; }
        if (strcmp(cmd.action, "cyan") == 0)  { _light.cyan();   return true; }
        if (strcmp(cmd.action, "rgb") == 0)   { _light.rgb((int)cmd.r, (int)cmd.g, (int)cmd.b); return true; }
    }
    else if (strcmp(cmd.device, "buzzer") == 0) {
        if (strcmp(cmd.action, "on") == 0)   { _buzzer.on();  return true; }
        if (strcmp(cmd.action, "off") == 0)  { _buzzer.off(); return true; }
        if (strcmp(cmd.action, "beep") == 0) {
            _buzzer.beep((int)cmd.count, (unsigned long)cmd.onMs, (unsigned long)cmd.offMs);
            return true;
        }
    }
#if ENABLE_TM1637
    else if (strcmp(cmd.device, "display") == 0) {
        if (strcmp(cmd.action, "show_time") == 0)   { _display.showTime((byte)cmd.hour, (byte)cmd.minute); return true; }
        if (strcmp(cmd.action, "show_number") == 0) { _display.showNumber((int)cmd.value); return true; }
        if (strcmp(cmd.action, "clear") == 0)       { _display.clear(); return true; }
    }
#endif
    else if (strcmp(cmd.device, "oled") == 0) {
        if (strcmp(cmd.action, "show_text") == 0) { _oled.showText((byte)cmd.line, cmd.text); return true; }
        if (strcmp(cmd.action, "clear") == 0)    { _oled.clear(); return true; }
    }
#if ENABLE_IR_TX
    else if (strcmp(cmd.device, "ir") == 0) {
        if (strcmp(cmd.action, "send_nec") == 0) { _ir.sendNEC(cmd.code); return true; }
        if (strcmp(cmd.action, "repeat") == 0)  { _ir.sendNECRepeat();  return true; }
        if (strcmp(cmd.action, "send_midea") == 0) {
            // hex = 3 字节状态帧 (A,B,C)；~A/~B/~C 与整帧重复由驱动生成
            uint8_t bytes[3];
            if (hexToBytes(cmd.hex, bytes, sizeof(bytes)) != 3) return false;
            _ir.sendMideaFrame(bytes, 3);
            return true;
        }
    }
#endif

    return false;
}

void CommandDispatcher::update() {
    _door.update();
    _window.update();
    _buzzer.update();
#if ENABLE_TM1637
    _display.update();
#endif
}

void CommandDispatcher::buildStatus(char* buf, size_t len) {
    const char* winState =
        _window.getState() == 1 ? "closed" :
        _window.getState() == 2 ? "open" : "normal";

    snprintf(buf, len,
        "{\"module\":\"output\",\"type\":\"state\","
        "\"door\":\"%s\",\"window\":\"%s\",\"fan\":%d,"
        "\"light\":%d,\"buzzer\":\"%s\"}",
        _door.isOpen() ? "open" : "closed",
        winState,
        _fan.getSpeed(),
        _light.getLevel(),
        _buzzer.isActive() ? "on" : "off");
}
