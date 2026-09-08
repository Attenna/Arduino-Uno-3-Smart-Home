#ifndef COMMAND_PARSER_H
#define COMMAND_PARSER_H

#include <Arduino.h>

// 解析后的命令结构（字段固定，便于 Dispatcher 分发）
struct Command {
    bool valid;
    char device[12];
    char action[20];
    long value;                 // fan 速度 / light 白亮度 / display 数字
    long r, g, b;               // light rgb
    long count, onMs, offMs;    // buzzer beep
    long hour, minute;          // display 时间
    long line;                  // oled 行号
    char text[24];              // oled 文本
    unsigned long code;         // ir NEC 码（32 位）
};

// 把 JSON 行解析为 Command 结构
class CommandParser {
public:
    bool parse(const char* json, Command& cmd);
};

#endif
