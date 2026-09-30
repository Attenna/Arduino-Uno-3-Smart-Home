#include "IR.h"
#include "../Config.h"

// 38kHz 载波：周期 ≈ 26.3µs，1/3 占空比（高 9µs / 低 17µs）
#define IR_CARRIER_HIGH_US   9
#define IR_CARRIER_LOW_US    17

namespace {
// D12 正好是 Uno 的硬件 SPI MISO 脚，而 OLED 是 U8x8 硬件 SPI（SCK=D13/MOSI=D11）：
// U8x8 的 BYTE_INIT 会调 SPI.begin()，而 AVR 的 SPI.begin() 会把 MISO(D12) 置回 INPUT。
// 一旦被改回 INPUT，carrier() 写这个脚就不会有任何输出 —— 表现为"指令 ACK 成功但红外
// 一点不发"。所以每次发射前都重新把引脚抢回 OUTPUT，而不是只在 begin() 里设一次。
inline void irPinReady() {
    pinMode(IR_TX_PIN, OUTPUT);
    digitalWrite(IR_TX_PIN, LOW);  // 空闲低电平=熄灭
}
} // namespace

void IR::begin() {
    irPinReady();
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
    irPinReady();
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
    irPinReady();
    // 重复帧：9ms 载波 + 2.25ms 空闲 + 560µs 载波
    carrier(9000);
    delayMicroseconds(2250);
    carrier(560);
}

// ============================================
// 美的 RN02G(X) 空调状态帧，需配合 PC_Test/midea_ac.py 使用
// ============================================
// 整帧 = 引导(4400/4400µs) + 48bit + 结束(500/5220µs)，**整帧重复 2 遍**。
// 48bit = 6 字节 [A, ~A, B, ~B, C, ~C]，三组互为逐位补码，**全部 MSB-first**。
// 数据来自香橙派 A 板红外接收头对真遥控器的抓取；与旧 RN02S13 的
// "B/C 低位先发 + 9 字节长帧" 完全不同，勿回退。

void IR::mideaLead() {
    carrier(MIDEA_LEAD_MARK);
    delayMicroseconds(MIDEA_LEAD_SPACE);
}

void IR::mideaStop() {
    carrier(MIDEA_STOP_MARK);
    delayMicroseconds(MIDEA_STOP_SPACE);
}

void IR::mideaByte(uint8_t value) {
    for (byte i = 0; i < 8; i++) {
        carrier(MIDEA_BIT_MARK);
        delayMicroseconds((value & 0x80) ? MIDEA_ONE_SPACE : MIDEA_ZERO_SPACE);
        value <<= 1;
    }
}

void IR::sendMideaFrame(const uint8_t* data, uint8_t len) {
    if (len < 3) return;
    irPinReady();
    for (byte r = 0; r < 2; r++) {
        mideaLead();
        mideaByte(data[0]);              // A
        mideaByte((uint8_t)~data[0]);    // ~A
        mideaByte(data[1]);              // B
        mideaByte((uint8_t)~data[1]);    // ~B
        mideaByte(data[2]);              // C
        mideaByte((uint8_t)~data[2]);    // ~C
        mideaStop();
    }
}
