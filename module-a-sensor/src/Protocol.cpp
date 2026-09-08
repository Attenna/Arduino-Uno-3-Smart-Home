#include "Protocol.h"
#include "Config.h"
#include <math.h>

unsigned long Protocol::_interval = REPORT_INTERVAL_MS;

// ---------- 文件内工具 ----------
static void trim(char* s) {
    byte len = strlen(s);
    while (len > 0 && (s[len-1] == ' ' || s[len-1] == '\t' ||
                       s[len-1] == '\r' || s[len-1] == '\n')) {
        s[--len] = '\0';
    }
    char* p = s;
    while (*p == ' ' || *p == '\t') p++;
    if (p != s) memmove(s, p, strlen(p) + 1);
}

static void toUpper(char* s) {
    for (byte i = 0; s[i]; i++) {
        if (s[i] >= 'a' && s[i] <= 'z') s[i] -= 32;
    }
}

// ---------- 初始化 ----------
void Protocol::init() {
    Serial.begin(SERIAL_BAUD);
    // 等待 USB 串口就绪，最多 3 秒（避免无 PC 时永久阻塞）
    unsigned long start = millis();
    while (!Serial && millis() - start < 3000);
}

unsigned long Protocol::reportInterval() { return _interval; }

// ---------- 上行 ----------
void Protocol::printFloat(float v) {
    if (isnan(v)) Serial.print(F("null"));
    else Serial.print(v, 1);
}

void Protocol::printBool(bool v) {
    Serial.print(v ? F("true") : F("false"));
}

void Protocol::sendReport(const SensorManager& s) {
    Serial.print(F("{\"module\":\"sensor\",\"type\":\"data\",\"timestamp\":"));
    Serial.print((unsigned long)millis());
    Serial.print(F(",\"data\":{\"temperature\":"));
    printFloat(s.temperature());
    Serial.print(F(",\"humidity\":"));
    printFloat(s.humidity());
    Serial.print(F(",\"light\":"));
    Serial.print(s.light());
    Serial.print(F(",\"smoke\":"));
    printBool(s.smoke());
    Serial.print(F(",\"rain\":"));
    printBool(s.rain());
    Serial.print(F(",\"distance\":"));
    int d = s.distance();
    if (d < 0) Serial.print(F("null"));
    else Serial.print(d);
    Serial.print(F(",\"touch\":"));
    printBool(s.touch());
    Serial.print(F(",\"motion\":"));
    printBool(s.motion());
    Serial.print(F(",\"soil_moisture\":"));
    Serial.print(s.soilMoisture());
    Serial.print(F(",\"soil_dry\":"));
    printBool(s.soilDry());
    Serial.println(F("}}"));
}

void Protocol::sendEvent(const Event& e) {
    Serial.print(F("{\"module\":\"sensor\",\"type\":\"event\",\"event\":\""));
    switch (e.type) {
        case EVT_TOUCH_PRESS:
        case EVT_TOUCH_RELEASE:
            Serial.print(F("touch"));
            Serial.print(F("\",\"state\":"));
            printBool(e.state);
            break;
        case EVT_SMOKE_ALERT:
        case EVT_SMOKE_CLEAR:
            Serial.print(F("smoke"));
            Serial.print(F("\",\"state\":"));
            printBool(e.state);
            break;
        case EVT_RAIN_START:
        case EVT_RAIN_CLEAR:
            Serial.print(F("rain"));
            Serial.print(F("\",\"state\":"));
            printBool(e.state);
            break;
        case EVT_PIR_MOTION:
        case EVT_PIR_CLEAR:
            Serial.print(F("motion"));
            Serial.print(F("\",\"state\":"));
            printBool(e.state);
            break;
        case EVT_SOIL_DRY:
        case EVT_SOIL_WET:
            Serial.print(F("soil"));
            Serial.print(F("\",\"state\":"));
            printBool(e.state);
            break;
        case EVT_RFID:
            Serial.print(F("rfid"));
            Serial.print(F("\",\"uid\":\""));
            Serial.print(e.uid);
            Serial.print(F("\""));
            break;
        case EVT_IR:
            Serial.print(F("ir"));
            Serial.print(F("\",\"protocol\":"));
            Serial.print(e.irProtocol);
            Serial.print(F(",\"address\":"));
            Serial.print(e.irAddress);
            Serial.print(F(",\"command\":"));
            Serial.print(e.irCommand);
            break;
        default:
            Serial.print(F("unknown"));
            break;
    }
    Serial.println(F("}"));
}

// ---------- 下行（可选） ----------
void Protocol::handleInput(SensorManager& s) {
    static char buf[32];
    static byte pos = 0;
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (pos > 0) {
                buf[pos] = '\0';
                pos = 0;
                processLine(buf, s);
            }
        } else {
            if (pos < sizeof(buf) - 1) buf[pos++] = c;
        }
    }
}

void Protocol::processLine(char* line, SensorManager& s) {
    trim(line);
    toUpper(line);
    if (line[0] == '\0') return;

    if (strcmp(line, "REPORT") == 0 || strcmp(line, "STATUS") == 0) {
        sendReport(s);
    } else if (strncmp(line, "INTERVAL:", 9) == 0) {
        long v = atol(line + 9);
        if (v >= 200 && v <= 60000) {
            _interval = (unsigned long)v;
            Serial.print(F("{\"module\":\"sensor\",\"type\":\"response\",\"result\":\"ok\",\"interval\":"));
            Serial.print(_interval);
            Serial.println(F("}"));
        }
    } else if (strcmp(line, "WHO") == 0) {
        respondWho();
    }
    // 其它输入忽略
}

void Protocol::respondWho() {
    Serial.print(F("{\"module\":\"sensor\",\"type\":\"who\",\"board\":\""));
    Serial.print(BOARD_TYPE);
    Serial.print(F("\",\"role\":\""));
    Serial.print(BOARD_ROLE);
    Serial.print(F("\",\"version\":\""));
    Serial.print(FW_VERSION);
    Serial.println(F("\"}"));
}
