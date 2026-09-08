#ifndef RFID_SENSOR_H
#define RFID_SENSOR_H

#include <Arduino.h>
#include <MFRC522.h>

// RC522 RFID 读卡器
// 事件型：读到新卡后置 hasCard，由上层消费。
class RFIDSensor {
public:
    RFIDSensor();
    void begin();
    bool read();               // 轮询读卡，返回是否有新卡
    bool hasCard() const;      // 是否有待消费的新卡
    void clearCard();          // 消费新卡
    const char* getUidHex() const; // 大写十六进制，字节以空格分隔
private:
    MFRC522 _rfid;
    byte _uid[10];
    byte _uidLen;
    bool _hasCard;
    char _uidHex[32];

    void makeHex();
};

#endif
