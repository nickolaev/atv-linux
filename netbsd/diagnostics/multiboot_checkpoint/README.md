# Apple TV Multiboot Ethernet checkpoint

The checkpoint runs at the first instruction entered by Multiboot 1 after
Linux `kexec`. The Ethernet variant sends one UDP datagram through the RTL8139 using
the configured IPv4 addresses and destination Ethernet address. The payload
includes the launch ID and the incoming EAX and EBX values. It then passes
control and the original registers to the NetBSD 11.1/i386 installer at
physical `0x00100000`. The installer can send a second, separate report from
its RAM filesystem using the [NetBSD installer reporter](../net_report/README.md).

The Apple TV test uses the existing USB bootstrap. Keep the instrumented
kernel in RAM and use separate load-only and execution jobs. An entry packet
proves the CPU reached the checkpoint. An installer report proves the kernel
reached installer userland and its network driver works. If the entry packet
is absent, the checkpoint or raw Ethernet transmission may have failed.
The UDP packet is unencrypted and is correlated by source and launch ID.

## Build and collect

Use Clang, LLD and GNU `objcopy`. The following configuration is for QEMU
with `-netdev user,id=nic0 -device rtl8139,netdev=nic0,addr=03`.

```sh
checkpoint=netbsd/diagnostics/multiboot_checkpoint
sh "$checkpoint/build.sh" checkpoint.bin \
  -DATV_PCI_BUS=0 -DATV_PCI_DEV=3 -DATV_PCI_FN=0 \
  -DATV_DST_MAC=0x52,0x55,0x0a,0x00,0x02,0x02 \
  -DATV_SRC_IP=10,0,2,15 -DATV_DST_IP=10,0,2,2 \
  '-DATV_CHECKPOINT_ID="qemu-checkpoint-1"'
python3 "$checkpoint/package.py" netbsd-INSTALL checkpoint.bin netbsd-checkpoint \
  --address 0x01c00000 --sha256 "$KERNEL_SHA256"
python3 "$checkpoint/receive.py" --source 127.0.0.1 \
  --launch-id qemu-checkpoint-1 --timeout 60 checkpoint.txt
```

Use the installer ELF with its original virtual entry as the input to
`package.py`. The script adds the checkpoint as a load segment at physical
`0x01c00000` and sets the ELF entry to that address. On the Apple TV, confirm
that range is in System RAM and use the PCI bus, device and function from the
current Linux preflight report. Set `ATV_DST_MAC` from the collecting network
interface. Run the collector on that interface's IPv4 address with `--bind`
and use the Apple TV's IPv4 address in `--source`.

Use the packaged kernel with `kexec --load --type=multiboot-x86
--command-line='root=md0a'`.

The diskless QEMU test used the Apple TV bootstrap's Linux 2.6.39 and
kexec-tools 2.0.1. The checkpoint packet recorded `EAX=2badb002` before the
installer started. The separate NetBSD report confirmed `root on md0a` and
`re0` on the emulated RTL8139C+. The Apple TV passed the signed RAM load and
unload check. Its physical Ethernet transmission still requires the one-way
execution test.

## Visual checkpoint

The `visual` variant writes a green and magenta checkerboard into the active
framebuffer and halts so the pattern stays visible. It executes before the
NetBSD installer. Power-cycle the Apple TV to return to the USB bootstrap.
If the display stays dark or retains the old menu, the result is inconclusive
because the framebuffer may be inaccessible after the handoff.

Use `fb_info.c` from the current Linux boot to read the fixed and variable
framebuffer information using GET ioctls. Include the PCI device and BARs plus
the physical RAM ranges in the signed report. `framebuffer_config.py` checks
the pixel layout, visible window, GPU aperture, and checkpoint RAM range. Pass
its `-DATV_FB_…` options to `ATV_CHECKPOINT=visual sh build.sh` and package
the output using the same `package.py` command as the Ethernet variant.

With networking disabled in QEMU, the bootstrap's Linux and kexec-tools 2.0.1
handed off to the visual variant and all 32 tiles matched the expected pixels.

The physical Apple TV also displayed the checkerboard after the same-stick
handoff. The signed Linux preflight reported a 1920×1080 Nouveau framebuffer
at `0x10049000` with a 7680-byte stride. The visible marker confirms execution
at the Multiboot entry on Apple TV hardware. This probe halted there by design.

## Continuing visual checkpoints

The `stages` variant displays the same checkerboard briefly and then boots
NetBSD. It fills and numbers each section of the top strip, from left to right.

| Number | Color | Last confirmed stage |
| --- | --- | --- |
| 1 | Cyan | NetBSD recognized Multiboot 1 and entered its boot-info copy path. |
| 2 | Yellow | The Multiboot information copy returned. |
| 3 | Blue | NetBSD is about to enable paging. |
| 4 | White | The CPU reached the high kernel address with paging active. |
| 5 | Orange | Both post-relocation calls returned and the framebuffer boot-info record was added. |
| 6 | Lavender | `initgdt` returned. |
| 7 | Green | `init_bootspace` returned and the hook immediately before `init386` ran. |

A red third marker means the temporary mapping encountered an occupied slot
and halted. After stage 7, NetBSD can take over the screen with its own `genfb`
console. The installer ramdisk sends a separate Ethernet report if it starts
and its network interface comes up.

Invoke `build.sh` with `ATV_CHECKPOINT=stages` and the authenticated framebuffer
flags from the current Linux boot. Save the `STAGE=ADDRESS` lines it prints and
pass each as `--hook STAGE=ADDRESS` to `stages_package.py`, with the SHA-256 of
the original-entry installer ELF. The same USB bootstrap can download this
kernel into RAM. Check the live framebuffer flags again after each reboot
before using an existing build.

In the first physical run with the five-color strip, the tester later recalled
seeing several extra colors above the checkerboard. The highest stage remains
unconfirmed. The installer receiver timed out after 180 seconds.

In a repeated physical run of the numbered build, the tester confirmed that
7 was the highest visible number. This verifies paging, both post-relocation
calls, framebuffer boot-info registration, `initgdt`, and `init_bootspace`.
The last confirmed point is the hook immediately before `init386`.
The installer receiver timed out after its 180-second listening window.

## Tracing init386

`init386_trace.py` adds further checkpoints to a verified numbered kernel.
It writes the latest hexadecimal stage in an orange box at the top-left,
while retaining the original 1–7 strip. Each call temporarily maps the first
framebuffer page using the recursive kernel page-table window and restores
the previous mapping before resuming the original function.

| Marker | Last confirmed point |
| --- | --- |
| 8 | `init386` entered and reached `uvm_lwp_setuarea`. |
| 9 | The uarea setup returned, just before `cpu_probe`. |
| A | `cpu_probe` returned, just before CPU MSR initialization. |
| B | CPU MSR initialization returned. |
| C | CPU speculation setup returned. |
| D | Bus-space initialization returned, just before `consinit`. |
| E | `consinit` returned, just before `pmap_bootstrap`. |
| F | `init386` returned to locore. |

The packer requires the input SHA-256 and checks every displaced call plus
the unused mapped text bytes containing its helpers. A QEMU test with the
bootstrap's Linux and kexec-tools reached F and returned a complete installer
report. In the physical same-stick test, the tester confirmed **E**, including
its bottom bar. This verifies that `consinit` returned and the hook immediately
before `pmap_bootstrap` ran. The `init386` return marker F was not observed.

Use `init386_trace.py --phase pmap` with a fresh verified numbered kernel to
trace the next part of initialization. This variant uses the same orange
hexadecimal character and leaves the seven numbered tiles intact.

| Marker | Last confirmed point |
| --- | --- |
| 0 | `consinit` returned, just before `pmap_bootstrap`. |
| 1 | `pmap_bootstrap` entered and reached its mutex initialization. |
| 2 | The kernel pmap object was initialized, entering CPU-set creation. |
| 3 | CPU mapping features were configured, entering per-CPU mapping allocation. |
| 4 | Virtual ranges were prepared, entering dump-page reservation. |
| 5 | Bootstrap mappings were prepared, entering the final TLB flush. |
| 6 | `pmap_bootstrap` returned, entering CPU RNG initialization. |
| 7 | CPU RNG initialization returned, entering seed processing. |
| 8 | Seed processing returned, entering physical memory cluster setup. |
| 9 | Memory clusters were initialized, entering VM page loading. |
| A | VM pages were loaded, entering message-buffer setup. |
| B | The message buffer was initialized, updating BIOS mappings. |
| C | Descriptor memory was prepared, entering IDT setup. |
| D | IDT gates were prepared, entering permanent GDT loading. |
| E | Symbol processing completed, entering default interrupt setup. |
| F | `init386` returned. |

The physical pmap-phase test reached lowercase `d` (stage D). This confirms
`pmap_bootstrap` returned, VM pages were loaded, and IDT gates were prepared.
The last confirmed checkpoint is immediately before permanent GDT loading.


Use `init386_trace.py --phase gdt` for the next experiment. This phase
keeps the same orange hexadecimal marker and traces the permanent GDT
instruction sequence as well as the remaining calls.

| Marker | Last confirmed point |
| --- | --- |
| 0 | IDT gates prepared, entering permanent `lgdt`. |
| 1 | The GDT pointer was received, immediately before the `lgdt` instruction. |
| 2 | The `lgdt` instruction completed, before reloading DS. |
| 3 | DS was reloaded, before ES, GS and SS reloads. |
| 4 | FS was reloaded, before the far jump that reloads CS. |
| 5 | Permanent GDT loading returned, entering `lldt`. |
| 6 | `lldt` returned, entering `lidt`. |
| 7 | `lidt` returned, entering debugger setup. |
| 8 | Debugger setup returned, entering Multiboot 1 symbol processing. |
| 9 | Multiboot 1 symbols were absent, entering Multiboot 2 symbol processing. |
| A | Entering fallback symbol boot-info lookup. |
| B | Fallback symbol boot-info was found, entering symbol registration. |
| C | Symbol handling completed, entering the MCA bus probe. |
| D | Entering default interrupt setup. |
| E | Interrupt setup passed, entering debug-register initialization. |
| F | `init386` returned. |

The markers inside `lgdt` also run when that helper is used earlier in
initialization. The final retained character and the numbered 1–7 strip
together identify the latest reached point. All inline patches check their
complete original instructions and replay them after preserving registers
and flags.

The physical GDT-phase test reached **C**. Permanent GDT loading, segment
reloads, LDT/IDT loading, and symbol handling progressed to the checkpoint
immediately before the MCA bus probe. The installer receiver timed out after
180 seconds. The next checkpoint, D before default interrupt setup, was not
observed.

The GDT phase passed the diskless QEMU test with the bootstrap's original
Linux and kexec-tools. NetBSD returned a complete installer report. A separate
run halted just after `init386` returned and retained F on the framebuffer.

Use `init386_trace.py --phase mca` to trace the MCA BIOS call and the following
default interrupt setup. The source confirms that the MCA probe invokes BIOS
INT 15 unless EFI boot information is present. This phase preserves that call.

| Marker | Last confirmed point |
| --- | --- |
| 0 | Entering the MCA bus probe. |
| 1 | MCA registers prepared, entering BIOS INT 15. |
| 2 | Preemption disabled, about to switch to the BIOS page map. |
| 3 | BIOS page map active, before the real-mode trampoline at `0x1000`. |
| 4 | The real-mode trampoline returned. |
| 5 | The kernel page map was restored. |
| 7 | The MCA probe returned, entering default interrupt setup. |
| 8 | Default interrupt setup entered, reserving an IDT vector. |
| 9 | A vector was reserved, entering its handler installation. |
| A | Vectors installed, entering PIC setup. |
| B | PIC setup returned, entering interrupt mutex initialization. |
| C | Default interrupt setup returned, entering debug-register initialization. |
| F | `init386` returned. |

The MCA phase passed the diskless QEMU test with the bootstrap's original
Linux and kexec-tools and returned a complete installer report. The retained
display test confirmed F after `init386` returned. This also checks the marker
renderer across the BIOS page-map switch.

The physical MCA-phase run reached **3**. The BIOS page map was active and
execution reached the checkpoint immediately before the real-mode trampoline
at `0x1000`. Marker 4 after the trampoline returned was not observed.
