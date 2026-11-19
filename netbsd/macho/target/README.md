# Current-boot scratch placement prototype

`scratch.c` derives a stack and bootinfo candidate from an explicitly
supplied EFI map rather than from captured addresses. It considers only
write-back, non-runtime conventional memory, subtracts all overlapping
restricted descriptors and page-rounded caller reservations, and avoids the
first MiB. The result is contained within a single conventional descriptor;
the caller selects the address ceiling and sizes. Invalid or insufficient
input fails without modifying the result.

This is a host-testable building block, **not a hardware entry or image**.
The caller must first obtain a trustworthy, current-boot map using a stack
that is safe to use; reserve the complete loader, kernel source/destinations,
both stacks, boot arguments, memory map, bootinfo, framebuffer and all live
firmware objects; and establish physical pointer readability, translation and
object lifetime. The helper cannot infer whether the reservation list is
complete. Its own bounded local arrays require a suitable pre-existing stack.
It does not validate EFI/ACPI objects or initialize a display.

`plan.c` additionally parses the supplied ELF without copying it, verifies
each load destination against the map, reserves the source and destinations,
and returns candidate usable ranges for the experimental native handoff.
`guarded.c` combines this planner with the bounded firmware validator only
under `TARGET_EMULATION_ONLY`. The validator checks a limited ACPI table set,
rejects unknown EFI configuration GUIDs, and cannot establish pointer
readability or lifetime; a successful synthetic test cannot authorize a
hardware transfer.

`entry_emulated.S` and `entry_emulated.c` exercise that pipeline from a
packaged Mach-O with synthetic firmware and identity-mapped memory. The entry,
read callback, layout and build script are explicitly test-only; none is a
production Apple TV loader. The test uses a trusted synthetic read callback
and known memory layout, not validated live firmware addresses.

The emulator entry also exercises `project_efi.c` with nine synthetic entries
using the GUIDs observed in the Linux-time photograph. It validates the
selected synthetic ACPI and SMBIOS objects, preserves their reservations,
copies a projected system table and configuration array into two owned pages,
and rejects invalid selected targets before writing those pages or kernel
destinations. Unknown GUIDs are dropped without following their pointers.
This projection and the selected-entry callbacks remain test-only; observing
the GUIDs does not validate the real pointed-to objects or their lifetimes.

Run the host tests from the repository root:

```sh
python3 -m unittest discover -s netbsd/macho/target -p 'test*.py'
```

On a Linux host with Clang, LLD, objdump, Python and Unicorn, to test an
uncompressed 11.1 kernel, use a **new** output directory:

```sh
bash netbsd/macho/target/build_emulated.sh /path/to/netbsd-INSTALL /tmp/new-target-fixture
python3 netbsd/macho/target/run_emulated.py --native /tmp/new-target-fixture/fixture.elf \
  --macho /tmp/new-target-fixture/fixture.macho --kernel /path/to/netbsd-INSTALL
```
