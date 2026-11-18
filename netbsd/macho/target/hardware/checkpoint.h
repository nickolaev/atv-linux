#ifndef ATV_NATIVE_CHECKPOINT_H
#define ATV_NATIVE_CHECKPOINT_H

/* Emulation-only API. The caller must reserve the copied kernel, bootinfo,
 * transfer stack, current GDT/IDT and BDA page, and prove 0x472 is writable
 * and disjoint from live inputs. expected_bootinfo is a separate immutable
 * copy of the freshly generated pointer array and records. A fatal fault
 * does not return. An outer hook must preserve EFLAGS and caller registers. */
#ifdef TARGET_NATIVE_CHECKPOINT
typedef __UINT32_TYPE__ checkpoint_u32;
int checkpoint_run(const void *source, checkpoint_u32 source_length,
                   checkpoint_u32 bootinfo_pa, checkpoint_u32 stack_top,
                   int bda_writable_and_reserved,
                   const void *expected_bootinfo, checkpoint_u32 expected_length);
#endif
#endif
