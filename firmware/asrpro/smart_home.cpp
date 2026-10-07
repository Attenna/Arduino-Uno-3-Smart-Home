// Tianwen Block AI: select ASRPRO, C++ mode; generate model, then compile/download.
#include "asr.h"
extern "C" { void * __dso_handle = 0; }
#include "setup.h"
#include "asr_event.h"
#include <stdio.h>
#include <string.h>

uint32_t snid;
static QueueHandle_t commands = NULL;
static volatile bool busy = false;
static unsigned long sequence = 0;

//{speak:小蝶-清新女声,vol:7,speed:10,platform:haohaodada}
//{playid:10001,voice:智能家居已启动，请用智能管家唤醒我}
//{playid:10002,voice:我先休息了}
//{ID:0,keyword:"唤醒词",ASR:"智能管家",ASRTO:"我在"}
//{ID:1,keyword:"命令词",ASR:"开灯",ASRTO:""}
//{ID:2,keyword:"命令词",ASR:"关灯",ASRTO:""}
//{ID:3,keyword:"命令词",ASR:"开门",ASRTO:""}
//{ID:4,keyword:"命令词",ASR:"开窗",ASRTO:""}
//{ID:5,keyword:"命令词",ASR:"开风扇",ASRTO:""}
//{ID:6,keyword:"命令词",ASR:"关风扇",ASRTO:""}
//{ID:7,keyword:"命令词",ASR:"当前温度",ASRTO:""}
//{ID:8,keyword:"命令词",ASR:"当前湿度",ASRTO:""}
//{ID:9,keyword:"命令词",ASR:"现在几点",ASRTO:""}
//{playid:201,voice:灯已打开}
//{playid:202,voice:灯已关闭}
//{playid:203,voice:开门指令已执行}
//{playid:204,voice:开窗指令已执行}
//{playid:205,voice:风扇已打开}
//{playid:206,voice:风扇已关闭}
//{playid:207,voice:当前温度为}
//{playid:208,voice:当前湿度为百分之}
//{playid:209,voice:现在是北京时间}
//{playid:210,voice:摄氏度}
//{playid:211,voice:点}
//{playid:212,voice:分}
//{playid:213,voice:暂时无法获取数据或执行指令，请检查连接}
//{playid:214,voice:等待回复超时，执行结果未确认}
// Numeric resources required by the installed SDK's play_num(value * 100, 1).
//{playid:10084,voice:零}
//{playid:10085,voice:一}
//{playid:10086,voice:二}
//{playid:10087,voice:三}
//{playid:10088,voice:四}
//{playid:10089,voice:五}
//{playid:10090,voice:六}
//{playid:10091,voice:七}
//{playid:10092,voice:八}
//{playid:10093,voice:九}
//{playid:10094,voice:十}
//{playid:10095,voice:百}
//{playid:10096,voice:千}
//{playid:10097,voice:万}
//{playid:10098,voice:亿}
//{playid:10099,voice:负}
//{playid:10100,voice:点}

static bool replyMatches(char *line, unsigned long request, unsigned command) {
    unsigned long rid = 0;
    unsigned cmd = 0;
    char kind[8], extra;
    long a = 0, b = 0;
    if (sscanf(line, "SH1 %lu %u %7s %ld %ld %c", &rid, &cmd, kind, &a, &b, &extra) != 5
        || rid != request || cmd != command) return false;
    if (!strcmp(kind, "ERR")) { play_audio(213); return true; }
    if (command <= 6 && !strcmp(kind, "OK")) {
        play_audio(200 + command);
    } else if (command == 7 && !strcmp(kind, "TEMP") && a >= -4000 && a <= 8000) {
        play_audio(207); play_num((int64_t)a, 1); play_audio(210);
    } else if (command == 8 && !strcmp(kind, "HUM") && a >= 0 && a <= 10000) {
        play_audio(208); play_num((int64_t)a, 1);
    } else if (command == 9 && !strcmp(kind, "TIME") && a >= 0 && a < 24 && b >= 0 && b < 60) {
        play_audio(209); play_num((int64_t)a * 100, 1); play_audio(211);
        play_num((int64_t)b * 100, 1); play_audio(212);
    } else return false;
    return true;
}

static void requestCommand(unsigned command) {
    while (Serial1.available()) Serial1.read();
    if (++sequence > 999999999UL) sequence = 1;
    char request[40];
    snprintf(request, sizeof(request), "SH1 %lu %u\n", sequence, command);
    Serial1.print(request);
    char line[64];
    unsigned used = 0;
    bool dropping = false;
    uint32_t started = millis();
    while ((uint32_t)(millis() - started) < 12000UL) {
        while (Serial1.available()) {
            int ch = Serial1.read();
            if (ch == '\n') {
                line[used] = 0;
                if (!dropping && replyMatches(line, sequence, command)) return;
                used = 0; dropping = false;
            } else if (!dropping && ch != '\r') {
                if (used < sizeof(line) - 1) line[used++] = (char)ch;
                else dropping = true;
            }
        }
        delay(5);
    }
    // Never resend a physical action after timeout.
    play_audio(214);
}

static void bridgeTask(void *) {
    unsigned command;
    for (;;) {
        if (xQueueReceive(commands, &command, portMAX_DELAY) == pdTRUE) {
            requestCommand(command);
            taskENTER_CRITICAL(); busy = false; taskEXIT_CRITICAL();
        }
    }
}

void ASR_CODE() {
    if (snid < 1 || snid > 9 || !commands) return;
    bool accepted = false;
    taskENTER_CRITICAL();
    if (!busy) { busy = true; accepted = true; }
    taskEXIT_CRITICAL();
    if (accepted) {
        unsigned command = snid;
        if (xQueueSend(commands, &command, 0) != pdTRUE) {
            taskENTER_CRITICAL(); busy = false; taskEXIT_CRITICAL();
        }
    }
}

void hardware_init() {
    // UART1: PA2 TX / PA3 RX, fourth alternate function in this SDK.
    setPinFun(2, FORTH_FUNCTION);
    setPinFun(3, FORTH_FUNCTION);
    Serial1.begin(115200);
    commands = xQueueCreate(1, sizeof(unsigned));
    if (commands && xTaskCreate(bridgeTask, "home_uart", 1024, NULL, 4, NULL) != pdPASS) {
        vQueueDelete(commands); commands = NULL;
    }
    vTaskDelete(NULL);
}

void setup() {}
