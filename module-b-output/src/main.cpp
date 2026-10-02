// ============================================
// Module B — Output Node（入口）
// ============================================
// 职责：只负责接收命令并执行硬件动作，不做任何业务判断。
//
// 数据流：Serial → Protocol → Parser → Dispatcher → Driver → Hardware
// 业务决策全部由 Orange Pi + Home Assistant 完成。
// ============================================

#include <Arduino.h>
#include <avr/wdt.h>
#include "Config.h"
#include "core/CommandDispatcher.h"
#include "Protocol.h"

CommandDispatcher dispatcher;
Protocol protocol;

void setup() {
    // 看门狗善后：先清掉「上次是看门狗复位」的标志并关掉 WDT，再往下初始化。
    // 不清 WDRF 的话，复位后该标志仍置位，会在 loop 还没跑起来时被反复复位
    // （表现为板子不停重启）；关掉则保证初始化阶段不会被自己打断。
    // 注：optiboot 引导前已清过 MCUSR，所以应用侧读不到复位原因（实测恒为 0），
    // 固件不再上报这个字段，避免给出恒为 unknown 的假信息。
    MCUSR = 0;
    wdt_disable();

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

    // 初始化全部完成后再使能看门狗：固件挂死 2 秒内自动复位重来，不再需要人工
    // 插拔。复位后执行器回固件默认，上位机侧已有「B 板复位→DB 对账」按硬件回读
    // 把状态拉回一致（见 PC_Test/web/hardware.py）。
    wdt_enable(WDTO_2S);
}

void loop() {
    wdt_reset();              // 喂狗：一次 loop 远快于 2s，正常时永不触发
    protocol.handleSerial();  // 处理下行命令
    dispatcher.update();      // 舵机释放 / 蜂鸣 / 数码管刷新
}
