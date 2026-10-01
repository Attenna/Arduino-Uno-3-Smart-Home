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
    // 抢在一切初始化之前把蜂鸣器引脚拉到"静默"电平。
    // MCU 复位后所有引脚是高阻，而 Buzzer::begin() 排在 door/window/fan/light
    // 之后（第 5 个），这中间有几十毫秒到数秒的窗口；有源低电平蜂鸣器在高阻
    // 输入下会持续响（实测每次复位/刷机都会吵到人）。
    pinMode(BUZZER_PIN, OUTPUT);
    digitalWrite(BUZZER_PIN, BUZZER_ACTIVE_LOW ? HIGH : LOW);

    // 风扇两脚同理：复位后到 Fan::begin()（排在 door/window 之后）之间 D7/D8
    // 是高阻，半桥驱动器输入悬空时可能出现毫秒级误导通——表现为 B 板复位/
    // 欠压瞬间风扇自己"冲"一下。这里复位后第一时间锁成 OUTPUT+LOW（停转）。
    pinMode(FAN_INA, OUTPUT);
    pinMode(FAN_INB, OUTPUT);
    digitalWrite(FAN_INA, LOW);
    digitalWrite(FAN_INB, LOW);

    dispatcher.begin();
    protocol.begin(dispatcher);
    protocol.sendReady();
}

void loop() {
    protocol.handleSerial();  // 处理下行命令
    dispatcher.update();      // 舵机释放 / 蜂鸣 / 数码管刷新
}
