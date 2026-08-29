#include "ssd1306.h"

#include <string.h>
#include "hardware/i2c.h"
#include "pico/stdlib.h"
#include "config.h"
#include "font5x7.h"

static uint8_t fb[OLED_W * OLED_H / 8]; // page-major, 4 pages x 128 cols
static bool present = false;

static bool cmd(uint8_t c) {
    uint8_t buf[2] = {0x00, c};
    return i2c_write_timeout_us(I2C_BUS, OLED_I2C_ADDR, buf, 2, false, 2000) == 2;
}

bool ssd1306_init(void) {
    static const uint8_t seq[] = {
        0xAE,             // display off
        0xD5, 0x80,       // clock
        0xA8, 0x1F,       // multiplex 31 (32 rows)
        0xD3, 0x00,       // no display offset
        0x40,             // start line 0
        0x8D, 0x14,       // charge pump on
        0x20, 0x00,       // horizontal addressing
        0xA1,             // segment remap
        0xC8,             // COM scan direction
        0xDA, 0x02,       // COM pins for 128x32
        0x81, 0x8F,       // contrast
        0xD9, 0xF1,       // precharge
        0xDB, 0x40,       // VCOM level
        0xA4,             // resume from RAM
        0xA6,             // normal (not inverted)
        0xAF,             // display on
    };
    present = true;
    for (unsigned i = 0; i < sizeof(seq); i++) {
        if (!cmd(seq[i])) { present = false; return false; }
    }
    ssd1306_clear();
    ssd1306_flush();
    return true;
}

void ssd1306_clear(void) { memset(fb, 0, sizeof(fb)); }

void ssd1306_flush(void) {
    if (!present) return;
    cmd(0x21); cmd(0); cmd(OLED_W - 1);      // column range
    cmd(0x22); cmd(0); cmd(OLED_H / 8 - 1);  // page range
    uint8_t buf[1 + sizeof(fb)];
    buf[0] = 0x40; // data control byte
    memcpy(buf + 1, fb, sizeof(fb));
    i2c_write_timeout_us(I2C_BUS, OLED_I2C_ADDR, buf, sizeof(buf), false, 20000);
}

void ssd1306_pixel(int x, int y, bool on) {
    if (x < 0 || x >= OLED_W || y < 0 || y >= OLED_H) return;
    uint16_t idx = (uint16_t)((y / 8) * OLED_W + x);
    uint8_t bit = (uint8_t)(1u << (y % 8));
    if (on) fb[idx] |= bit; else fb[idx] &= (uint8_t)~bit;
}

void ssd1306_fill_rect(int x, int y, int w, int h, bool on) {
    for (int j = y; j < y + h; j++)
        for (int i = x; i < x + w; i++)
            ssd1306_pixel(i, j, on);
}

void ssd1306_frame_rect(int x, int y, int w, int h) {
    for (int i = x; i < x + w; i++) {
        ssd1306_pixel(i, y, true);
        ssd1306_pixel(i, y + h - 1, true);
    }
    for (int j = y; j < y + h; j++) {
        ssd1306_pixel(x, j, true);
        ssd1306_pixel(x + w - 1, j, true);
    }
}

int ssd1306_text(int x, int y, const char *s, int scale) {
    for (; *s; s++) {
        const uint8_t *g = font5x7_lookup(*s);
        int first = 0, last = 4;
        while (first < 4 && g[first] == 0) first++;
        while (last > first && g[last] == 0) last--;
        if (*s == ' ') { x += 3 * scale; continue; }
        for (int c = first; c <= last; c++) {
            for (int r = 0; r < 7; r++) {
                if (g[c] & (1u << r)) {
                    ssd1306_fill_rect(x + (c - first) * scale, y + r * scale,
                                      scale, scale, true);
                }
            }
        }
        x += (last - first + 1 + 1) * scale; // glyph + 1-col spacing
    }
    return x;
}
