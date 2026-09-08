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
#define LIGHT_BRIGHTNESS    60
#define LIGHT_BOOT_ON       0   // 1=上电默认点亮（需独立供电，否则易欠压复位）, 0=上电熄灭
#define LIGHT_BOOT_LEVEL    20  // 上电点亮时的亮度 0~255（越小越省电）

// ---- 蜂鸣器 ----
#define BUZZER_PIN          9
#define BUZZER_ACTIVE_LOW   1   // 1=低电平触发（有源蜂鸣器低电平响）, 0=高电平触发
#define BUZZER_DEFAULT_OFF  1   // 1=上电默认关闭（静音）, 0=上电默认开启

// ---- TM1637 数码管 ----
#define TM_CLK              5
#define TM_DIO              6

// ---- 红外发射（V1221 / TSAL1221 940nm，38kHz NEC 协议）----
#define IR_TX_PIN           12

// ---- OLED（SPI 4 线接口）----
#define OLED_IS_SH1106      1   // 1=SH1106, 0=SSD1306
#define OLED_RES_PIN        15  // RES  → A1（D15）
#define OLED_DC_PIN         14  // DC   → A0（D14）
#define OLED_CS_PIN         10  // CS   → D10
// SCK=D13、MOSI(=SDA)=D11 为 Uno 硬件 SPI 固定引脚，无需在此定义

// ---- 设备标识 ----
#define BOARD_TYPE          "MODULE_B"
#define BOARD_ROLE          "OUTPUT_NODE"
#define FW_VERSION          "V2.0"

#endif // CONFIG_B_H
