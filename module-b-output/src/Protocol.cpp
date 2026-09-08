#include "Protocol.h"
#include "Config.h"
#include "core/CommandDispatcher.h"

void Protocol::begin(CommandDispatcher& dispatcher) {
    _dispatcher = &dispatcher;
    _pos = 0;
    Serial.begin(SERIAL_BAUD);
    // 等待 USB 串口就绪，最多 3 秒
    unsigned long start = millis();
    while (!Serial && millis() - start < 3000);
}

void Protocol::sendReady() {
    Serial.print(F("{\"module\":\"output\",\"type\":\"ready\",\"board\":\""));
    Serial.print(BOARD_TYPE);
    Serial.print(F("\",\"role\":\""));
    Serial.print(BOARD_ROLE);
    Serial.print(F("\",\"version\":\""));
    Serial.print(FW_VERSION);
    Serial.println(F("\"}"));
}

void Protocol::handleSerial() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            // 兼容 \n、\r、\r\n 三种行结束符
            if (_pos > 0) {
                _buf[_pos] = '\0';
                normalizeFullWidth();      // 全角引号/冒号/逗号 → 半角（内部会重算 _pos）
                _pos = 0;
                handleLine(_buf);
            }
        } else {
            if (_pos < sizeof(_buf) - 1) _buf[_pos++] = c;
        }
    }
}

// 把全角字符转成半角：解决从中文输入法/聊天软件复制命令时
// 引号被转成全角 “ ” 导致 deserializeJson 失败（parse_error）的问题
void Protocol::normalizeFullWidth() {
    byte w = 0;
    for (byte r = 0; r < _pos; r++) {
        byte b0 = (byte)_buf[r];
        if (r + 2 < _pos && b0 == 0xE2 && (byte)_buf[r + 1] == 0x80 &&
            ((byte)_buf[r + 2] == 0x9C || (byte)_buf[r + 2] == 0x9D)) {
            _buf[w++] = '"';      // “ ” → "
            r += 2;
        } else if (r + 2 < _pos && b0 == 0xEF && (byte)_buf[r + 1] == 0xBC &&
                   ((byte)_buf[r + 2] == 0x9A || (byte)_buf[r + 2] == 0x8C)) {
            _buf[w++] = ((byte)_buf[r + 2] == 0x9A) ? ':' : ',';   // ：→ :   ，→ ,
            r += 2;
        } else {
            _buf[w++] = _buf[r];
        }
    }
    _pos = w;
    _buf[_pos] = '\0';
}

void Protocol::handleLine(const char* line) {
    Command cmd;
    if (!_parser.parse(line, cmd)) {
        // JSON 解析失败 → 尝试旧文本命令（向后兼容）
        if (handleLegacy(line)) return;
        respondError("parse_error");
        // 回显收到的原始内容，方便排查引号/编码/格式问题
        Serial.print(F("[input] "));
        Serial.println(line);
        return;
    }

    // 系统命令
    if (strcmp(cmd.device, "system") == 0) {
        if (strcmp(cmd.action, "status") == 0) {
            char buf[96];
            _dispatcher->buildStatus(buf, sizeof(buf));
            Serial.println(buf);
            return;
        }
        if (strcmp(cmd.action, "who") == 0) {
            sendReady();
            return;
        }
        respondError("unknown_command");
        return;
    }

    if (_dispatcher->dispatch(cmd)) {
        respondOk(cmd.device, cmd.action);
    } else {
        respondError("unknown_command");
    }
}

void Protocol::respondOk(const char* device, const char* action) {
    Serial.print(F("{\"module\":\"output\",\"type\":\"response\",\"result\":\"ok\",\"cmd\":\""));
    Serial.print(device);
    Serial.print(F("\",\"action\":\""));
    Serial.print(action);
    Serial.println(F("\"}"));
}

void Protocol::respondError(const char* err) {
    Serial.print(F("{\"module\":\"output\",\"type\":\"response\",\"result\":\"error\",\"error\":\""));
    Serial.print(err);
    Serial.println(F("\"}"));
}

// ============================================
// 旧文本命令兼容（B:DOOR:OPEN / B:FAN:OFF ...）
// 仅映射"纯硬件动作"命令；ALARM/HOUSE 等业务命令不在此列。
// ============================================

static void upperInPlace(char* s) {
    for (byte i = 0; s[i]; i++) {
        if (s[i] >= 'a' && s[i] <= 'z') s[i] -= 32;
    }
}

static bool startsWith(const char* s, const char* prefix) {
    while (*prefix) {
        if (*s++ != *prefix++) return false;
    }
    return true;
}

bool Protocol::handleLegacy(const char* line) {
    char buf[64];
    strncpy(buf, line, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';
    upperInPlace(buf);

    char* p = buf;
    if (startsWith(p, "B:")) p += 2;
    else if (startsWith(p, "A:")) p += 2;
    if (p[0] == '\0') return false;

    // 查询
    if (strcmp(p, "STATUS") == 0) {
        char out[96];
        _dispatcher->buildStatus(out, sizeof(out));
        Serial.println(out);
        return true;
    }
    if (strcmp(p, "WHO") == 0) {
        sendReady();
        return true;
    }

    Command cmd;
    memset(&cmd, 0, sizeof(cmd));

    // 门
    if (strcmp(p, "DOOR:OPEN") == 0)       { strcpy(cmd.device, "door");   strcpy(cmd.action, "open"); }
    else if (strcmp(p, "DOOR:CLOSE") == 0) { strcpy(cmd.device, "door");   strcpy(cmd.action, "close"); }
    // 窗
    else if (strcmp(p, "WINDOW:OPEN") == 0)   { strcpy(cmd.device, "window"); strcpy(cmd.action, "open"); }
    else if (strcmp(p, "WINDOW:CLOSE") == 0)  { strcpy(cmd.device, "window"); strcpy(cmd.action, "close"); }
    else if (strcmp(p, "WINDOW:NORMAL") == 0) { strcpy(cmd.device, "window"); strcpy(cmd.action, "normal"); }
    // 风扇
    else if (strcmp(p, "FAN:ON") == 0)  { strcpy(cmd.device, "fan"); strcpy(cmd.action, "on"); }
    else if (strcmp(p, "FAN:OFF") == 0) { strcpy(cmd.device, "fan"); strcpy(cmd.action, "off"); }
    else if (startsWith(p, "FAN:"))     { strcpy(cmd.device, "fan"); strcpy(cmd.action, "set_speed"); cmd.value = atol(p + 4); }
    // 灯
    else if (strcmp(p, "LIGHT:ON") == 0 || strcmp(p, "LIGHT:WHITE") == 0) { strcpy(cmd.device, "light"); strcpy(cmd.action, "white"); cmd.value = 255; }
    else if (strcmp(p, "LIGHT:OFF") == 0)    { strcpy(cmd.device, "light"); strcpy(cmd.action, "off"); }
    else if (strcmp(p, "LIGHT:RED") == 0)    { strcpy(cmd.device, "light"); strcpy(cmd.action, "red"); }
    else if (strcmp(p, "LIGHT:GREEN") == 0)  { strcpy(cmd.device, "light"); strcpy(cmd.action, "green"); }
    else if (strcmp(p, "LIGHT:BLUE") == 0)   { strcpy(cmd.device, "light"); strcpy(cmd.action, "blue"); }
    else if (strcmp(p, "LIGHT:YELLOW") == 0) { strcpy(cmd.device, "light"); strcpy(cmd.action, "yellow"); }
    else if (strcmp(p, "LIGHT:PURPLE") == 0) { strcpy(cmd.device, "light"); strcpy(cmd.action, "purple"); }
    else if (strcmp(p, "LIGHT:CYAN") == 0)   { strcpy(cmd.device, "light"); strcpy(cmd.action, "cyan"); }
    else if (startsWith(p, "LIGHT:RGB:")) {
        strcpy(cmd.device, "light"); strcpy(cmd.action, "rgb");
        int r = 0, g = 0, b = 0;
        sscanf(p + 10, "%d,%d,%d", &r, &g, &b);
        cmd.r = r; cmd.g = g; cmd.b = b;
    }
    else if (startsWith(p, "LIGHT:")) { strcpy(cmd.device, "light"); strcpy(cmd.action, "white"); cmd.value = atol(p + 6); }
    // 蜂鸣器
    else if (strcmp(p, "BUZZER:ON") == 0)  { strcpy(cmd.device, "buzzer"); strcpy(cmd.action, "on"); }
    else if (strcmp(p, "BUZZER:OFF") == 0) { strcpy(cmd.device, "buzzer"); strcpy(cmd.action, "off"); }
    else if (startsWith(p, "BUZZER:BEEP:")) {
        strcpy(cmd.device, "buzzer"); strcpy(cmd.action, "beep");
        int c = 1, on = 200, off = 200;
        sscanf(p + 12, "%d:%d:%d", &c, &on, &off);
        cmd.count = c; cmd.onMs = on; cmd.offMs = off;
    }
    // 数码管时钟
    else if (startsWith(p, "TIME:")) {
        char t[5] = {0};
        strncpy(t, p + 5, 4);
        if (strlen(t) != 4 || !isDigit(t[0]) || !isDigit(t[1]) || !isDigit(t[2]) || !isDigit(t[3])) {
            return false;
        }
        strcpy(cmd.device, "display"); strcpy(cmd.action, "show_time");
        cmd.hour = (t[0] - '0') * 10 + (t[1] - '0');
        cmd.minute = (t[2] - '0') * 10 + (t[3] - '0');
    }
    // OLED 清屏 / 指定行文本
    else if (strcmp(p, "OLED:CLEAR") == 0) { strcpy(cmd.device, "oled"); strcpy(cmd.action, "clear"); }
    else if (startsWith(p, "OLED:SHOW:")) {
        strcpy(cmd.device, "oled"); strcpy(cmd.action, "show_text");
        char* q = p + 10;                    // 跳过 "OLED:SHOW:"
        cmd.line = atol(q);
        char* sep = strchr(q, ':');
        if (!sep) return false;
        // 文本从原始行（非大写副本）提取，保留原始大小写
        int off = (int)(sep - buf) + 1;
        strncpy(cmd.text, line + off, sizeof(cmd.text) - 1);
        cmd.text[sizeof(cmd.text) - 1] = '\0';
    }
    else {
        return false; // 非旧命令
    }

    cmd.valid = true;
    if (_dispatcher->dispatch(cmd)) {
        respondOk(cmd.device, cmd.action);
        return true;
    }
    return false;
}
