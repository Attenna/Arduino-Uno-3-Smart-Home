#include "CommandParser.h"
#include <stdlib.h>
#include <string.h>

// ============================================
// 轻量 JSON 解析器（零堆分配）
// ============================================
// 背景：Uno 仅 2KB RAM。原实现使用 ArduinoJson 7 的
// JsonDocument，其变体池/字符串池完全依赖堆分配；
// 固件静态内存已占 ~81%，解析调用链上堆顶与栈指针
// 间距不足 malloc 安全边距，导致 deserializeJson 必然
// 返回 NoMemory —— 所有 JSON 命令报 parse_error。
//
// 本解析器只支持本协议用到的扁平单层对象：
//   {"cmd":"fan","action":"set_speed","value":180}
// 不支持嵌套对象/数组（协议中不存在），遇到即解析失败，
// 由上层 handleLegacy() 回退到冒号文本命令。
// ============================================

namespace {

void skipWs(const char*& p) {
    while (*p == ' ' || *p == '\t') p++;
}

// 解析 "..." 字符串到 out（支持简单转义），成功返回 true 且 p 移到闭引号之后。
// 超长内容截断存储，但会继续扫描到闭引号，保证后续字段不错位。
bool parseString(const char*& p, char* out, byte outSize) {
    if (*p != '"') return false;
    p++;
    byte n = 0;
    while (*p && *p != '"') {
        char c = *p++;
        if (c == '\\' && *p) {
            char e = *p++;
            switch (e) {
                case 'n': c = '\n'; break;
                case 't': c = '\t'; break;
                case 'r': c = '\r'; break;
                case 'b': c = '\b'; break;
                case 'f': c = '\f'; break;
                case 'u':  // \uXXXX：跳过 4 位 hex，以 '?' 代替
                    for (byte i = 0; i < 4 && *p; i++) p++;
                    c = '?';
                    break;
                default: c = e; break;  // \" \\ \/ 等
            }
        }
        if (n + 1 < outSize) out[n++] = c;
    }
    if (*p != '"') return false;  // 引号未闭合
    p++;
    out[n] = '\0';
    return true;
}

void assignString(Command& cmd, const char* key, const char* val) {
    if (strcmp(key, "cmd") == 0) {
        strncpy(cmd.device, val, sizeof(cmd.device) - 1);
    } else if (strcmp(key, "action") == 0) {
        strncpy(cmd.action, val, sizeof(cmd.action) - 1);
    } else if (strcmp(key, "text") == 0) {
        strncpy(cmd.text, val, sizeof(cmd.text) - 1);
    } else if (strcmp(key, "hex") == 0) {
        strncpy(cmd.hex, val, sizeof(cmd.hex) - 1);
    }
    // 其余字符串字段忽略
}

void assignNumber(Command& cmd, const char* key, unsigned long v) {
    if (strcmp(key, "value") == 0)       cmd.value = (long)v;
    else if (strcmp(key, "r") == 0)      cmd.r = (long)v;
    else if (strcmp(key, "g") == 0)      cmd.g = (long)v;
    else if (strcmp(key, "b") == 0)      cmd.b = (long)v;
    else if (strcmp(key, "count") == 0)  cmd.count = (long)v;
    else if (strcmp(key, "on_ms") == 0)  cmd.onMs = (long)v;
    else if (strcmp(key, "off_ms") == 0) cmd.offMs = (long)v;
    else if (strcmp(key, "hour") == 0)   cmd.hour = (long)v;
    else if (strcmp(key, "minute") == 0) cmd.minute = (long)v;
    else if (strcmp(key, "line") == 0)   cmd.line = (long)v;
    else if (strcmp(key, "code") == 0)   cmd.code = v;
    // 其余数字字段忽略
}

bool matchLiteral(const char*& p, const char* lit) {
    size_t n = strlen(lit);
    if (strncmp(p, lit, n) == 0) { p += n; return true; }
    return false;
}

} // namespace

bool CommandParser::parse(const char* json, Command& cmd) {
    memset(&cmd, 0, sizeof(cmd));
    // 与原 ArduinoJson 实现保持一致的缺省值
    cmd.count = 1;
    cmd.onMs = 200;
    cmd.offMs = 200;

    const char* p = json;
    skipWs(p);
    if (*p != '{') return false;
    p++;

    bool first = true;
    for (;;) {
        skipWs(p);
        if (*p == '}') { p++; break; }
        if (!first) {
            if (*p != ',') return false;
            p++;
            skipWs(p);
        }
        first = false;

        char key[12];
        if (!parseString(p, key, sizeof(key))) return false;

        skipWs(p);
        if (*p != ':') return false;
        p++;
        skipWs(p);

        if (*p == '"') {
            char val[24];
            if (!parseString(p, val, sizeof(val))) return false;
            assignString(cmd, key, val);
        } else if (*p == '-' || (*p >= '0' && *p <= '9')) {
            char* end;
            unsigned long v = strtoul(p, &end, 10);
            if (end == p) return false;
            p = end;
            assignNumber(cmd, key, v);
        } else if (matchLiteral(p, "true")) {
            assignNumber(cmd, key, 1);
        } else if (matchLiteral(p, "false") || matchLiteral(p, "null")) {
            assignNumber(cmd, key, 0);
        } else {
            return false;  // 嵌套对象/数组/非法值：不支持
        }
    }

    skipWs(p);
    if (*p != '\0') return false;  // 尾部垃圾

    if (cmd.device[0] == '\0' || cmd.action[0] == '\0') return false;
    cmd.valid = true;
    return true;
}
