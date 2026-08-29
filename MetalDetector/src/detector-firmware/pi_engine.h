// Route B pulse-induction engine: the Pico fires the coil and samples the decay.
// Hardware contract: docs/HAT-SCHEMATIC-SPEC.md (TX gate, damping bank, digipot, RX chain).

#ifndef PI_ENGINE_H
#define PI_ENGINE_H

#include <stdbool.h>

typedef enum {
    TAU_UNKNOWN = 0, // no target / not classifiable
    TAU_FAST,        // thin/small target (foil, small gold)
    TAU_MEDIUM,
    TAU_SLOW,        // large/high-conductivity (copper, silver, solid ring)
} tau_class_t;

void pi_engine_init(void);

// One TX pulse + decay capture. Returns the early-window integral (the strength
// observable, in summed ADC counts); *late_ratio gets late/early for tau.
// Interrupts are briefly disabled for deterministic timing (~0.3 ms).
float pi_engine_measure(float *late_ratio);

// Auto-tune to the attached coil: pick the damping setting with the fastest
// clean settle, then set RX gain so the noise floor hits GAIN_TARGET_NOISE.
// Call once at boot, coil connected, no target near. Reports over stdio.
void pi_engine_autotune(void);

tau_class_t pi_engine_classify(float late_ratio, bool detecting);

#endif // PI_ENGINE_H
