#include "OledCarousel.h"
#include "../drivers/OLEDDisplay.h"
#include <string.h>
#include <avr/pgmspace.h>

// ============================================
// OLED 多页轮播（B 板本地渲染，V2.12）
// ============================================
// 页面模板与固定文案全部放 flash（PROGMEM），经 strncpy_P/snprintf_P 拷进
// 17B 栈缓冲后再交给 OLEDDisplay::showText()。Uno 仅 2KB RAM，普通字面量
// 会进 .data 并在启动时拷进 RAM，故此处一律走 flash。
// ============================================

// 页标题
static const char T_ENV[]  PROGMEM = "= ENVIRONMENT =";
static const char T_DEV[]  PROGMEM = "= DEVICES =";
static const char T_SAFE[] PROGMEM = "= SAFETY =";

// Safety 页的状态词
static const char S_ON[] PROGMEM = "ON";
static const char S_OK[] PROGMEM = "OK";

// Safety 页四行标签
static const char L_SMOKE[] PROGMEM = "Smoke";
static const char L_RAIN[]  PROGMEM = "Rain";
static const char L_TOUCH[] PROGMEM = "Touch";
static const char L_PIR[]   PROGMEM = "PIR";

static const char* const SAFE_LABELS[4] = { L_SMOKE, L_RAIN, L_TOUCH, L_PIR };
static const uint8_t SAFE_MASKS[4] = {
    OLED_FLAG_SMOKE, OLED_FLAG_RAIN, OLED_FLAG_TOUCH, OLED_FLAG_MOTION,
};

void OledCarousel::begin() {
    _page = 0;
    _begun = false;
    _nextUpdate = 0;      // 首次 update() 立即渲染并拉取
    _reqSeq = 0;
    _reqId = 0;
    _dataFresh = false;
    _data.temp10 = OLED_DATA_NULL;
    _data.hum10 = OLED_DATA_NULL;
    _data.light = 0;
    _data.flags = 0;
    _data.valid = false;
}

void OledCarousel::applyData(const OledData& data) {
    _data = data;
    if (data.valid) _dataFresh = true;   // 首帧/新帧到达，待补渲染当前页
}

bool OledCarousel::update(unsigned long now, const LocalState& local, OLEDDisplay& oled) {
    if (now >= _nextUpdate) {
        if (_begun) _page = (uint8_t)((_page + 1) % PAGE_COUNT);
        _begun = true;
        render(_page, local, oled);
        _nextUpdate = now + PAGE_INTERVAL_MS;
        _reqId = ++_reqSeq;              // 生成新请求 id，拒绝陈旧回帧
        return true;                     // 本拍需向香橙派拉取下一次数据
    }

    // 未到期：首帧数据刚落地时，不推进页码就地补渲染一次，
    // 避免上电后首页长时间显示 "--"。
    if (_dataFresh && _data.valid) {
        _dataFresh = false;
        render(_page, local, oled);
    }
    return false;
}

void OledCarousel::render(uint8_t page, const LocalState& local, OLEDDisplay& oled) {
    switch (page) {
        case 0:  renderEnvironment(oled);         break;
        case 1:  renderDevices(local, oled);      break;
        default: renderSafety(oled);              break;
    }
}

void OledCarousel::renderEnvironment(OLEDDisplay& oled) {
    char buf[17];

    strncpy_P(buf, T_ENV, sizeof(buf));
    oled.showText(0, buf);

    // 温度
    if (_data.temp10 == OLED_DATA_NULL) {
        strncpy_P(buf, PSTR("Temp: --"), sizeof(buf));
    } else if (_data.temp10 < 0) {
        int t = -_data.temp10;
        snprintf_P(buf, sizeof(buf), PSTR("Temp: -%d.%dC"), t / 10, t % 10);
    } else {
        snprintf_P(buf, sizeof(buf), PSTR("Temp: %d.%dC"), _data.temp10 / 10, _data.temp10 % 10);
    }
    oled.showText(1, buf);

    // 湿度
    if (_data.hum10 == OLED_DATA_NULL) {
        strncpy_P(buf, PSTR("Hum: --"), sizeof(buf));
    } else if (_data.hum10 < 0) {
        int h = -_data.hum10;
        snprintf_P(buf, sizeof(buf), PSTR("Hum: -%d.%d%%"), h / 10, h % 10);
    } else {
        snprintf_P(buf, sizeof(buf), PSTR("Hum: %d.%d%%"), _data.hum10 / 10, _data.hum10 % 10);
    }
    oled.showText(2, buf);

    // 光照原始值（0~1023）
    snprintf_P(buf, sizeof(buf), PSTR("Light: %u"), (unsigned)_data.light);
    oled.showText(3, buf);

    for (byte l = 4; l < 8; l++) oled.clearLine(l);
}

void OledCarousel::renderDevices(const LocalState& local, OLEDDisplay& oled) {
    char buf[17];

    strncpy_P(buf, T_DEV, sizeof(buf));
    oled.showText(0, buf);

    // 门：全部取 B 板本地执行器状态，不经香橙派
    strncpy_P(buf, local.doorOpen ? PSTR("Door: open") : PSTR("Door: closed"), sizeof(buf));
    oled.showText(1, buf);

    // 窗：0=normal, 1=closed, 2=open
    const char* ws;
    switch (local.windowState) {
        case 1:  ws = PSTR("Wind: closed"); break;
        case 2:  ws = PSTR("Wind: open");   break;
        default: ws = PSTR("Wind: normal"); break;
    }
    strncpy_P(buf, ws, sizeof(buf));
    oled.showText(2, buf);

    // 风扇：0=停，>0 显示当前速度
    if (local.fanSpeed > 0) {
        snprintf_P(buf, sizeof(buf), PSTR("Fan: %d"), local.fanSpeed);
    } else {
        strncpy_P(buf, PSTR("Fan: off"), sizeof(buf));
    }
    oled.showText(3, buf);

    for (byte l = 4; l < 8; l++) oled.clearLine(l);
}

void OledCarousel::renderSafety(OLEDDisplay& oled) {
    char buf[17];

    strncpy_P(buf, T_SAFE, sizeof(buf));
    oled.showText(0, buf);

    for (byte i = 0; i < 4; i++) {
        bool on = _data.valid && (_data.flags & SAFE_MASKS[i]);
        snprintf_P(buf, sizeof(buf), PSTR("%S: %S"),
                   SAFE_LABELS[i], on ? S_ON : S_OK);
        oled.showText((byte)(1 + i), buf);
    }

    for (byte l = 5; l < 8; l++) oled.clearLine(l);
}