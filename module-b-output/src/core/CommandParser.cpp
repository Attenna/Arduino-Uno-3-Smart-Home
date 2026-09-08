#include "CommandParser.h"
#include <ArduinoJson.h>

bool CommandParser::parse(const char* json, Command& cmd) {
    memset(&cmd, 0, sizeof(cmd));

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, json);
    if (err) return false;

    const char* device = doc["cmd"] | "";
    const char* action = doc["action"] | "";
    if (device[0] == '\0' || action[0] == '\0') return false;

    strncpy(cmd.device, device, sizeof(cmd.device) - 1);
    strncpy(cmd.action, action, sizeof(cmd.action) - 1);

    cmd.value  = doc["value"] | 0L;
    cmd.r      = doc["r"] | 0L;
    cmd.g      = doc["g"] | 0L;
    cmd.b      = doc["b"] | 0L;
    cmd.count  = doc["count"] | 1L;
    cmd.onMs   = doc["on_ms"] | 200L;
    cmd.offMs  = doc["off_ms"] | 200L;
    cmd.hour   = doc["hour"] | 0L;
    cmd.minute = doc["minute"] | 0L;
    cmd.line   = doc["line"] | 0L;
    cmd.code   = doc["code"] | 0UL;

    const char* text = doc["text"] | "";
    strncpy(cmd.text, text, sizeof(cmd.text) - 1);

    cmd.valid = true;
    return true;
}
