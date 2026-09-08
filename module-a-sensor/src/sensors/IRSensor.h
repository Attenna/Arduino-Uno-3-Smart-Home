#ifndef IR_SENSOR_H
#define IR_SENSOR_H

#include <Arduino.h>

// 红外遥控接收（IRremote 库）
// 事件型：解码到新码后置 hasCode，由上层消费。
class IRSensor {
public:
    void begin();
    bool read();              // 轮询解码，返回是否有新码
    bool hasCode() const;     // 是否有待消费的新码
    void clearCode();         // 消费新码
    uint16_t getProtocol() const;
    uint16_t getAddress() const;
    uint16_t getCommand() const;
private:
    bool _hasCode;
    uint16_t _protocol;
    uint16_t _address;
    uint16_t _command;
    unsigned long _lastDecode;
};

#endif
