"""Optional instruction-level test of the TARGET_DIAGNOSTIC record.

Set ATV_DIAG_ELF, ATV_DIAG_MACHO and ATV_DIAG_KERNEL to a diagnostic-enabled
build and install Unicorn. The inputs and firmware bytes are entirely synthetic.
"""
import os
import pathlib
import struct
import sys
import unittest

TARGET = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TARGET))


@unittest.skipUnless(all(os.environ.get(x) for x in
                         ('ATV_DIAG_ELF', 'ATV_DIAG_MACHO', 'ATV_DIAG_KERNEL')),
                     'requires a TARGET_DIAGNOSTIC Unicorn build')
class DiagnosticStatusTests(unittest.TestCase):
    def test_actual_shim_status_for_success_and_rejections(self):
        import run_emulated
        from run_unicorn import Elf32
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
        from unicorn.x86_const import UC_X86_REG_CR0, UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ESP

        native = Elf32(os.environ['ATV_DIAG_ELF'])
        kernel = Elf32(os.environ['ATV_DIAG_KERNEL'])
        loads = [program for program in native.programs if program[0] == 1]
        self.assertEqual(len(loads), 1)
        self.assertEqual(loads[0][4], loads[0][5], 'workspace must be file-backed')
        for case, expected_stage, expected_error in (
                ('args', 1, 1), ('map', 2, 2), ('system', 4, 4),
                ('acpi', 5, 5), ('smbios', 5, 5), ('ok', 9, 0)):
            with self.subTest(case=case):
                machine = Uc(UC_ARCH_X86, UC_MODE_32)
                machine.mem_map(0, 0x10000000)
                entry = run_emulated.load_macho(machine, os.environ['ATV_DIAG_MACHO'])
                workspace_start = native.symbol('__bss_start')
                workspace_end = native.symbol('__bss_end')
                self.assertFalse(any(machine.mem_read(workspace_start, workspace_end - workspace_start)),
                                 'file-backed diagnostic workspace was not initialized to zero')
                apple = run_emulated.fixture(machine, case if case in ('acpi', 'smbios') else None,
                                             native.symbol('projected_pages'))
                if case == 'args':
                    apple = 0
                elif case == 'map':
                    machine.mem_write(apple + 0x448, b'\0')
                elif case == 'system':
                    machine.mem_write(0x2b57f10, b'\0')
                seen = []
                writes = []
                protected_writes = []
                def stop(uc, address, size, user_data):
                    seen.append(address)
                    uc.emu_stop()
                machine.hook_add(UC_HOOK_CODE, stop, begin=0x80000, end=0x80000)
                address = native.symbol('nb_enter_native')
                machine.hook_add(UC_HOOK_CODE, stop, begin=address, end=address)
                for kind, _, _, pa, _, size, _, _ in kernel.programs:
                    if kind == 1:
                        machine.hook_add(UC_HOOK_MEM_WRITE,
                                         lambda uc, access, addr, length, value, data: writes.append((addr, length)),
                                         begin=pa, end=pa + size - 1)
                # The standalone high bridge has no reason to write the
                # existing Linux Mach-O or the supplied firmware snapshots.
                for start, end in ((0x02000000, 0x02afd000), (0x02b50000, 0x02b58000),
                                   (0x03020000, 0x03021000), (0x03022000, 0x0302244c)):
                    machine.hook_add(UC_HOOK_MEM_WRITE,
                                     lambda uc, access, addr, length, value, data: protected_writes.append((addr, length)),
                                     begin=start, end=end - 1)
                machine.reg_write(UC_X86_REG_CR0, 0x13)
                machine.reg_write(UC_X86_REG_EAX, apple)
                machine.reg_write(UC_X86_REG_EDX, 0x03024000)
                machine.reg_write(UC_X86_REG_ESP, 0x0300f000)
                machine.mem_write(0x0300f000, struct.pack('<I', 0x80000))
                machine.emu_start(entry, 0x10000000, count=500000000)
                fields = struct.unpack('<12I', machine.mem_read(0x03024000, 48))
                self.assertEqual(fields[:4], (0x47414944, 1, expected_stage, expected_error))
                self.assertEqual(seen, [0x80000])
                self.assertFalse(writes, 'diagnostic modified a kernel destination')
                self.assertFalse(protected_writes, 'diagnostic modified Linux or firmware source data')
                if case == 'smbios':
                    self.assertEqual(fields[8:10], (3, 0x2b54000))
                if case == 'ok':
                    self.assertNotEqual(fields[10], 0)
                    self.assertNotEqual(fields[11], 0)


if __name__ == '__main__':
    unittest.main()
