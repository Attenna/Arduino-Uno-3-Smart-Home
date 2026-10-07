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

// 引脚方向位（1=OUTPUT）与输入寄存器位：自检用来暴露「引脚被外设改回 INPUT」
// （IR.cpp 记录过 D12 被 U8x8 的 SPI.begin() 抢走这类事故）。
uint8_t pinOutBit(uint8_t pin) {
    uint8_t port = digitalPinToPort(pin);
    if (port == NOT_A_PIN) return 0;
    return (*(portModeRegister(port)) & digitalPinToBitMask(pin)) ? 1 : 0;
}

uint8_t pinInBit(uint8_t pin) {
    uint8_t port = digitalPinToPort(pin);
    if (port == NOT_A_PIN) return 0;
    return (*(portInputRegister(port)) & digitalPinToBitMask(pin)) ? 1 : 0;
}

} // namespace

void CommandDispatcher::begin() {
    _okCount = 0;
    _errCount = 0;
    _door.begin();
    _window.begin();
    _fan.begin();
    _light.begin();
    _buzzer.begin();
    _ultrasonic.begin();
#if ENABLE_TM1637
    _display.begin();
#endif
    _oled.begin();
#if ENABLE_IR_TX
    _ir.begin();
#endif
}

unsigned long CommandDispatcher::measureDistance() {
    return _ultrasonic.measure();
}

bool CommandDispatcher::dispatch(const Command& cmd) {
    bool ok = _route(cmd);
    if (ok) _okCount++; else _errCount++;
    return ok;
}

bool CommandDispatcher::_route(const Command& cmd) {
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
        // 夜灯：只点中间几颗；未带 value 时用 Config 里的 LIGHT_NIGHT_LEVEL
        if (strcmp(cmd.action, "night") == 0) {
            _light.night(cmd.hasValue ? (int)constrain(cmd.value, 0L, 255L) : LIGHT_NIGHT_LEVEL);
            return true;
        }
        // 色温：temp 是色温(K)，value 是亮度 0~255（缺省 255）
        if (strcmp(cmd.action, "temp") == 0) {
            _light.temp((int)constrain(cmd.temp, (long)LIGHT_TEMP_MIN, (long)LIGHT_TEMP_MAX),
                        cmd.hasValue ? (int)constrain(cmd.value, 0L, 255L) : 255);
            return true;
        }
        if (strcmp(cmd.action, "red") == 0)   { _light.red();    return true; }
        if (strcmp(cmd.action, "green") == 0) { _light.green();  return true; }
        if (strcmp(cmd.action, "blue") == 0)  { _light.blue();   return true; }
        if (strcmp(cmd.action, "yellow") == 0){ _light.yellow(); return true; }
        if (strcmp(cmd.action, "purple") == 0){ _light.purple(); return true; }
        if (strcmp(cmd.action, "cyan") == 0)  { _light.cyan();   return true; }
        // rgb 的 value 是整体亮度缩放 0~255，缺省 255（保持旧行为：按原色全亮）
        if (strcmp(cmd.action, "rgb") == 0) {
            _light.rgb((int)cmd.r, (int)cmd.g, (int)cmd.b,
                       cmd.hasValue ? (int)constrain(cmd.value, 0L, 255L) : 255);
            return true;
        }
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
    _fan.update();
    _buzzer.update();
#if ENABLE_TM1637
    _display.update();
#endif
}

void CommandDispatcher::buildStatus(char* buf, size_t len) {
    const char* winState =
        _window.getState() == 1 ? "closed" :
        _window.getState() == 2 ? "open" : "normal";

    // snprintf_P + PSTR：格式串放 flash。Uno 只有 2KB RAM，普通字面量会占 .data
    // 并在启动时拷进 RAM（这段约 95 字节，实测把栈顶到静态区导致固件跑飞）。
    snprintf_P(buf, len,
        PSTR("{\"module\":\"output\",\"type\":\"state\","
             "\"door\":\"%s\",\"window\":\"%s\",\"fan\":%d,"
             "\"light\":%d,\"buzzer\":\"%s\"}"),
        _door.isOpen() ? "open" : "closed",
        winState,
        _fan.getSpeed(),
        _light.getLevel(),
        _buzzer.isActive() ? "on" : "off");
}

// 状态字段直印 Serial（无中间缓冲）：供 response/ready 帧内嵌 "state":{...}，
// 让中间层在命令 ack 当场就能对比「命令意图 vs 固件实际」，不必等心跳。
void CommandDispatcher::printStateFields() {
    Serial.print(F("\"door\":\""));
    Serial.print(_door.isOpen() ? F("open") : F("closed"));
    Serial.print(F("\",\"window\":\""));
    Serial.print(_window.getState() == 1 ? F("closed") :
                 _window.getState() == 2 ? F("open") : F("normal"));
    Serial.print(F("\",\"fan\":"));
    Serial.print(_fan.getSpeed());
    Serial.print(F(",\"light\":"));
    Serial.print(_light.getLevel());
    Serial.print(F(",\"buzzer\":\""));
    Serial.print(_buzzer.isActive() ? F("on") : F("off"));
    Serial.print('"');
}

// 自检快照（system/selftest）。字段刻意做成「能区分故障在哪一层」：
//   d4[]  —— [方向位, 拉高读回, 拉低读回]；拉高读回是 0 说明数据脚被短路到 GND
//            或带载过重 → 二分「固件执行了」vs「引脚物理没信号」
//   pin[] —— 风扇两脚的 [方向位, 电平] × 2；方向位=0 说明又被外设抢成 INPUT
//   shows/reclaim —— 灯带 show() 实际调用次数 / 风扇引脚自愈次数（固件侧铁证）
void CommandDispatcher::printSelfTest() {
    int d4High = -1, d4Low = -1;
    _light.rawPinTest(&d4High, &d4Low);

    Serial.print(F("\"ok\":"));
    Serial.print((unsigned long)_okCount);
    Serial.print(F(",\"err\":"));
    Serial.print((unsigned long)_errCount);

    Serial.print(F(",\"fan\":{\"speed\":"));
    Serial.print(_fan.getSpeed());
    Serial.print(F(",\"reclaim\":"));
    Serial.print((unsigned)_fan.reclaimCount());
    Serial.print(F(",\"pin\":["));
    Serial.print((unsigned)pinOutBit(FAN_INA));
    Serial.print(',');
    Serial.print((unsigned)pinInBit(FAN_INA));
    Serial.print(',');
    Serial.print((unsigned)pinOutBit(FAN_INB));
    Serial.print(',');
    Serial.print((unsigned)pinInBit(FAN_INB));
    Serial.print(F("]}"));

    Serial.print(F(",\"light\":{\"level\":"));
    Serial.print(_light.getLevel());
    Serial.print(F(",\"bright\":"));
    Serial.print((unsigned)_light.stripBrightness());
    Serial.print(F(",\"shows\":"));
    Serial.print((unsigned)_light.showCount());
    // lit：最近一次点亮的灯珠数，0 = 整条（夜灯时会是 LIGHT_NIGHT_COUNT）
    Serial.print(F(",\"lit\":"));
    Serial.print((unsigned)_light.litCount());
    Serial.print(F(",\"d4\":["));
    Serial.print((unsigned)pinOutBit(RGB_PIN));
    Serial.print(',');
    Serial.print(d4High);
    Serial.print(',');
    Serial.print(d4Low);
    Serial.print(F("]}"));

    Serial.print(F(",\"buzzer\":\""));
    Serial.print(_buzzer.isActive() ? F("on") : F("off"));
    Serial.print('"');
}
