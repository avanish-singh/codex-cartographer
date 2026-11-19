#include <stdio.h>
#include <stdlib.h>
#include "signal.h"

/* Allocate a zeroed signal buffer. */
Signal *signal_create(size_t length)
{
    Signal *sig = malloc(sizeof(Signal));
    if (sig == NULL) {
        return NULL;
    }
    sig->buffer = calloc(length, sizeof(double));
    sig->length = length;
    return sig;
}

void signal_destroy(Signal *sig)
{
    if (sig) {
        free(sig->buffer);
        free(sig);
    }
}

double signal_mean(const Signal *sig)
{
    double total = 0.0;
    for (size_t i = 0; i < sig->length; i++) {
        total += sig->buffer[i];
    }
    return total / (double)sig->length;
}

/* In-place moving average with the given window size. */
void signal_smooth(Signal *sig, size_t window)
{
    double *out = calloc(sig->length, sizeof(double));
    for (size_t i = 0; i < sig->length; i++) {
        double acc = 0.0;
        size_t count = 0;
        for (size_t k = 0; k < window && i + k < sig->length; k++) {
            acc += sig->buffer[i + k];
            count++;
        }
        out[i] = acc / (double)count;
    }
    for (size_t i = 0; i < sig->length; i++) {
        sig->buffer[i] = out[i];
    }
    free(out);
}

int main(void)
{
    Signal *sig = signal_create(8);
    for (size_t i = 0; i < sig->length; i++) {
        sig->buffer[i] = (double)i;
    }
    signal_smooth(sig, 3);
    printf("mean after smoothing: %f\n", signal_mean(sig));
    signal_destroy(sig);
    return 0;
}
