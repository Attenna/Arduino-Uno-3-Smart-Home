#include "DHTSensor.h"
#include "../Config.h"
#include <DHT.h>
#include <math.h>

static DHT _dht(DHT_PIN, DHT_TYPE);

DHTSensor::DHTSensor()
    : _temperature(NAN), _humidity(NAN), _lastRead(0) {}

void DHTSensor::begin() {
    _dht.begin();
    // 首次预热读取（DHT11 首次读数常为 NAN）
    delay(100);
    float t = _dht.readTemperature();
    float h = _dht.readHumidity();
    if (!isnan(t)) _temperature = t;
    if (!isnan(h)) _humidity = h;
    _lastRead = millis();
}

bool DHTSensor::read() {
    unsigned long now = millis();
    if (now - _lastRead < DHT_INTERVAL_MS) {
        return !isnan(_temperature);
    }
    _lastRead = now;

    float t = _dht.readTemperature();
    float h = _dht.readHumidity();
    if (!isnan(t)) _temperature = t;
    if (!isnan(h)) _humidity = h;
    return !isnan(t) && !isnan(h);
}

float DHTSensor::getTemperature() const { return _temperature; }
float DHTSensor::getHumidity() const    { return _humidity; }
