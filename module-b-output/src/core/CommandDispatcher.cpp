#include "CommandDispatcher.h"
#include "../Config.h"

void CommandDispatcher::begin() {
    _door.begin();
    _window.begin();
    _fan.begin();
    _light.begin();
    _buzzer.begin();
    _display.begin();
    _oled.begin();
    _ir.begin();
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
    else if (strcmp(cmd.device, "display") == 0) {
        if (strcmp(cmd.action, "show_time") == 0)   { _display.showTime((byte)cmd.hour, (byte)cmd.minute); return true; }
        if (strcmp(cmd.action, "show_number") == 0) { _display.showNumber((int)cmd.value); return true; }
        if (strcmp(cmd.action, "clear") == 0)       { _display.clear(); return true; }
    }
    else if (strcmp(cmd.device, "oled") == 0) {
        if (strcmp(cmd.action, "show_text") == 0) { _oled.showText((byte)cmd.line, cmd.text); return true; }
        if (strcmp(cmd.action, "clear") == 0)    { _oled.clear(); return true; }
    }
    else if (strcmp(cmd.device, "ir") == 0) {
        if (strcmp(cmd.action, "send_nec") == 0) { _ir.sendNEC(cmd.code); return true; }
        if (strcmp(cmd.action, "repeat") == 0)  { _ir.sendNECRepeat();  return true; }
    }

    return false;
}

void CommandDispatcher::update() {
    _door.update();
    _window.update();
    _buzzer.update();
    _display.update();
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
