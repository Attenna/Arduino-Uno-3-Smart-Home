#include "SensorManager.h"
#include "../Config.h"

void SensorManager::begin() {
    _dht.begin();
    _ultrasonic.begin();
    _touch.begin();
    _light.begin();
    _smoke.begin();
    _rain.begin();
    _ir.begin();
    _rfid.begin();
    _pir.begin();
    _soil.begin();

    _baselineReady = false;
    _prevTouch = false;
    _prevSmoke = false;
    _prevRain = false;
    _prevPir = false;
    _prevSoil = false;
    _lastTouchPush = 0;
    _lastSmokePush = 0;
    _lastRainPush = 0;
    _lastPirPush = 0;
    _lastSoilPush = 0;
}

void SensorManager::readAll() {
    _dht.read();
    _ultrasonic.read();
    _touch.read();
    _light.read();
    _smoke.read();
    _rain.read();
    _ir.read();
    _rfid.read();
    _pir.read();
    _soil.read();

    // 首次读取后建立边沿检测基线，避免上电误报
    if (!_baselineReady) {
        _prevTouch = _touch.isPressed();
        _prevSmoke = _smoke.isAlarm();
        _prevRain  = _rain.isRaining();
        _prevPir   = _pir.isMotion();
        _prevSoil  = _soil.isDry();
        _baselineReady = true;
    }
}

float SensorManager::temperature() const { return _dht.getTemperature(); }
float SensorManager::humidity() const    { return _dht.getHumidity(); }
int   SensorManager::light() const       { return _light.getRaw(); }
bool  SensorManager::smoke() const       { return _smoke.isAlarm(); }
bool  SensorManager::rain() const        { return _rain.isRaining(); }
bool  SensorManager::touch() const       { return _touch.isPressed(); }
bool  SensorManager::motion() const      { return _pir.isMotion(); }
bool  SensorManager::soilDry() const     { return _soil.isDry(); }
int   SensorManager::soilMoisture() const{ return _soil.getMoisture(); }

int SensorManager::distance() const {
    float d = _ultrasonic.getDistanceCm();
    if (d < 0) return -1;
    return (int)(d + 0.5f);
}

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

    // ---- RFID ----
    if (_rfid.hasCard()) {
        strncpy(ev.uid, _rfid.getUidHex(), sizeof(ev.uid) - 1);
        ev.uid[sizeof(ev.uid) - 1] = '\0';
        _rfid.clearCard();
        ev.type = EVT_RFID;
        return true;
    }

    // ---- IR ----
    if (_ir.hasCode()) {
        ev.irProtocol = _ir.getProtocol();
        ev.irAddress  = _ir.getAddress();
        ev.irCommand  = _ir.getCommand();
        _ir.clearCode();
        ev.type = EVT_IR;
        return true;
    }

    return false;
}
