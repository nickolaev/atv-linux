CC = clang
LD = ld.lld
TARGET = i386-unknown-none-elf
CFLAGS = --target=$(TARGET) -ffreestanding -fno-stack-protector -fno-pic -fno-builtin -fno-asynchronous-unwind-tables -Wall -Wextra -Werror -O2

all: mach_kernel

entry.o: entry.S
	$(CC) $(CFLAGS) -c $< -o $@

diagnostic.o: diagnostic.c
	$(CC) $(CFLAGS) -c $< -o $@

diagnostic.elf: entry.o diagnostic.o layout.ld
	$(LD) -m elf_i386 --build-id=none -T layout.ld entry.o diagnostic.o -o $@

mach_kernel: diagnostic.elf elf_to_macho.py
	python3 elf_to_macho.py diagnostic.elf $@

probe_trampoline.o: probe_trampoline.S
	$(CC) $(CFLAGS) -c $< -o $@

probe_trampoline.elf: probe_trampoline.o probe_layout.ld
	$(LD) -m elf_i386 --build-id=none -T probe_layout.ld probe_trampoline.o -o $@

test:
	python3 test_diagnostic.py
	python3 test_probe.py

clean:
	rm -f entry.o diagnostic.o diagnostic.elf mach_kernel probe_trampoline.o probe_trampoline.elf

.PHONY: all clean test
