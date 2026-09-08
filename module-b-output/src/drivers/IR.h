#ifndef IR_H
#define IR_H

#include <Arduino.h>

// V1221（TSAL1221）940nm 红外发射管，NEC 协议 38kHz 载波
// 发射期间阻塞约 68ms（时序要求严格，无法非阻塞）
class IR {
public:
    void begin();
    void sendNEC(unsigned long code);  // 发送完整 NEC 32 位码（地址+地址反码+命令+命令反码）
    void sendNECRepeat();             // 发送 NEC 重复帧（长按场景）
private:
    void carrier(unsigned int us);    // 38kHz 载波，持续 us 微秒
};

#endif
