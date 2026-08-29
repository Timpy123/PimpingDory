#include "pi_engine.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "pico/stdlib.h"
#include "hardware/adc.h"
#include "hardware/spi.h"
#include "hardware/sync.h"
#include "config.h"

static int sample_start_us = SAMPLE_START_US;

// ---- MCP41010 digipot (RX gain) --------------------------------------------

static void pot_write(uint8_t value) {
    uint8_t cmd[2] = {0x11, value}; // write to wiper 0
    gpio_put(PIN_POT_CS, 0);
    spi_write_blocking(SPI_BUS, cmd, 2);
    gpio_put(PIN_POT_CS, 1);
}

// ---- Damping bank ------------------------------------------------------------

static void damping_set(int code) { // 0..7, bit n -> DAMPn
    gpio_put(PIN_DAMP0, code & 1);
    gpio_put(PIN_DAMP1, (code >> 1) & 1);
    gpio_put(PIN_DAMP2, (code >> 2) & 1);
}

// ---- Core: fire one pulse, capture the decay ---------------------------------

static int capture(uint16_t *buf) {
    uint32_t irq = save_and_disable_interrupts();

    gpio_put(PIN_TX_GATE, 1);
    busy_wait_us_32(TX_PULSE_US);
    gpio_put(PIN_TX_GATE, 0);
    busy_wait_us_32((uint32_t)sample_start_us);

    adc_run(true); // free-running, ~2 us/sample at clkdiv 0
    int n = 0;
    while (n < DECAY_SAMPLES) {
        buf[n++] = adc_fifo_get_blocking();
    }
    adc_run(false);
    adc_fifo_drain();

    restore_interrupts(irq);
    return n;
}

float pi_engine_measure(float *late_ratio) {
    uint16_t buf[DECAY_SAMPLES];
    capture(buf);

    // Tail of the record approximates the settled level (VREF).
    float tail = 0;
    for (int i = LATE_WINDOW_END; i < DECAY_SAMPLES; i++) tail += buf[i];
    tail /= (float)(DECAY_SAMPLES - LATE_WINDOW_END);

    float early = 0, late = 0;
    for (int i = 0; i < EARLY_WINDOW; i++) early += fabsf((float)buf[i] - tail);
    for (int i = EARLY_WINDOW; i < LATE_WINDOW_END; i++) late += fabsf((float)buf[i] - tail);

    if (late_ratio) *late_ratio = early > 1.0f ? late / early : 0.0f;
    return early;
}

tau_class_t pi_engine_classify(float late_ratio, bool detecting) {
    if (!detecting) return TAU_UNKNOWN;
    if (late_ratio < TAU_FAST_MAX) return TAU_FAST;
    if (late_ratio > TAU_SLOW_MIN) return TAU_SLOW;
    return TAU_MEDIUM;
}

// ---- Auto-tune ----------------------------------------------------------------

// Ringing metric: sign changes of (sample - tail) in the early record.
static int ringing_count(const uint16_t *buf, float tail) {
    int changes = 0;
    int prev = 0;
    for (int i = 0; i < LATE_WINDOW_END; i++) {
        float d = (float)buf[i] - tail;
        if (fabsf(d) < RING_THRESHOLD) continue;
        int s = d > 0 ? 1 : -1;
        if (prev != 0 && s != prev) changes++;
        prev = s;
    }
    return changes;
}

static int settle_index(const uint16_t *buf, float tail) {
    for (int i = 0; i < DECAY_SAMPLES - 4; i++) {
        bool settled = true;
        for (int j = i; j < i + 4; j++) {
            if (fabsf((float)buf[j] - tail) > RING_THRESHOLD) { settled = false; break; }
        }
        if (settled) return i;
    }
    return DECAY_SAMPLES;
}

void pi_engine_autotune(void) {
    uint16_t buf[DECAY_SAMPLES];

    // 1. Damping: pick the code with the fastest ring-free settle.
    int best_code = 0, best_settle = DECAY_SAMPLES + 1;
    for (int code = 0; code < 8; code++) {
        damping_set(code);
        sleep_ms(2);
        capture(buf);
        float tail = 0;
        for (int i = LATE_WINDOW_END; i < DECAY_SAMPLES; i++) tail += buf[i];
        tail /= (float)(DECAY_SAMPLES - LATE_WINDOW_END);
        int rings = ringing_count(buf, tail);
        int settle = settle_index(buf, tail);
        printf("autotune damp=%d rings=%d settle=%d\n", code, rings, settle);
        if (rings == 0 && settle < best_settle) { best_settle = settle; best_code = code; }
    }
    damping_set(best_code);

    // 2. Gain: walk the digipot down from max until noise std hits the target.
    int gain = 255;
    for (; gain >= 8; gain -= 8) {
        pot_write((uint8_t)gain);
        sleep_ms(2);
        float sum = 0, sumsq = 0;
        const int reps = 16;
        for (int r = 0; r < reps; r++) {
            float e = pi_engine_measure(NULL);
            sum += e;
            sumsq += e * e;
            sleep_ms(PULSE_PERIOD_MS);
        }
        float mean = sum / reps;
        float var = sumsq / reps - mean * mean;
        float std = var > 0 ? sqrtf(var) : 0;
        if (std <= GAIN_TARGET_NOISE) break;
    }

    printf("autotune done: damping=%d settle=%d gain=%d\n", best_code, best_settle, gain);
}

// ---- Init -----------------------------------------------------------------------

void pi_engine_init(void) {
    gpio_init(PIN_TX_GATE);
    gpio_set_dir(PIN_TX_GATE, GPIO_OUT);
    gpio_put(PIN_TX_GATE, 0);

    gpio_init(PIN_DAMP0); gpio_set_dir(PIN_DAMP0, GPIO_OUT);
    gpio_init(PIN_DAMP1); gpio_set_dir(PIN_DAMP1, GPIO_OUT);
    gpio_init(PIN_DAMP2); gpio_set_dir(PIN_DAMP2, GPIO_OUT);
    damping_set(0);

    spi_init(SPI_BUS, 1000 * 1000);
    gpio_set_function(PIN_SPI_SCK, GPIO_FUNC_SPI);
    gpio_set_function(PIN_SPI_MOSI, GPIO_FUNC_SPI);
    gpio_init(PIN_POT_CS);
    gpio_set_dir(PIN_POT_CS, GPIO_OUT);
    gpio_put(PIN_POT_CS, 1);
    pot_write(128);

    adc_init();
    adc_gpio_init(PIN_RX_ADC);
    adc_select_input(RX_ADC_INPUT);
    adc_fifo_setup(true, false, 1, false, false);
    adc_set_clkdiv(0); // max rate, ~2 us/sample
}
