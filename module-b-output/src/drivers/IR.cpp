#include "IR.h"
#include "../Config.h"

// 38kHz 载波：周期 ≈ 26.3µs，1/3 占空比（高 9µs / 低 17µs）
#define IR_CARRIER_HIGH_US   9
#define IR_CARRIER_LOW_US    17

void IR::begin() {
    pinMode(IR_TX_PIN, OUTPUT);
    digitalWrite(IR_TX_PIN, LOW);  // 默认熄灭
}

void IR::carrier(unsigned int us) {
    unsigned long end = micros() + us;
    while (micros() < end) {
        digitalWrite(IR_TX_PIN, HIGH);
        delayMicroseconds(IR_CARRIER_HIGH_US);
        digitalWrite(IR_TX_PIN, LOW);
        delayMicroseconds(IR_CARRIER_LOW_US);
    }
}

void IR::sendNEC(unsigned long code) {
    // 引导码：9ms 载波 + 4.5ms 空闲
    carrier(9000);
    delayMicroseconds(4500);
    // 32 位数据，高位在前
    //   逻辑 1：560µs 载波 + 1690µs 空闲
    //   逻辑 0：560µs 载波 + 560µs 空闲
    for (byte i = 0; i < 32; i++) {
        if (code & 0x80000000UL) {
            carrier(560);
            delayMicroseconds(1690);
        } else {
            carrier(560);
            delayMicroseconds(560);
        }
        code <<= 1;
    }
    // 结束位
    carrier(560);
}

void IR::sendNECRepeat() {
    // 重复帧：9ms 载波 + 2.25ms 空闲 + 560µs 载波
    carrier(9000);
    delayMicroseconds(2250);
    carrier(560);
}
