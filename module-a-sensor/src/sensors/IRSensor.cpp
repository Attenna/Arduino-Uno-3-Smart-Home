#include "IRSensor.h"
#include "../Config.h"

// IRremote 配置宏必须在库头文件之前定义
#define IR_USE_AVR_TIMER1
// 本板只接收。IRremote 4.x 没有单独的「禁用发送」宏，定义 IR_SEND_PIN 只是把发送端
// 固定到该脚（IRsend 实例仍会编译进来）；业务代码不得调用 IrSender。
#define IR_SEND_PIN 0
#include <IRremote.hpp>

static IRrecv _irrecv(IR_RECV_PIN);

void IRSensor::begin() {
    _hasCode = false;
    _protocol = 0;
    _address = 0;
    _command = 0;
    _lastKey = 0xFFFFFFFFUL;
    _lastDecode = 0;
    _irrecv.enableIRIn();
}

bool IRSensor::read() {
    if (_hasCode) return true;
    if (!_irrecv.decode()) return false;

    // 先取解码结果再 resume
    uint16_t proto = _irrecv.decodedIRData.protocol;
    uint16_t addr  = _irrecv.decodedIRData.address;
    uint16_t cmd   = _irrecv.decodedIRData.command;
    uint8_t  flags = _irrecv.decodedIRData.flags;
    uint16_t bits  = _irrecv.decodedIRData.numberOfBits;
    _irrecv.resume();

    // 只接受可识别、非重复的短帧：
    //  - UNKNOWN/溢出是 decodeHash 对噪声和空调长帧的兜底，并不代表按了遥控器；
    //  - NEC 长按每 110ms 发一帧重复码，按新按键处理会让灯/风扇等反复切换；
    //  - >32 bit 基本是空调状态帧，本系统键位表只定义 NEC 遥控。
    bool repeat = (flags & (IRDATA_FLAGS_IS_REPEAT | IRDATA_FLAGS_IS_AUTO_REPEAT)) != 0;
    bool overflow = (flags & IRDATA_FLAGS_WAS_OVERFLOW) != 0;
    if (proto == UNKNOWN || overflow || bits > 32 || repeat) return false;

    // 按键级防抖：只压同一 (address, command) 的连发，1→2 快速连按不会丢第二个键。
    uint32_t key = ((uint32_t)addr << 16) | cmd;
    unsigned long now = millis();
    if (key == _lastKey && now - _lastDecode < DEBOUNCE_IR_MS) return false;
    _lastKey = key;
    _lastDecode = now;

    _protocol = proto;
    _address  = addr;
    _command  = cmd;
    _hasCode  = true;
    return true;
}

bool IRSensor::hasCode() const { return _hasCode; }
void IRSensor::clearCode() { _hasCode = false; }
uint16_t IRSensor::getProtocol() const { return _protocol; }
uint16_t IRSensor::getAddress() const  { return _address; }
uint16_t IRSensor::getCommand() const  { return _command; }
