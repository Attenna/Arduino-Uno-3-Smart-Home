// ============================================
// Protocol — Module B 串口协议层
// ============================================
// 负责：Serial 读取 JSON 行 → CommandParser → CommandDispatcher
// 以及响应/状态的 JSON 序列化输出。
// 数据流：Serial → Protocol → Parser → Dispatcher → Driver → Hardware
// ============================================

#ifndef PROTOCOL_B_H
#define PROTOCOL_B_H

#include <Arduino.h>
#include "core/CommandParser.h"

class CommandDispatcher;

class Protocol {
public:
    void begin(CommandDispatcher& dispatcher);
    void handleSerial();
    void sendReady();

private:
    CommandDispatcher* _dispatcher;
    CommandParser _parser;
    char _buf[96];
    byte _pos;

    void handleLine(const char* line);
    void normalizeFullWidth();             // 全角引号/冒号/逗号 → 半角
    bool handleLegacy(const char* line);   // 旧文本命令兼容
    void respondOk(const char* device, const char* action);
    void respondError(const char* err);
};

#endif // PROTOCOL_B_H
