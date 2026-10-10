#include "RFIDSensor.h"
#include "../Config.h"
#include <SPI.h>

RFIDSensor::RFIDSensor()
    : _rfid(RFID_SS_PIN, RFID_RST_PIN), _uidLen(0), _hasCard(false), _consecFails(0) {}

void RFIDSensor::begin() {
    SPI.begin();
    _rfid.PCD_Init();
    // 降低 SPI 频率，多传感器环境下更稳定
    SPI.beginTransaction(SPISettings(1000000, MSBFIRST, SPI_MODE0));
    _rfid.PCD_SetAntennaGain(RFID_ANTENNA_GAIN);
    _consecFails = 0;
}

bool RFIDSensor::read() {
    if (_hasCard) return true;
    if (!_rfid.PICC_IsNewCardPresent()) return false;

    // 原地重试：克隆 RC522 上 PICC_ReadCardSerial() 单次失败率很高，而失败的卡
    // 仍停在 READY 态（没有 HaltA），紧接着再选一次往往就成功。过去失败一次就
    // PCD_Reset() 并且直接放弃，等于让用户反复贴卡却经常什么都收不到。
    bool ok = false;
    for (byte attempt = 0; attempt < RFID_READ_ATTEMPTS && !ok; attempt++) {
        ok = _rfid.PICC_ReadCardSerial();
        if (!ok && attempt + 1 < RFID_READ_ATTEMPTS) delay(RFID_RETRY_GAP_MS);
    }
    if (!ok) {
        // 复位整颗芯片代价大（会丢天线配置），只在连续失败到阈值时做一次自愈，
        // 防止读卡器真的掉电/跑飞后永久读不到卡。
        if (++_consecFails >= RFID_RESET_AFTER_FAILS) {
            _consecFails = 0;
            _rfid.PCD_Reset();
            delay(10);
            _rfid.PCD_Init();
            _rfid.PCD_SetAntennaGain(RFID_ANTENNA_GAIN);
        }
        return false;
    }
    _consecFails = 0;

    _uidLen = _rfid.uid.size;
    for (byte i = 0; i < _uidLen && i < 10; i++) {
        _uid[i] = _rfid.uid.uidByte[i];
    }

    _rfid.PICC_HaltA();
    _rfid.PCD_StopCrypto1();

    makeHex();
    _hasCard = true;
    return true;
}

void RFIDSensor::makeHex() {
    byte p = 0;
    for (byte i = 0; i < _uidLen && i < 10; i++) {
        if (i > 0) _uidHex[p++] = ' ';
        sprintf(&_uidHex[p], "%02X", _uid[i]);
        p += 2;
    }
    _uidHex[p] = '\0';
}

bool RFIDSensor::hasCard() const { return _hasCard; }
void RFIDSensor::clearCard() { _hasCard = false; }
const char* RFIDSensor::getUidHex() const { return _uidHex; }
