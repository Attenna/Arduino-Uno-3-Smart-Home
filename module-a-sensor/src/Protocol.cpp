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
#if ENABLE_ULTRASONIC
    Serial.print(F(",\"distance\":"));
    int d = s.distance();
    if (d < 0) Serial.print(F("null"));
    else Serial.print(d);
#endif
    Serial.print(F(",\"touch\":"));
    printBool(s.touch());
#if ENABLE_PIR
    Serial.print(F(",\"motion\":"));
    printBool(s.motion());
#endif
#if ENABLE_SOIL
    Serial.print(F(",\"soil_moisture\":"));
    Serial.print(s.soilMoisture());
    Serial.print(F(",\"soil_dry\":"));
    printBool(s.soilDry());
#endif
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
#if ENABLE_PIR
        case EVT_PIR_MOTION:
        case EVT_PIR_CLEAR:
            Serial.print(F("motion"));
            Serial.print(F("\",\"state\":"));
            printBool(e.state);
            break;
#endif
#if ENABLE_SOIL
        case EVT_SOIL_DRY:
        case EVT_SOIL_WET:
            Serial.print(F("soil"));
            Serial.print(F("\",\"state\":"));
            printBool(e.state);
            break;
#endif
#if ENABLE_RFID
        case EVT_RFID:
            Serial.print(F("rfid"));
            Serial.print(F("\",\"uid\":\""));
            Serial.print(e.uid);
            Serial.print(F("\""));
            break;
#endif
#if ENABLE_IR_RECV
        case EVT_IR:
            Serial.print(F("ir"));
            Serial.print(F("\",\"protocol\":"));
            Serial.print(e.irProtocol);
            Serial.print(F(",\"address\":"));
            Serial.print(e.irAddress);
            Serial.print(F(",\"command\":"));
            Serial.print(e.irCommand);
            break;
#endif
#if ENABLE_KEYPAD
        case EVT_KEYPAD:
            Serial.print(F("keypad"));
            Serial.print(F("\",\"key\":\""));
            Serial.print(e.key);
            Serial.print(F("\""));
            break;
#endif
        default:
            Serial.print(F("unknown"));
            break;
    }
    Serial.println(F("}"));
}

// ---------- 下行（可选） ----------
void Protocol::handleInput(SensorManager& s, LightOutput& light) {
    static char buf[160];
    static byte pos = 0;
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (pos > 0) {
                buf[pos] = '\0';
                pos = 0;
                processLine(buf, s, light);
            }
        } else {
            if (pos < sizeof(buf) - 1) buf[pos++] = c;
        }
    }
}

static long jsonLong(const char* line, const char* key, long fallback) {
    const char* p = strstr(line, key);
    if (!p) return fallback;
    p = strchr(p, ':');
    return p ? atol(p + 1) : fallback;
}

static bool jsonAction(const char* line, char* out, byte len) {
    const char* p = strstr(line, "\"action\"");
    if (!p || !(p = strchr(p, ':')) || !(p = strchr(p, '\"'))) return false;
    p++;
    byte i = 0;
    while (*p && *p != '\"' && i + 1 < len) out[i++] = *p++;
    out[i] = 0;
    return i > 0;
}

bool Protocol::processLightJson(char* line, LightOutput& light) {
    if (!strstr(line, "\"cmd\":\"light\"") && !strstr(line, "\"cmd\": \"light\"")) return false;
    char action[12] = {0};
    long id = jsonLong(line, "\"id\"", -1);
    bool ok = jsonAction(line, action, sizeof(action));
    int value = constrain(jsonLong(line, "\"value\"", 255), 0L, 255L);
    int count = constrain(jsonLong(line, "\"count\"", RGB_LED_COUNT), 1L, (long)RGB_LED_COUNT);
    if (ok && strcmp(action, "off") == 0) light.off();
    else if (ok && strcmp(action, "white") == 0) light.white(value, count);
    else if (ok && strcmp(action, "night") == 0) light.white(value, 2);
    else if (ok && strcmp(action, "red") == 0) light.rgb(255, 0, 0, value, count);
    else if (ok && strcmp(action, "green") == 0) light.rgb(0, 255, 0, value, count);
    else if (ok && strcmp(action, "blue") == 0) light.rgb(0, 0, 255, value, count);
    else if (ok && strcmp(action, "yellow") == 0) light.rgb(255, 180, 0, value, count);
    else if (ok && strcmp(action, "purple") == 0) light.rgb(160, 0, 255, value, count);
    else if (ok && strcmp(action, "cyan") == 0) light.rgb(0, 180, 255, value, count);
    else if (ok && (strcmp(action, "rgb") == 0 || strcmp(action, "pixels") == 0)) {
        light.rgb(jsonLong(line, "\"r\"", 0), jsonLong(line, "\"g\"", 0),
                  jsonLong(line, "\"b\"", 0), value, count);
    } else ok = false;
    Serial.print(F("{\"module\":\"sensor\",\"type\":\"response\",\"result\":\""));
    Serial.print(ok ? F("ok") : F("error"));
    Serial.print(F("\",\"cmd\":\"light\",\"action\":\""));
    Serial.print(action);
    Serial.print('"');
    if (id >= 0) { Serial.print(F(",\"id\":")); Serial.print(id); }
    Serial.print(F(",\"state\":{\"light\":")); Serial.print(light.level());
    Serial.print(F(",\"lit\":")); Serial.print(light.count());
    Serial.println(F("}}"));
    return true;
}

bool Protocol::processLightCompact(char* line, LightOutput& light) {
    if (line[0] != 'L' || line[1] != ',') return false;
    char* save = NULL;
    strtok_r(line, ",", &save);               // L
    char* action = strtok_r(NULL, ",", &save);
    char* fields[6];
    for (byte i = 0; i < 6; i++) fields[i] = strtok_r(NULL, ",", &save);
    if (!action || !fields[0] || !fields[1] || !fields[2] || !fields[3] ||
            !fields[4] || !fields[5]) return true;
    int value = constrain(atol(fields[0]), 0L, 255L);
    int r = constrain(atol(fields[1]), 0L, 255L);
    int g = constrain(atol(fields[2]), 0L, 255L);
    int b = constrain(atol(fields[3]), 0L, 255L);
    int count = constrain(atol(fields[4]), 1L, (long)RGB_LED_COUNT);
    long id = atol(fields[5]);
    bool ok = true;
    if (strcmp(action, "O") == 0) light.off();
    else if (strcmp(action, "W") == 0) light.white(value, count);
    else if (strcmp(action, "P") == 0) light.rgb(r, g, b, value, count);
    else ok = false;
    Serial.print(F("{\"module\":\"sensor\",\"type\":\"response\",\"result\":\""));
    Serial.print(ok ? F("ok") : F("error"));
    Serial.print(F("\",\"cmd\":\"light\",\"id\":")); Serial.print(id);
    Serial.print(F(",\"state\":{\"light\":")); Serial.print(light.level());
    Serial.print(F(",\"lit\":")); Serial.print(light.count());
    Serial.println(F("}}"));
    return true;
}

void Protocol::processLine(char* line, SensorManager& s, LightOutput& light) {
    trim(line);
    if (processLightCompact(line, light)) return;
    if (line[0] == '{' && processLightJson(line, light)) return;
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
