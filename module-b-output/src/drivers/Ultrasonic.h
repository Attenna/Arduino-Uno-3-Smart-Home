#ifndef ULTRASONIC_H
#define ULTRASONIC_H

#include <Arduino.h>

class Ultrasonic {
public:
    void begin();
    // Fresh measurement; 0 means no complete echo within the timeout.
    unsigned long measure();
private:
    unsigned long _lastTrigger;
};

#endif
