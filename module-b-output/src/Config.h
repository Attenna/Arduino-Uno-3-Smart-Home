// ============================================
// Module B（Output Node）全局配置
// ============================================
// 所有引脚、角度、时间参数集中在此管理。
// 驱动通过包含本文件获取引脚，不在驱动内部硬编码。
// ============================================

#ifndef CONFIG_B_H
#define CONFIG_B_H

// ---- 串口通信 ----
#define SERIAL_BAUD         115200

// ============================================
// 硬件裁剪开关（硬件小组 2026-09 正式版会议决定）
// ============================================
#define ENABLE_TM1637       0   // 四位数码管时钟单元已移除 → D5/D6 悬空（保持高阻）
#define ENABLE_IR_TX        1   // 红外发射（D12，NEC 38kHz）保留

// ---- 舵机 ----
#define DOOR_SERVO_PIN      2
#define WINDOW_SERVO_PIN    3
#define DOOR_CLOSED_ANGLE   0
#define DOOR_OPEN_ANGLE     90
#define WINDOW_CLOSED_ANGLE 0
#define WINDOW_NORMAL_ANGLE 45
#define WINDOW_OPEN_ANGLE   120
#define SERVO_SETTLE_TIME   700UL  // 舵机运动后释放引脚的时间 (ms)

// ---- 风扇（INA/INB，D8/D7 均非 PWM 引脚，退化为开关控制）----
#define FAN_INA             8   // A 信号（开关控制）
#define FAN_INB             7   // B 信号（方向）

// ---- RGB 灯带（NeoPixel）----
#define RGB_PIN             4
#define LED_COUNT           8
#define LIGHT_BRIGHTNESS    255  // 灯带全局亮度上限：NeoPixel 的 setBrightness 会再乘一次，
                                 // 60 会把 255 缩成约 24% 输出（8 颗灯珠暗到看着像没亮）
#define LIGHT_BOOT_ON       0   // 1=上电默认点亮（需独立供电，否则易欠压复位）, 0=上电熄灭
#define LIGHT_BOOT_LEVEL    20  // 上电点亮时的亮度 0~255（越小越省电）

// 夜灯（night）：只点亮居中的几颗灯珠，其余保持熄灭，避免整条灯带当小夜灯晃眼
#define LIGHT_NIGHT_COUNT   2   // 夜灯点亮的灯珠数量（居中对齐，超过 LED_COUNT 时按整条处理）
#define LIGHT_NIGHT_LEVEL   60  // 夜灯缺省亮度 0~255（未带 value 时用）

// 色温（temp）可调范围，单位 K
#define LIGHT_TEMP_MIN      2700
#define LIGHT_TEMP_MAX      6500

// ---- 蜂鸣器 ----
#define BUZZER_PIN          9
#define BUZZER_ACTIVE_LOW   1   // 1=低电平触发（有源蜂鸣器低电平响）, 0=高电平触发
#define BUZZER_DEFAULT_OFF  1   // 1=上电默认关闭（静音）, 0=上电默认开启

// ---- TM1637 数码管 ----
#define TM_CLK              5
#define TM_DIO              6

// ---- 红外发射（V1221 / TSAL1221 940nm，38kHz NEC 协议）----
#define IR_TX_PIN           12

// ---- 美的空调长码时序（移植自 IRsendMeidi 参考库，38kHz 载波）----
// 位 1 = 500µs 载波 + 1600µs 空闲；位 0 = 500µs 载波 + 550µs 空闲
// 引导 = 4400µs 载波 + 4400µs 空闲；结尾 = 500µs 载波 + 5220µs 空闲
#define MIDEA_LEAD_MARK     4400
#define MIDEA_LEAD_SPACE    4400
#define MIDEA_BIT_MARK      500
#define MIDEA_ONE_SPACE     1600
#define MIDEA_ZERO_SPACE    550
#define MIDEA_STOP_MARK     500
#define MIDEA_STOP_SPACE    5220

// ---- OLED（SPI 4 线接口）----
#define OLED_IS_SH1106      1   // 1=SH1106, 0=SSD1306
#define OLED_RES_PIN        15  // RES  → A1（D15）
#define OLED_DC_PIN         14  // DC   → A0（D14）
#define OLED_CS_PIN         10  // CS   → D10
// SCK=D13、MOSI(=SDA)=D11 为 Uno 硬件 SPI 固定引脚，无需在此定义

// ---- 设备标识 ----
#define BOARD_TYPE          "MODULE_B"
#define BOARD_ROLE          "OUTPUT_NODE"
#define FW_VERSION          "V2.9"  // V2.2 起红外支持美的长码；V2.3 修 D12(SPI MISO) 被 OLED 抢成 INPUT 导致发不出红外；V2.4 setup 开头提前锁死风扇 D7/D8；V2.5 风扇每 loop 引脚自愈（被外设改回 INPUT 时抢回并上报）；V2.6 响应回显请求 id，服务端可丢弃迟到响应；V2.7 看门狗 WDTO_2S；V2.8 灯带全局亮度 60→255（原来 255 会被缩成约 24%，看着像没亮）；V2.9 命令响应/就绪帧回附固件状态快照与复位原因，新增 system/selftest 自检

#endif // CONFIG_B_H
