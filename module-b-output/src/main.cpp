// ============================================
// Module B — Output Node（入口）
// ============================================
// 职责：只负责接收命令并执行硬件动作，不做任何业务判断。
//
// 数据流：Serial → Protocol → Parser → Dispatcher → Driver → Hardware
// 业务决策全部由 Orange Pi + Home Assistant 完成。
// ============================================

#include <Arduino.h>
#include "Config.h"
#include "core/CommandDispatcher.h"
#include "Protocol.h"

CommandDispatcher dispatcher;
Protocol protocol;

void setup() {
    dispatcher.begin();
    protocol.begin(dispatcher);
    protocol.sendReady();
}

void loop() {
    protocol.handleSerial();  // 处理下行命令
    dispatcher.update();      // 舵机释放 / 蜂鸣 / 数码管刷新
}
