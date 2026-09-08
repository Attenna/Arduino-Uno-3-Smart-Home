#include "RFIDSensor.h"
#include "../Config.h"
#include <SPI.h>

RFIDSensor::RFIDSensor()
    : _rfid(RFID_SS_PIN, RFID_RST_PIN), _uidLen(0), _hasCard(false) {}

void RFIDSensor::begin() {
    SPI.begin();
    _rfid.PCD_Init();
    // 降低 SPI 频率，多传感器环境下更稳定
    SPI.beginTransaction(SPISettings(1000000, MSBFIRST, SPI_MODE0));
    _rfid.PCD_SetAntennaGain(0x07);
}

bool RFIDSensor::read() {
    if (_hasCard) return true;
    if (!_rfid.PICC_IsNewCardPresent()) return false;
    if (!_rfid.PICC_ReadCardSerial()) {
        _rfid.PCD_Reset();
        delay(10);
        _rfid.PCD_Init();
        return false;
    }

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
