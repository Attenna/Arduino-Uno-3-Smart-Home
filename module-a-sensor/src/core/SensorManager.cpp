#include "SensorManager.h"
#include "../Config.h"

void SensorManager::begin() {
    _dht.begin();
#if ENABLE_ULTRASONIC
    _ultrasonic.begin();
#endif
    _touch.begin();
    _light.begin();
    _smoke.begin();
    _rain.begin();
#if ENABLE_IR_RECV
    _ir.begin();
#endif
#if ENABLE_RFID
    _rfid.begin();
#endif
#if ENABLE_PIR
    _pir.begin();
#endif
#if ENABLE_SOIL
    _soil.begin();
#endif
#if ENABLE_KEYPAD
    _keypad.begin();
#endif

    _baselineReady = false;
    _prevTouch = false;
    _prevSmoke = false;
    _prevRain = false;
#if ENABLE_PIR
    _prevPir = false;
#endif
#if ENABLE_SOIL
    _prevSoil = false;
#endif
    _lastTouchPush = 0;
    _lastSmokePush = 0;
    _lastRainPush = 0;
#if ENABLE_PIR
    _lastPirPush = 0;
#endif
#if ENABLE_SOIL
    _lastSoilPush = 0;
#endif
}

void SensorManager::readAll() {
    _dht.read();
#if ENABLE_ULTRASONIC
    _ultrasonic.read();
#endif
    _touch.read();
    _light.read();
    _smoke.read();
    _rain.read();
#if ENABLE_IR_RECV
    _ir.read();
#endif
#if ENABLE_RFID
    _rfid.read();
#endif
#if ENABLE_PIR
    _pir.read();
#endif
#if ENABLE_SOIL
    _soil.read();
#endif
#if ENABLE_KEYPAD
    _keypad.read();
#endif

    // 首次读取后建立边沿检测基线，避免上电误报
    if (!_baselineReady) {
        _prevTouch = _touch.isPressed();
        _prevSmoke = _smoke.isAlarm();
        _prevRain  = _rain.isRaining();
#if ENABLE_PIR
        _prevPir   = _pir.isMotion();
#endif
#if ENABLE_SOIL
        _prevSoil  = _soil.isDry();
#endif
        _baselineReady = true;
    }
}

float SensorManager::temperature() const { return _dht.getTemperature(); }
float SensorManager::humidity() const    { return _dht.getHumidity(); }
int   SensorManager::light() const       { return _light.getRaw(); }
bool  SensorManager::smoke() const       { return _smoke.isAlarm(); }
bool  SensorManager::rain() const        { return _rain.isRaining(); }
bool  SensorManager::touch() const       { return _touch.isPressed(); }
#if ENABLE_PIR
bool  SensorManager::motion() const      { return _pir.isMotion(); }
#endif
#if ENABLE_SOIL
bool  SensorManager::soilDry() const     { return _soil.isDry(); }
int   SensorManager::soilMoisture() const{ return _soil.getMoisture(); }
#endif

#if ENABLE_ULTRASONIC
int SensorManager::distance() const {
    float d = _ultrasonic.getDistanceCm();
    if (d < 0) return -1;
    return (int)(d + 0.5f);
}
#endif

bool SensorManager::pollEvent(Event& ev) {
    ev.type = EVT_NONE;

    // ---- 触摸 ----
    bool t = _touch.isPressed();
    if (t != _prevTouch) {
        _prevTouch = t;
        if (millis() - _lastTouchPush >= DEBOUNCE_TOUCH_MS) {
            _lastTouchPush = millis();
            ev.type  = t ? EVT_TOUCH_PRESS : EVT_TOUCH_RELEASE;
            ev.state = t;
            return true;
        }
    }

    // ---- 烟雾 ----
    bool s = _smoke.isAlarm();
    if (s != _prevSmoke) {
        _prevSmoke = s;
        if (millis() - _lastSmokePush >= DEBOUNCE_SMOKE_MS) {
            _lastSmokePush = millis();
            ev.type  = s ? EVT_SMOKE_ALERT : EVT_SMOKE_CLEAR;
            ev.state = s;
            return true;
        }
    }

    // ---- 雨滴 ----
    bool r = _rain.isRaining();
    if (r != _prevRain) {
        _prevRain = r;
        if (millis() - _lastRainPush >= DEBOUNCE_RAIN_MS) {
            _lastRainPush = millis();
            ev.type  = r ? EVT_RAIN_START : EVT_RAIN_CLEAR;
            ev.state = r;
            return true;
        }
    }

#if ENABLE_PIR
    // ---- PIR 人体红外 ----
    bool m = _pir.isMotion();
    if (m != _prevPir) {
        _prevPir = m;
        if (millis() - _lastPirPush >= DEBOUNCE_PIR_MS) {
            _lastPirPush = millis();
            ev.type  = m ? EVT_PIR_MOTION : EVT_PIR_CLEAR;
            ev.state = m;
            return true;
        }
    }
#endif

#if ENABLE_SOIL
    // ---- 土壤湿度 ----
    bool sd = _soil.isDry();
    if (sd != _prevSoil) {
        _prevSoil = sd;
        if (millis() - _lastSoilPush >= DEBOUNCE_SOIL_MS) {
            _lastSoilPush = millis();
            ev.type  = sd ? EVT_SOIL_DRY : EVT_SOIL_WET;
            ev.state = sd;
            return true;
        }
    }
#endif

#if ENABLE_RFID
    // ---- RFID ----
    if (_rfid.hasCard()) {
        strncpy(ev.uid, _rfid.getUidHex(), sizeof(ev.uid) - 1);
        ev.uid[sizeof(ev.uid) - 1] = '\0';
        _rfid.clearCard();
        ev.type = EVT_RFID;
        return true;
    }
#endif

#if ENABLE_IR_RECV
    // ---- 红外遥控接收 ----
    if (_ir.hasCode()) {
        ev.irProtocol = _ir.getProtocol();
        ev.irAddress  = _ir.getAddress();
        ev.irCommand  = _ir.getCommand();
        _ir.clearCode();
        ev.type = EVT_IR;
        return true;
    }
#endif

#if ENABLE_KEYPAD
    // ---- 矩阵键盘（read 只锁存，takePress 才取事件，避免被 readAll 吞掉）----
    _keypad.read();
    if (_keypad.takePress()) {
        ev.type = EVT_KEYPAD;
        ev.key  = _keypad.key();
        return true;
    }
#endif

    return false;
}
