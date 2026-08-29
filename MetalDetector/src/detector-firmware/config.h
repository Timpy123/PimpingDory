// Detector pod firmware v3 — pin map and tuning constants.
// Spec: PLAN-DETECTOR-POD.md "v3 specification"; hardware: docs/HAT-SCHEMATIC-SPEC.md.
// The pin map MUST match the HAT spec's Pico pin table.

#ifndef CONFIG_H
#define CONFIG_H

// ---- Pins (HAT v3) --------------------------------------------------------

// PI front end
#define PIN_TX_GATE             17  // coil pulse via TC4427 gate driver
#define PIN_RX_ADC              26  // decay signal, conditioned to 0-3.3V by RX chain
#define RX_ADC_INPUT            0
#define PIN_DAMP0               10  // damping bank select (binary, 3 bits)
#define PIN_DAMP1               11
#define PIN_DAMP2               12

// Digipot (RX gain), MCP41010 on SPI0
#define SPI_BUS                 spi0
#define PIN_SPI_SCK             2
#define PIN_SPI_MOSI            3
#define PIN_POT_CS              6

// DRV8833 (on-HAT) driving the potted piezo disc, push-pull.
// GP14/GP15 share one PWM slice (channels A/B) -> complementary output.
#define PIN_SOUNDER_A           14
#define PIN_SOUNDER_B           15

// WS2812 strip, single data line.
#define PIN_WS2812              13
#define WS2812_NUM_PIXELS       8

// I2C bus: OLED (and the LCD1602 on the bench). J7 is a free I2C port.
// v3: moved to GP8/GP9 (GP2-6 belong to the digipot SPI block on the HAT).
#define I2C_BUS                 i2c0
#define PIN_I2C_SDA             8
#define PIN_I2C_SCL             9
#define I2C_BAUD_HZ             400000
#define OLED_I2C_ADDR           0x3C

#define PIN_STATUS_LED          25  // onboard LED, mirrors heartbeat

// ---- PI engine (bench-calibrate on first hardware) -------------------------

#define TX_PULSE_US             150     // coil on-time per pulse
#define PULSE_PERIOD_MS         10      // 100 pulses/s
#define SAMPLE_START_US         15      // first ADC sample after switch-off (autotune refines)
#define DECAY_SAMPLES           64      // ADC free-run burst per pulse (~2us/sample)
#define EARLY_WINDOW            16      // samples 0..15: strength integral
#define LATE_WINDOW_END         48      // samples 16..47: tau (late/early ratio)
#define RING_THRESHOLD          40      // ADC counts: ringing detection in autotune
#define GAIN_TARGET_NOISE       6.0f    // autotune digipot: target noise std in counts
#define TAU_FAST_MAX            0.10f   // late/early below this -> class F (thin/small)
#define TAU_SLOW_MIN            0.30f   // above this -> class S (large/conductive); between -> M

// ---- Signal processing -----------------------------------------------------

#define LEVEL_EMA_MS            50      // fast smoothing of the per-pulse integral
#define CALIBRATION_MS          2000    // startup auto-zero duration
#define BASELINE_TAU_MS         60000   // slow drift tracking (targets fade in ~minutes)
#define DETECT_SIGMA            3.0f    // detection gate: signal > max(3*sigma, floor)
#define DETECT_FLOOR            2.0f    // minimum gate in integral counts
#define FULL_SCALE_SIGNAL       400.0f  // integral counts that map to strength 255 (bench-tune)

// ---- Sounder ---------------------------------------------------------------

#define SOUNDER_ENABLED         1       // compile-time mute
#define TONE_BASE_HZ            3000    // rises with strength up to ~4 kHz
#define TICK_MS                 30      // length of one beep tick
#define TICK_PERIOD_MAX_MS      800     // cadence at barely-detected
#define TICK_PERIOD_MIN_MS      80      // cadence just below continuous
#define CONTINUOUS_THRESHOLD    240     // strength >= this -> solid tone

// ---- Depth / temperature ----------------------------------------------------


// ---- Strip behavior ----------------------------------------------------------

#define STRIP_BRIGHTNESS        60      // 0-255 cap (potted LEDs are bright)
#define INSPECT_STABLE_MS       2000    // stable strong signal -> inspect mode
#define INSPECT_MIN_STRENGTH    40      // below this, never enter inspect mode
#define INSPECT_STABLE_BAND     26      // strength units (~10% of 255)
#define INSPECT_DIM_NUM         1       // dim to 1/10 in inspect mode
#define INSPECT_DIM_DEN         10

// ---- OLED layout (frozen v2 layout carried over; scales = calibration knob) --

#define OLED_W                  128
#define OLED_H                  32
#define LAYOUT_LEFT_W           80  // cols 0-79 text zone
#define LAYOUT_RIGHT_X          84  // cols 84-127 detection zone
#define TAU_ROW_Y               17  // tau icon row (was the temp line)
#define BAR_H                   14  // strength bar height, rows 0-13
#define DISPLAY_REFRESH_MS      200 // OLED redraw period (~12 ms I2C per flush)

// ---- Heartbeat / debug --------------------------------------------------------

#define HEARTBEAT_PERIOD_MS     2000    // "alive" blip interval (strip px 0, OLED dot, GP25)
#define HEARTBEAT_ON_MS         100
#define DEBUG_PRINT_PERIOD_MS   500     // level/baseline/strength/tau/depth/temp over UART (GP0)

#endif // CONFIG_H
