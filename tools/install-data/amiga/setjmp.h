/* Freestanding setjmp for blast.c in the Amiga helper (setjmp.s). */
#ifndef SWOTL_SETJMP_H
#define SWOTL_SETJMP_H
typedef long jmp_buf[13];
int setjmp(jmp_buf env);
void longjmp(jmp_buf env, int value) __attribute__((noreturn));
#endif
