| AmigaOS version string for SWOTL.
|
| AmigaDOS Version finds this by scanning the load image for the "$VER: "
| marker; no code references it. SHF_GNU_RETAIN keeps the otherwise
| unreferenced section alive through --gc-sections.
|
| Keep the date hardcoded so identical source trees produce identical builds.
	.section .rodata.version,"aR"
	.balign 2
	.asciz "$VER: SWotL 1.2 (11.11.2026)"
	.balign 2
