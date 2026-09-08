// ============================================
// Module A（Sensor Node）全局配置
// ============================================
// 所有引脚、阈值、时间间隔集中在此管理。
// 传感器驱动通过包含本文件获取引脚，不在驱动内部硬编码。
// ============================================

#ifndef CONFIG_A_H
#define CONFIG_A_H

// ---- 串口通信 ----
#define SERIAL_BAUD         115200

// ---- DHT11 温湿度 ----
#define DHT_PIN             7
#define DHT_TYPE            DHT11
#define DHT_INTERVAL_MS     2100    // DHT11 最小读取间隔

// ---- HC-SR04 超声波 ----
#define US_TRIG_PIN         A0
#define US_ECHO_PIN         A1
#define US_TIMEOUT_US       25000UL // 对应约 4m 量程
#define US_INTERVAL_MS      300
#define US_MIN_CM           2
#define US_MAX_CM           400

// ---- TTP223 触摸 ----
#define TOUCH_PIN           6

// ---- 光敏传感器（模拟）----
#define LIGHT_PIN           A5

// ---- MQ-2 烟雾（数字 + 模拟）----
#define SMOKE_DIGITAL_PIN   5
#define SMOKE_ANALOG_PIN    A3

// ---- 雨滴传感器（模拟）----
#define RAIN_ANALOG_PIN     A2
#define RAIN_THRESHOLD      500     // 低于此值视为有雨

// ---- PIR 人体红外（SR602 / HC-SR501）----
#define PIR_PIN             8

// ---- 土壤湿度（数字 + 模拟，兼容 YL-69/FC-28）----
#define SOIL_DIGITAL_PIN    4
#define SOIL_ANALOG_PIN     A4

// ---- 红外遥控接收 ----
#define IR_RECV_PIN         3

// ---- RC522 RFID ----
#define RFID_SS_PIN         10
#define RFID_RST_PIN        9
// D11=MOSI, D12=MISO, D13=SCK（SPI 硬件固定）

// ---- 周期上报 ----
#define REPORT_INTERVAL_MS  2000

// ---- 事件防抖 (ms) ----
#define DEBOUNCE_TOUCH_MS   300
#define DEBOUNCE_SMOKE_MS   1000
#define DEBOUNCE_RAIN_MS    3000
#define DEBOUNCE_IR_MS      500
#define DEBOUNCE_PIR_MS     5000
#define DEBOUNCE_SOIL_MS    2000

// ---- 设备标识 ----
#define BOARD_TYPE          "MODULE_A"
#define BOARD_ROLE          "SENSOR_NODE"
#define FW_VERSION          "V2.0"

#endif // CONFIG_A_H
