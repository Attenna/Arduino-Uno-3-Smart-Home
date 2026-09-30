#ifndef IR_H
#define IR_H

#include <Arduino.h>

// V1221（TSAL1221）940nm 红外发射管，38kHz 载波
// 发射期间阻塞（时序要求严格，无法非阻塞）：NEC 约 68ms，美的长码约 250ms
class IR {
public:
    void begin();
    void sendNEC(unsigned long code);  // 发送完整 NEC 32 位码（地址+地址反码+命令+命令反码）
    void sendNECRepeat();             // 发送 NEC 重复帧（长按场景）
    // 发送美的 RN02G(X) 空调状态帧。data 为 3 字节 (A, B, C)，
    // 实际发 [A, ~A, B, ~B, C, ~C]（全 MSB-first）并整帧重复 2 遍。
    void sendMideaFrame(const uint8_t* data, uint8_t len);

private:
    void carrier(unsigned int us);    // 38kHz 载波，持续 us 微秒
    void mideaLead();
    void mideaStop();
    void mideaByte(uint8_t value);
};

#endif
