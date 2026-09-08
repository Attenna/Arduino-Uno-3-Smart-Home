#ifndef COMMAND_DISPATCHER_H
#define COMMAND_DISPATCHER_H

#include <Arduino.h>
#include "CommandParser.h"
#include "../drivers/Door.h"
#include "../drivers/Window.h"
#include "../drivers/Fan.h"
#include "../drivers/Light.h"
#include "../drivers/Buzzer.h"
#include "../drivers/Display.h"
#include "../drivers/OLEDDisplay.h"
#include "../drivers/IR.h"

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
    Display _display;
    OLEDDisplay _oled;
    IR _ir;
};

#endif
