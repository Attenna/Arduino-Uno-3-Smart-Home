#ifndef COMMAND_DISPATCHER_H
#define COMMAND_DISPATCHER_H

#include <Arduino.h>
#include "../Config.h"
#include "CommandParser.h"
#include "../drivers/Door.h"
#include "../drivers/Window.h"
#include "../drivers/Fan.h"
#include "../drivers/Light.h"
#include "../drivers/Buzzer.h"
#include "../drivers/Ultrasonic.h"
#if ENABLE_TM1637
#include "../drivers/Display.h"
#endif
#include "../drivers/OLEDDisplay.h"
#if ENABLE_IR_TX
#include "../drivers/IR.h"
#endif

// 命令分发核心：{cmd, action, ...} → 对应驱动 → 执行
// 只做路由，不做业务判断，驱动之间不互相调用。
class CommandDispatcher {
public:
    void begin();
    bool dispatch(const Command& cmd);  // 返回命令是否被识别并执行
    void update();                       // 主循环调用
    void buildStatus(char* buf, size_t len);
    // 直接把状态字段打印到 Serial（无中间缓冲）。Uno 只有 2KB RAM，静态占用已
    // 近 8 成，任何 100+ 字节的栈上缓冲都可能把栈压进静态区，故统一走直印。
    void printStateFields();
    // 自检快照：命令成败计数 / 引脚方向与电平 / 灯带 show 次数，用于把
    // 「灯不亮 / 风扇自转」二分到 固件未执行 / 引脚被外设抢走 / 引脚物理短路。
    void printSelfTest();
    unsigned long measureDistance();  // Echo pulse duration, zero on timeout.

private:
    bool _route(const Command& cmd);     // 真正的路由，dispatch 外包一层计数
    uint32_t _okCount;
    uint32_t _errCount;
    Door _door;
    Window _window;
    Fan _fan;
    Light _light;
    Buzzer _buzzer;
    Ultrasonic _ultrasonic;
#if ENABLE_TM1637
    Display _display;
#endif
    OLEDDisplay _oled;
#if ENABLE_IR_TX
    IR _ir;
#endif
};

#endif
