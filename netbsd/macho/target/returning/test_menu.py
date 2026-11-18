import os
import subprocess
import tempfile
import unittest
from pathlib import Path

MENU = Path(__file__).with_name('menu-status.sh')


class MenuTests(unittest.TestCase):
    def run_status(self, words):
        with tempfile.TemporaryDirectory() as work:
            record = Path(work) / 'record'
            record.write_bytes(b'present')
            source = MENU.read_text().split('\nshow_status\n', 1)[0]
            source = source.replace('exec </dev/console >/dev/console 2>&1', '')
            source = source.replace('/atv-loader-diag.bin', str(record))
            source = 'hexdump() { printf "%s\\n" "$DIAG_TEST_WORDS"; }\n' + source + '\nshow_status\n'
            env = dict(os.environ, DIAG_TEST_WORDS=' '.join(words))
            return subprocess.run(['sh', '-c', source], env=env, text=True,
                                  capture_output=True, check=True).stdout

    def test_success_and_validation_failure(self):
        words = ['47414944', '00000001', '00000009', '00000000'] + ['00000000']*8
        self.assertIn('Dry-run preparation completed', self.run_status(words))
        words[2:4] = ['00000005', '00000005']
        self.assertIn('ACPI, or SMBIOS validation rejected', self.run_status(words))

    def test_low_call_and_missing_completion(self):
        self.assertIn('high call', self.run_status(['31574f4c'] + ['00000000']*11))
        self.assertIn('No completed loader status', self.run_status(['00000000']*12))

    def test_return_state_failure_detail(self):
        words = ['47414944', '00000001', '00000006', '0000000a'] + ['00000000']*4
        words += ['00000703', '01234000', '00000001', '05000cff']
        out = self.run_status(words)
        self.assertIn('EFI configuration entry', out)
        self.assertIn('address=01234000 length=00000001', out)
        self.assertIn('Reason=5 (no single descriptor covers the range)', out)
        self.assertIn('descriptor=12 type=255', out)

    def test_opt_in_export_generates_report_and_starts_server(self):
        with tempfile.TemporaryDirectory() as work:
            record = Path(work) / 'record'
            record.write_bytes(b'capture')
            source = MENU.read_text().split('\nshow_status\n', 1)[0]
            source = source.replace('exec </dev/console >/dev/console 2>&1', '')
            source = source.replace('/atv-loader-diag.bin', str(record))
            # Keep the exported filename literal when substituting the input.
            source = source.replace('"$export_dir' + str(record) + '"', '"$export_dir/atv-loader-diag.bin"')
            source = source.replace('/tmp/atv-loader-export-', work + '/export-')
            source = ('hexdump() { echo "47414944 00000001 00000009 00000000 00000000 00000000 00000000 00000000 00000000 00000000 00000000 00000000"; }\n'
                      'ifconfig() { :; }\nudhcpc() { :; }\nhttpd() { :; }\n' + source + '\nexport_status\nexport_status\n')
            result = subprocess.run(['sh', '-c', source], text=True, capture_output=True, check=True)
            dirs = list(Path(work).glob('export-*'))
            self.assertEqual(len(dirs), 1)
            self.assertEqual((dirs[0] / 'atv-loader-diag.bin').read_bytes(), b'capture')
            self.assertIn('Dry-run preparation completed', (dirs[0] / 'status.txt').read_text())
            self.assertIn(':8080/status.txt', result.stdout)
            self.assertIn('remains available to the local network', result.stdout)

    def test_ethernet_failure_paths(self):
        with tempfile.TemporaryDirectory() as work:
            record = Path(work) / 'record'
            record.write_bytes(b'capture')
            source = MENU.read_text().split('\nshow_status\n', 1)[0]
            source = source.replace('exec </dev/console >/dev/console 2>&1', '')
            source = source.replace('/atv-loader-diag.bin', str(record))
            source = source.replace('"$export_dir' + str(record) + '"', '"$export_dir/atv-loader-diag.bin"')
            source = source.replace('/tmp/atv-loader-export-', work + '/export-')
            for failing in ('udhcpc', 'httpd'):
                mocks = ('hexdump() { echo "47414944 00000001 00000009 00000000 00000000 00000000 00000000 00000000 00000000 00000000 00000000 00000000"; }\n'
                         + '\n'.join(name + '() { ' + ('false' if name == failing else ':') + '; }'
                                     for name in ('ifconfig', 'udhcpc', 'httpd')) + '\n')
                result = subprocess.run(['sh', '-c', mocks + source + '\nexport_status\n'],
                                        text=True, capture_output=True, check=True)
                self.assertIn('DHCP failed' if failing == 'udhcpc' else 'Could not start HTTP server', result.stdout)


if __name__ == '__main__':
    unittest.main()
