#ifndef SENSOR_MANAGER_H
#define SENSOR_MANAGER_H

#include <Arduino.h>
#include "../Config.h"
#include "../sensors/DHTSensor.h"
#if ENABLE_ULTRASONIC
#include "../sensors/UltrasonicSensor.h"
#endif
#include "../sensors/TouchSensor.h"
#include "../sensors/LightSensor.h"
#include "../sensors/SmokeSensor.h"
#include "../sensors/RainSensor.h"
#if ENABLE_IR_RECV
#include "../sensors/IRSensor.h"
#endif
#if ENABLE_RFID
#include "../sensors/RFIDSensor.h"
#endif
#if ENABLE_PIR
#include "../sensors/PIRSensor.h"
#endif
#if ENABLE_SOIL
#include "../sensors/SoilSensor.h"
#endif
#if ENABLE_KEYPAD
#include "../sensors/KeypadSensor.h"
#endif

// 事件类型
enum EventType {
    EVT_NONE,
    EVT_TOUCH_PRESS,
    EVT_TOUCH_RELEASE,
    EVT_SMOKE_ALERT,
    EVT_SMOKE_CLEAR,
    EVT_RAIN_START,
    EVT_RAIN_CLEAR,
#if ENABLE_PIR
    EVT_PIR_MOTION,
    EVT_PIR_CLEAR,
#endif
#if ENABLE_SOIL
    EVT_SOIL_DRY,
    EVT_SOIL_WET,
#endif
#if ENABLE_RFID
    EVT_RFID,
#endif
#if ENABLE_IR_RECV
    EVT_IR,
#endif
#if ENABLE_KEYPAD
    EVT_KEYPAD
#endif
};

// 事件载体
struct Event {
    EventType type;
    bool state;         // touch / smoke / rain / pir / soil
    char uid[32];       // rfid
    char key;           // keypad
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
#if ENABLE_ULTRASONIC
    int   distance() const;
#endif
    bool  touch() const;
#if ENABLE_PIR
    bool  motion() const;       // PIR
#endif
#if ENABLE_SOIL
    bool  soilDry() const;      // 土壤干燥
    int   soilMoisture() const;
#endif

    // 事件轮询：每次消费一个事件，无事件返回 false
    bool pollEvent(Event& ev);

private:
    DHTSensor _dht;
#if ENABLE_ULTRASONIC
    UltrasonicSensor _ultrasonic;
#endif
    TouchSensor _touch;
    LightSensor _light;
    SmokeSensor _smoke;
    RainSensor _rain;
#if ENABLE_IR_RECV
    IRSensor _ir;
#endif
#if ENABLE_RFID
    RFIDSensor _rfid;
#endif
#if ENABLE_PIR
    PIRSensor _pir;
#endif
#if ENABLE_SOIL
    SoilSensor _soil;
#endif
#if ENABLE_KEYPAD
    KeypadSensor _keypad;
#endif

    // 边沿检测的上一状态
    bool _prevTouch;
    bool _prevSmoke;
    bool _prevRain;
#if ENABLE_PIR
    bool _prevPir;
#endif
#if ENABLE_SOIL
    bool _prevSoil;
#endif
    bool _baselineReady;

    // 防抖时间戳
    unsigned long _lastTouchPush;
    unsigned long _lastSmokePush;
    unsigned long _lastRainPush;
#if ENABLE_PIR
    unsigned long _lastPirPush;
#endif
#if ENABLE_SOIL
    unsigned long _lastSoilPush;
#endif
};

#endif
