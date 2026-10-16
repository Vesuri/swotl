#ifndef SWOTL_FILE_DATE_H
#define SWOTL_FILE_DATE_H
#include <stdint.h>

/* Amiga DateStamp uses local calendar days since 1978-01-01, minutes since
 * midnight and 50 Hz ticks within the minute (NDK dos/dos.h). DOSBox-X
 * DOS_PackDate/Time masks the year to seven bits and truncates odd seconds. */
static inline void amiga_file_date(int32_t days, int32_t minutes, int32_t ticks,
                                  uint16_t *dos_time, uint16_t *dos_date)
{
    int32_t cycles = days / 146097;
    days %= 146097;
    if (days < 0) { days += 146097; --cycles; }
    int32_t year = 1978 + cycles * 400;
    for (;;) {
        int leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
        int length = 365 + leap;
        if (days < length) break;
        days -= length;
        ++year;
    }
    static const uint8_t lengths[12] = {31,28,31,30,31,30,31,31,30,31,30,31};
    unsigned month = 0;
    for (;;) {
        int length = lengths[month] + (month == 1 && year % 4 == 0 &&
                                     (year % 100 != 0 || year % 400 == 0));
        if (days < length) break;
        days -= length;
        ++month;
    }
    *dos_date = (uint16_t)(((uint32_t)(year - 1980) & 127) << 9 |
                           (month + 1) << 5 | (uint32_t)(days + 1));
    *dos_time = (uint16_t)(((uint32_t)(minutes / 60) & 31) << 11 |
                           ((uint32_t)(minutes % 60) & 63) << 5 |
                           ((uint32_t)(ticks / 100) & 31));
}
/* DOS packed calendar to Amiga DateStamp; seconds have two-second precision. */
static inline void amiga_date_stamp(uint16_t time, uint16_t date,
                                   int32_t *days, int32_t *minutes, int32_t *ticks)
{
    uint32_t year = 1980 + (date >> 9), month = (date >> 5) & 15;
    int32_t n = 0;
    for (uint32_t y = 1978; y < year; ++y)
        n += 365 + (y % 4 == 0 && (y % 100 != 0 || y % 400 == 0));
    static const uint8_t lengths[12] = {31,28,31,30,31,30,31,31,30,31,30,31};
    for (uint32_t m = 1; m < month; ++m)
        n += lengths[m - 1] + (m == 2 && year % 4 == 0 &&
                              (year % 100 != 0 || year % 400 == 0));
    *days = n + (date & 31) - 1;
    *minutes = (time >> 11) * 60 + ((time >> 5) & 63);
    *ticks = (time & 31) * 100;
}
#endif
