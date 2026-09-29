#ifndef KEYPAD_SENSOR_H
#define KEYPAD_SENSOR_H

#include <Arduino.h>

// ============================================
// 矩阵键盘（正式版新增；替代已移除的土壤传感器接线）
// ============================================
// 当前硬件只接了 1 行 1 列，因此只有 "1" 键可用（开门密码 1111 = 连按 4 次）。
// 扫描方式：行引脚 KEYPAD_ROW_PIN 持续输出 LOW，列引脚 INPUT_PULLUP；
//           按下时行列短接，列被拉低。
// 固件只负责"一次完整按下锁存一次按键"，密码校验在香橙派 MCP 侧完成。
//
// 采样与取事件解耦（修复 readAll/pollEvent 双调用竞态）：
//   read()       仅采样去抖并【锁存】一次按下，幂等，可被多处周期调用；
//   takePress() 取走并清除一次锁存（只有事件循环调用，按键不会被采样吞掉）。
// ============================================
class KeypadSensor {
public:
    void begin();
    void read();          // 周期采样：去抖 + 锁存一次有效按下（幂等）
    bool takePress();     // 取走一次已锁存的按下事件（取后自动清除）
    char key() const;     // 当前接线恒返回 '1'

private:
    bool _armed;          // 是否已松开并保持足够时间，可触发下一次
    bool _level;          // 防抖后的稳定电平：true=高(未按) false=低(按下)
    bool _latched;        // 已锁存、等待 takePress 取走的按下
    unsigned long _changeMs;
};

#endif
