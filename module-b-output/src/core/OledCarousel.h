#ifndef OLED_CAROUSEL_H
#define OLED_CAROUSEL_H

#include <Arduino.h>

class OLEDDisplay;

// ============================================
// OLED 多页轮播（V2.12 起下移到 B 板固件）
// ============================================
// 显示逻辑（页面/排版）硬编码在本固件，数据由 B 板每 15s 主动向香橙派拉取。
// 只负责「组页 + 计时 + 渲染 + 缓存数据」：不碰 Serial，也不调用其它驱动
// （B 板本地执行器状态由 CommandDispatcher 汇总成 LocalState 传入）。
// ============================================

// 温度/湿度读取失败时的哨兵（来自紧凑帧的 -32768）
#define OLED_DATA_NULL      (-32768)

// 布尔位（紧凑帧 flags 字段）
#define OLED_FLAG_SMOKE     0x01
#define OLED_FLAG_RAIN      0x02
#define OLED_FLAG_TOUCH     0x04
#define OLED_FLAG_MOTION    0x08

// 来自香橙派的 A 板传感器快照（紧凑帧解析结果）
struct OledData {
    int16_t  temp10;    // 温度 ×10；OLED_DATA_NULL = 无值
    int16_t  hum10;     // 湿度 ×10；OLED_DATA_NULL = 无值
    uint16_t light;     // 光照原始值 0~1023
    uint8_t  flags;     // OLED_FLAG_* 组合
    bool     valid;     // 是否已收到过有效帧
};

// B 板本地执行器状态（Dispatcher 汇总传入，避免驱动互相调用）
struct LocalState {
    bool     doorOpen;
    uint8_t  windowState;   // 0=normal, 1=closed, 2=open
    int      fanSpeed;      // 0=停，>0=转
};

class OledCarousel {
public:
    static const uint8_t PAGE_COUNT = 3;
    static const unsigned long PAGE_INTERVAL_MS = 15000UL;   // 每页停留 15s

    void begin();

    // 每 loop 由 CommandDispatcher::update() 调用。
    // 到期则渲染当前页、切到下一页并返回 true（表示本拍需向香橙派拉取数据）；
    // 首帧数据到达时补渲染一次当前页（不推进页码）；其余时间只做一次 millis()
    // 比较，绝不阻塞，远快于看门狗窗口。
    bool update(unsigned long now, const LocalState& local, OLEDDisplay& oled);

    // 收到香橙派的紧凑数据帧后落地
    void applyData(const OledData& data);

    uint16_t lastReqId() const { return _reqId; }

private:
    void render(uint8_t page, const LocalState& local, OLEDDisplay& oled);
    void renderEnvironment(OLEDDisplay& oled);
    void renderDevices(const LocalState& local, OLEDDisplay& oled);
    void renderSafety(OLEDDisplay& oled);

    uint8_t       _page;
    bool          _begun;         // 是否已渲染过首页（决定到期时是否推进页码）
    unsigned long _nextUpdate;
    uint16_t      _reqSeq;
    uint16_t      _reqId;
    bool          _dataFresh;     // 首帧数据到达、待补渲染当前页
    OledData      _data;
};

#endif // OLED_CAROUSEL_H