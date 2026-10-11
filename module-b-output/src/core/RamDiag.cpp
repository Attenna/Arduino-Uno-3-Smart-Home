#include "RamDiag.h"

#include <Arduino.h>
#include <EEPROM.h>
#include <avr/io.h>

namespace {
// avr-libc 的堆边界：__brkval 非 0 时是堆顶，否则空堆，用 __heap_start（.bss 之后）。
extern "C" int __heap_start;
extern "C" char* __brkval;

const uint8_t PAINT = 0xC5;   // 哨兵值
const uint8_t MARGIN = 40;    // 涂色时给"本函数自己的栈帧"留的余量
const uint8_t RUN = 8;        // 连续这么多哨兵才算"没被压到"，躲开残迹里的偶然同值

// EEPROM（只放启动序号与"曾涂过色"的标志，都是 1 次/启动的写）
const int ADDR_MAGIC0 = 0;      // 'R'
const int ADDR_MAGIC1 = 1;      // 'D'
const int ADDR_VER = 2;         // 布局版本
const int ADDR_PAINTED = 3;     // 1 = 至少涂过一次色（区分"整窗被压穿"与"从未涂色"）
const int ADDR_BOOT = 6;        // uint16 启动序号
const uint8_t LAYOUT_VER = 2;

uint8_t* s_lo = nullptr;      // 涂色区低端（堆顶）
uint8_t* s_hi = nullptr;      // 涂色区高端（不含）
uint16_t s_hw = 0;            // 本次运行期栈高水位
uint16_t s_margin = 0;        // 栈最深点距堆顶的余量
uint16_t s_prev_hw = 0;       // 上一次运行期栈高水位
uint16_t s_boot = 0;
uint32_t s_last_ms = 0;

uint8_t* heapTop() {
    return reinterpret_cast<uint8_t*>(
        __brkval != nullptr ? __brkval
                            : reinterpret_cast<char*>(&__heap_start));
}

// 自上而下找"残迹/哨兵"的分界线。返回 true 时 *used 为栈用掉的字节数。
// 找不到分界线时：曾涂过色 ⇒ 整窗被压穿（*used = 整窗，*overrun = true）；
// 否则视为无证据（*used = 0）。
bool measureRegion(uint8_t* lo, uint8_t* hi, uint16_t* used, bool* overrun) {
    *used = 0;
    *overrun = false;
    if (hi <= lo) {
        return false;
    }
    bool painted_before = EEPROM.read(ADDR_MAGIC0) == 'R'
                          && EEPROM.read(ADDR_VER) == LAYOUT_VER
                          && EEPROM.read(ADDR_PAINTED) == 1;
    uint16_t paint_total = 0;
    uint8_t run = 0;
    uint8_t* run_top = nullptr;
    for (uint8_t* p = hi; p > lo; p--) {
        if (*(p - 1) == PAINT) {
            if (run == 0) {
                run_top = p - 1;
            }
            if (++run >= RUN) {
                *used = static_cast<uint16_t>(hi - run_top);
                return true;
            }
            if (++paint_total > 64) {
                break;              // 哨兵很多却凑不出连续 RUN：只可能是没涂过
            }
        } else {
            run = 0;
        }
    }
    if (painted_before) {
        *used = static_cast<uint16_t>(hi - lo);   // 整窗被压穿（或全被覆盖）
        *overrun = true;
        return true;
    }
    return false;
}

void refresh() {
    uint16_t used = 0;
    bool overrun = false;
    if (measureRegion(s_lo, s_hi, &used, &overrun)) {
        if (used > s_hw) {
            s_hw = used;
        }
        s_margin = overrun
                       ? 0
                       : static_cast<uint16_t>(s_hi - s_lo) - used;
    }
}
}  // namespace

namespace RamDiag {

void begin() {
    uint8_t* lo = heapTop();
    uint8_t* hi = reinterpret_cast<uint8_t*>(SP) - MARGIN;

    // 1) 先量上一次运行期的深度：此时 SRAM 里还留着它的哨兵与残迹（复位不清 SRAM），
    //    且本函数还没往那片区域压过栈（MARGIN 留出的余量就是给这里用的）。
    uint16_t used = 0;
    bool overrun = false;
    if (measureRegion(lo, hi, &used, &overrun)) {
        s_prev_hw = used;
    } else {
        s_prev_hw = 0;
    }

    // 2) 重新涂色：本次运行期的深度用同样的办法测，崩溃后由下一次启动读出来。
    if (hi > lo) {
        for (uint8_t* p = lo; p < hi; p++) {
            *p = PAINT;
        }
        s_lo = lo;
        s_hi = hi;
    } else {
        s_lo = nullptr;         // 余量太小：宁可不测，也不踩正在用的栈
        s_hi = nullptr;
    }
    s_hw = 0;
    s_margin = (s_hi != nullptr) ? static_cast<uint16_t>(s_hi - s_lo) : 0;
    s_last_ms = 0;

    // 3) EEPROM：标志 + 启动序号（各 1 次写；内容相同则 update 不实际写）
    if (EEPROM.read(ADDR_MAGIC0) != 'R' || EEPROM.read(ADDR_MAGIC1) != 'D'
            || EEPROM.read(ADDR_VER) != LAYOUT_VER) {
        EEPROM.write(ADDR_MAGIC0, 'R');
        EEPROM.write(ADDR_MAGIC1, 'D');
        EEPROM.write(ADDR_VER, LAYOUT_VER);
        EEPROM.put(ADDR_BOOT, static_cast<uint16_t>(0));
    }
    EEPROM.update(ADDR_PAINTED, 1);
    EEPROM.get(ADDR_BOOT, s_boot);
    if (s_boot == 0xFFFF) {
        s_boot = 0;
    }
    s_boot++;
    EEPROM.put(ADDR_BOOT, s_boot);
}

void update() {
    uint32_t now = millis();
    if (now - s_last_ms < 500) {   // 500ms 一次足够：哨兵会"记住"最深点
        return;
    }
    s_last_ms = now;
    refresh();
}

uint16_t stackHighWater() { return s_hw; }
uint16_t prevStackHighWater() { return s_prev_hw; }
uint16_t stackMargin() { return s_margin; }

uint16_t stackWindow() {
    return (s_lo != nullptr && s_hi > s_lo)
               ? static_cast<uint16_t>(s_hi - s_lo) : 0;
}

uint16_t freeRam() {
    uint16_t sp = SP;
    uint16_t heap = static_cast<uint16_t>(
        __brkval != nullptr ? reinterpret_cast<uint16_t>(__brkval)
                            : reinterpret_cast<uint16_t>(&__heap_start));
    return sp > heap ? static_cast<uint16_t>(sp - heap) : 0;
}

uint16_t bootCount() { return s_boot; }

}  // namespace RamDiag