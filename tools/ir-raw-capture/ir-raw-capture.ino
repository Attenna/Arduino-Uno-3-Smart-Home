// ============================================
// IR RAW 抓取器（诊断固件，临时烧录到 Module A 板）
// 用途：抓取真空调遥控器的原始红外时序，用于反推编码。
// 输出：串口 115200，每帧一行：
//   RAW|len=<n>|ovf=<0/1>|proto=<p>|ticks=<t1>,<t2>,...
//   单位 = 50µs tick，µs = tick * 50
// 注意：本固件不含任何传感器业务，抓完必须还原 module-a-sensor 生产固件。
// 依赖 IRremote 4.x（香橙派 ~/Arduino/libraries/IRremote 已装 4.4.1）
// ============================================
#define IR_USE_AVR_TIMER1
// 400 项 × uint16 = 800B RAM（Uno 2KB 可承受）。
// Midea 长帧约 3 段 × 147 项，400 足以捕获前两段完整（各段字节相同）。
#define RAW_BUFFER_LENGTH 400
#define IR_RECV_PIN 3
#include <IRremote.hpp>

void setup() {
    Serial.begin(115200);
    while (!Serial && millis() < 3000) {}
    IrReceiver.begin(IR_RECV_PIN, DISABLE_LED_FEEDBACK);
    Serial.println(F("IR_RAW_CAPTURE_READY"));
}

void loop() {
    if (IrReceiver.decode()) {
        // 默认实例解码后 rawDataPtr 始终指向 irparams（构造函数赋值）
        irparams_struct* r = IrReceiver.decodedIRData.rawDataPtr;
        Serial.print(F("RAW|len="));
        Serial.print((uint16_t)r->rawlen);
        Serial.print(F("|ovf="));
        Serial.print((IrReceiver.decodedIRData.flags & IRDATA_FLAGS_WAS_OVERFLOW) ? 1 : 0);
        Serial.print(F("|proto="));
        Serial.print(IrReceiver.decodedIRData.protocol);
        Serial.print(F("|ticks="));
        for (uint16_t i = 0; i < r->rawlen; i++) {
            Serial.print((uint16_t)r->rawbuf[i]);
            if (i + 1 < r->rawlen) Serial.print(',');
        }
        Serial.println();
        IrReceiver.resume();
    }
}
