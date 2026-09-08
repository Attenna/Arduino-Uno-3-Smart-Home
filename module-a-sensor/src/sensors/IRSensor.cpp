#include "IRSensor.h"
#include "../Config.h"

// IRremote 配置宏必须在库头文件之前定义
#define IR_USE_AVR_TIMER1
#define IR_SEND_PIN 0   // 本板只接收，禁用发送以节省资源
#include <IRremote.hpp>

static IRrecv _irrecv(IR_RECV_PIN);

void IRSensor::begin() {
    _hasCode = false;
    _protocol = 0;
    _address = 0;
    _command = 0;
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
    _irrecv.resume();

    unsigned long now = millis();
    if (now - _lastDecode < DEBOUNCE_IR_MS) return false; // 防连按
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
