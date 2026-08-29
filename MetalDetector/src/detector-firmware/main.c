// Detector pod firmware v3 (HAT — PLAN-DETECTOR-POD.md "v3 specification").
//
// Route B detection: the Pico IS the detector — it fires the coil (TX gate),
// samples the decay directly (pi_engine), and auto-tunes damping + RX gain
// to whatever coil is attached. Reporting on:
//  - WS2812 strip: attention channel; length = strength, color = confidence;
//    auto-dims while hovering over a stable target so the OLED stays readable
//  - 0.91" SSD1306 128x32 OLED: detail channel; strength bar + live tau
//    class icon (F/M/S). Cols 0-79 are free (depth/temp removed with the
//    MS5837, 2026-08-29) and reserved for the tau readout.
//  - potted piezo sounder: cadence/pitch encodes strength
//
// Behavior contract: power on mounted and clear of metal (autotune + 2 s
// auto-zero); heartbeat on strip
// pixel 0, OLED dot, and onboard LED so a dead pod is distinguishable from
// "no metal".

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "pico/stdlib.h"
#include "hardware/adc.h"
#include "hardware/pwm.h"
#include "hardware/pio.h"
#include "hardware/i2c.h"
#include "hardware/clocks.h"
#include "config.h"
#include "ssd1306.h"
#include "pi_engine.h"
#include "ws2812.pio.h"

// ---- WS2812 strip ----------------------------------------------------------

static PIO strip_pio = pio0;
static uint strip_sm = 0;

static void strip_init(void) {
    uint offset = pio_add_program(strip_pio, &ws2812_program);
    ws2812_program_init(strip_pio, strip_sm, offset, PIN_WS2812, 800000.0f);
}

static inline uint32_t grb(uint8_t r, uint8_t g, uint8_t b) {
    return ((uint32_t)g << 16) | ((uint32_t)r << 8) | b;
}

// strength 0..255 -> lit length; color green->red with strength; dim divider.
static void strip_show(int strength, bool heartbeat, int dim_num, int dim_den) {
    int lit = 0;
    if (strength > 0) lit = 1 + strength * (WS2812_NUM_PIXELS - 1) / 255;
    for (int i = 0; i < WS2812_NUM_PIXELS; i++) {
        uint32_t px = 0;
        if (i < lit) {
            uint8_t r = (uint8_t)(strength);
            uint8_t g = (uint8_t)(255 - strength);
            r = (uint8_t)((int)r * STRIP_BRIGHTNESS / 255 * dim_num / dim_den);
            g = (uint8_t)((int)g * STRIP_BRIGHTNESS / 255 * dim_num / dim_den);
            px = grb(r, g, 0);
        } else if (i == 0 && heartbeat) {
            px = grb(0, 0, STRIP_BRIGHTNESS / 4); // blue blip = alive
        }
        pio_sm_put_blocking(strip_pio, strip_sm, px << 8u);
    }
}

// ---- Sounder (unchanged from v1) --------------------------------------------

static uint sounder_slice;

static void sounder_init(void) {
    gpio_init(PIN_SOUNDER_A);
    gpio_init(PIN_SOUNDER_B);
    gpio_set_dir(PIN_SOUNDER_A, GPIO_OUT);
    gpio_set_dir(PIN_SOUNDER_B, GPIO_OUT);
    gpio_put(PIN_SOUNDER_A, 0);
    gpio_put(PIN_SOUNDER_B, 0);
    sounder_slice = pwm_gpio_to_slice_num(PIN_SOUNDER_A);
}

static void sounder_tone(uint32_t freq_hz) {
#if SOUNDER_ENABLED
    uint32_t sys_hz = clock_get_hz(clk_sys);
    float div = 4.0f;
    uint32_t wrap = (uint32_t)(sys_hz / (div * freq_hz)) - 1;
    pwm_config c = pwm_get_default_config();
    pwm_config_set_clkdiv(&c, div);
    pwm_config_set_wrap(&c, wrap);
    pwm_config_set_output_polarity(&c, false, true); // B inverted: push-pull
    pwm_init(sounder_slice, &c, false);
    pwm_set_both_levels(sounder_slice, (wrap + 1) / 2, (wrap + 1) / 2);
    gpio_set_function(PIN_SOUNDER_A, GPIO_FUNC_PWM);
    gpio_set_function(PIN_SOUNDER_B, GPIO_FUNC_PWM);
    pwm_set_enabled(sounder_slice, true);
#endif
}

static void sounder_off(void) {
    pwm_set_enabled(sounder_slice, false);
    gpio_set_function(PIN_SOUNDER_A, GPIO_FUNC_SIO);
    gpio_set_function(PIN_SOUNDER_B, GPIO_FUNC_SIO);
    gpio_put(PIN_SOUNDER_A, 0); // no DC across the piezo when silent
    gpio_put(PIN_SOUNDER_B, 0);
}

// ---- OLED layout (v2 layout carried over) -------------------------------------

static void display_render(int strength, tau_class_t tau, bool heartbeat) {
    ssd1306_clear();

    // Left zone (cols 0-79): FREE since the MS5837 was dropped 2026-08-29.
    // Reserved for the tau readout; intentionally blank until that lands.

    // Right zone: strength bar with frame, live tau class below.
    ssd1306_frame_rect(LAYOUT_RIGHT_X, 0, OLED_W - LAYOUT_RIGHT_X, BAR_H);
    int w = strength * (OLED_W - LAYOUT_RIGHT_X - 4) / 255;
    ssd1306_fill_rect(LAYOUT_RIGHT_X + 2, 2, w, BAR_H - 4, true);
    const char *tau_icon =
        tau == TAU_FAST ? "F" : tau == TAU_MEDIUM ? "M" :
        tau == TAU_SLOW ? "S" : "-";
    ssd1306_text(LAYOUT_RIGHT_X + 14, TAU_ROW_Y, tau_icon, 2);

    // Heartbeat dot in the separator column.
    if (heartbeat) ssd1306_fill_rect(81, 29, 2, 2, true);

    ssd1306_flush();
}

// ---- Self test -----------------------------------------------------------------

static void self_test(bool oled_ok) {
    strip_show(255, false, 1, 1);
    sounder_tone(2800);
    sleep_ms(120);
    sounder_tone(3500);
    sleep_ms(120);
    sounder_off();
    sleep_ms(160);
    strip_show(0, false, 1, 1);
    printf("self-test: oled=%d\n", oled_ok);
}

// ---- Main ----------------------------------------------------------------------

int main(void) {
    stdio_init_all();

    gpio_init(PIN_STATUS_LED);
    gpio_set_dir(PIN_STATUS_LED, GPIO_OUT);

    i2c_init(I2C_BUS, I2C_BAUD_HZ);
    gpio_set_function(PIN_I2C_SDA, GPIO_FUNC_I2C);
    gpio_set_function(PIN_I2C_SCL, GPIO_FUNC_I2C);
    gpio_pull_up(PIN_I2C_SDA);
    gpio_pull_up(PIN_I2C_SCL);

    strip_init();
    sounder_init();
    pi_engine_init(); // owns the ADC (free-run decay capture)

    bool oled_ok = ssd1306_init();

    printf("detector-pod v3 boot\n");
    self_test(oled_ok);

    // Adapt to the attached coil: damping code + RX gain.
    pi_engine_autotune();

    // Detection auto-zero (mounted, clear of metal).
    float baseline = 0.0f, sigma = 0.0f;
    {
        int pulses = CALIBRATION_MS / PULSE_PERIOD_MS;
        float sum = 0.0f, sumsq = 0.0f;
        for (int i = 0; i < pulses; i++) {
            float a = pi_engine_measure(NULL);
            sum += a;
            sumsq += a * a;
            sleep_ms(PULSE_PERIOD_MS);
        }
        baseline = sum / pulses;
        float var = sumsq / pulses - baseline * baseline;
        sigma = var > 0 ? sqrtf(var) : 0.0f;
        printf("auto-zero: baseline=%.2f sigma=%.2f\n", baseline, sigma);
    }

    const float gate = fmaxf(DETECT_SIGMA * sigma, DETECT_FLOOR);
    const float level_alpha =
        (float)PULSE_PERIOD_MS / (float)LEVEL_EMA_MS;
    const float baseline_alpha =
        (float)PULSE_PERIOD_MS / (float)BASELINE_TAU_MS;

    float level = baseline;
    bool tone_on = false;
    bool hb_visible = false;
    int inspect_ref = -1;                      // strength when stability started
    absolute_time_t inspect_since = get_absolute_time();
    absolute_time_t next_tick = get_absolute_time();
    absolute_time_t tick_off_at = get_absolute_time();
    absolute_time_t next_heartbeat = get_absolute_time();
    absolute_time_t heartbeat_off_at = get_absolute_time();
    absolute_time_t next_display = get_absolute_time();
    absolute_time_t next_debug = get_absolute_time();

    absolute_time_t next_pulse = get_absolute_time();
    float late_ratio_ema = 0.0f;

    while (true) {
        // Pace the TX pulses at PULSE_PERIOD_MS (100 Hz).
        sleep_until(next_pulse);
        next_pulse = delayed_by_ms(next_pulse, PULSE_PERIOD_MS);

        float late_ratio;
        float activity = pi_engine_measure(&late_ratio);
        level += level_alpha * (activity - level);
        baseline += baseline_alpha * (level - baseline);
        late_ratio_ema += level_alpha * (late_ratio - late_ratio_ema);

        float signal = level - baseline;
        int strength = 0;
        if (signal > gate) {
            float s = (signal - gate) / (FULL_SCALE_SIGNAL - gate) * 255.0f;
            strength = s > 255.0f ? 255 : (int)s;
            if (strength < 1) strength = 1;
        }
        tau_class_t tau = pi_engine_classify(late_ratio_ema, strength > 0);

        absolute_time_t now = get_absolute_time();

        // --- Inspect mode: strong and stable -> dim the strip for the OLED ---
        if (strength >= INSPECT_MIN_STRENGTH && inspect_ref >= 0 &&
            abs(strength - inspect_ref) <= INSPECT_STABLE_BAND) {
            // still stable, keep reference and timer
        } else {
            inspect_ref = strength >= INSPECT_MIN_STRENGTH ? strength : -1;
            inspect_since = now;
        }
        bool inspect = inspect_ref >= 0 &&
            absolute_time_diff_us(inspect_since, now) >
                (int64_t)INSPECT_STABLE_MS * 1000;

        // --- Heartbeat timing ---
        if (time_reached(next_heartbeat)) {
            heartbeat_off_at = delayed_by_ms(now, HEARTBEAT_ON_MS);
            next_heartbeat = delayed_by_ms(now, HEARTBEAT_PERIOD_MS);
        }
        hb_visible = !time_reached(heartbeat_off_at);
        gpio_put(PIN_STATUS_LED, hb_visible);

        // --- Strip ---
        strip_show(strength, hb_visible && strength == 0,
                   inspect ? INSPECT_DIM_NUM : 1,
                   inspect ? INSPECT_DIM_DEN : 1);

        // --- Sounder ---
        if (strength >= CONTINUOUS_THRESHOLD) {
            if (!tone_on) { sounder_tone(TONE_BASE_HZ + strength * 4); tone_on = true; }
        } else if (strength > 0) {
            uint32_t period = TICK_PERIOD_MAX_MS -
                (uint32_t)(TICK_PERIOD_MAX_MS - TICK_PERIOD_MIN_MS) * strength / 255;
            if (time_reached(next_tick)) {
                sounder_tone(TONE_BASE_HZ + strength * 4);
                tone_on = true;
                tick_off_at = delayed_by_ms(now, TICK_MS);
                next_tick = delayed_by_ms(now, period);
            }
            if (tone_on && time_reached(tick_off_at)) { sounder_off(); tone_on = false; }
        } else if (tone_on) {
            sounder_off();
            tone_on = false;
        }

        // --- OLED ---
        if (time_reached(next_display)) {
            display_render(strength, tau, hb_visible);
            next_display = delayed_by_ms(now, DISPLAY_REFRESH_MS);
        }

        // --- Debug telemetry ---
        if (time_reached(next_debug)) {
            printf("level=%.2f base=%.2f str=%d tau=%.3f%s\n",
                   level, baseline, strength, late_ratio_ema,
                   inspect ? " [inspect]" : "");
            next_debug = delayed_by_ms(now, DEBUG_PRINT_PERIOD_MS);
        }
    }
}
