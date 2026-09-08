#ifndef SENSOR_MANAGER_H
#define SENSOR_MANAGER_H

#include <Arduino.h>
#include "../sensors/DHTSensor.h"
#include "../sensors/UltrasonicSensor.h"
#include "../sensors/TouchSensor.h"
#include "../sensors/LightSensor.h"
#include "../sensors/SmokeSensor.h"
#include "../sensors/RainSensor.h"
#include "../sensors/IRSensor.h"
#include "../sensors/RFIDSensor.h"
#include "../sensors/PIRSensor.h"
#include "../sensors/SoilSensor.h"

// 事件类型
enum EventType {
    EVT_NONE,
    EVT_TOUCH_PRESS,
    EVT_TOUCH_RELEASE,
    EVT_SMOKE_ALERT,
    EVT_SMOKE_CLEAR,
    EVT_RAIN_START,
    EVT_RAIN_CLEAR,
    EVT_PIR_MOTION,
    EVT_PIR_CLEAR,
    EVT_SOIL_DRY,
    EVT_SOIL_WET,
    EVT_RFID,
    EVT_IR
};

// 事件载体
struct Event {
    EventType type;
    bool state;         // touch / smoke / rain / pir / soil
    char uid[32];       // rfid
    uint16_t irProtocol;
    uint16_t irAddress;
    uint16_t irCommand;
};

// 传感器集合管理器
// 只负责：读取所有传感器 → 组织数据 → 交给 Protocol，不做业务判断。
class SensorManager {
public:
    void begin();
    void readAll();

    // 状态数据 getter（供 Protocol 生成周期上报）
    float temperature() const;
    float humidity() const;
    int   light() const;
    bool  smoke() const;
    bool  rain() const;
    int   distance() const;
    bool  touch() const;
    bool  motion() const;       // PIR
    bool  soilDry() const;      // 土壤干燥
    int   soilMoisture() const;

    // 事件轮询：每次消费一个事件，无事件返回 false
    bool pollEvent(Event& ev);

private:
    DHTSensor _dht;
    UltrasonicSensor _ultrasonic;
    TouchSensor _touch;
    LightSensor _light;
    SmokeSensor _smoke;
    RainSensor _rain;
    IRSensor _ir;
    RFIDSensor _rfid;
    PIRSensor _pir;
    SoilSensor _soil;

    // 边沿检测的上一状态
    bool _prevTouch;
    bool _prevSmoke;
    bool _prevRain;
    bool _prevPir;
    bool _prevSoil;
    bool _baselineReady;

    // 防抖时间戳
    unsigned long _lastTouchPush;
    unsigned long _lastSmokePush;
    unsigned long _lastRainPush;
    unsigned long _lastPirPush;
    unsigned long _lastSoilPush;
};

#endif
