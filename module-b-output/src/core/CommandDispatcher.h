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

private:
    Door _door;
    Window _window;
    Fan _fan;
    Light _light;
    Buzzer _buzzer;
#if ENABLE_TM1637
    Display _display;
#endif
    OLEDDisplay _oled;
#if ENABLE_IR_TX
    IR _ir;
#endif
};

#endif
