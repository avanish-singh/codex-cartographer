#ifndef SIGNAL_H
#define SIGNAL_H

#include <stddef.h>

/* Simple moving-average filter shared by the C and C++ front-ends. */
typedef struct {
    double *buffer;
    size_t length;
} Signal;

Signal *signal_create(size_t length);
void signal_destroy(Signal *sig);
double signal_mean(const Signal *sig);
void signal_smooth(Signal *sig, size_t window);

#endif
