// Minimal SSD1306 128x32 I2C driver with framebuffer and scalable 5x7 text.

#ifndef SSD1306_H
#define SSD1306_H

#include <stdbool.h>
#include <stdint.h>

bool ssd1306_init(void);            // false if the display doesn't ACK
void ssd1306_clear(void);
void ssd1306_flush(void);           // push framebuffer to the panel
void ssd1306_pixel(int x, int y, bool on);
void ssd1306_fill_rect(int x, int y, int w, int h, bool on);
void ssd1306_frame_rect(int x, int y, int w, int h);

// Proportional text: empty glyph edge columns are trimmed ('1' is 3 cols).
// Returns the x position after the string. scale is an integer >= 1.
int ssd1306_text(int x, int y, const char *s, int scale);

#endif // SSD1306_H
