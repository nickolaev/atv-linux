"""Exercise the BusyBox-compatible, photo-sized report pager."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class MenuPagesTest(unittest.TestCase):
    def test_pages_cover_report_and_wrap(self):
        menu = Path(__file__).with_name('menu.sh').read_text()
        function = menu[menu.index('show_page() {'):menu.index('\nshow_preflight_page() {')]
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / 'report'
            report.write_text(''.join('line-%02d\n' % n for n in range(1, 41)))
            result = subprocess.run(
                ['sh', '-c', function + '\nshow_page "$1" 0 Test\n'
                 'show_page "$1" "$next_page" Test\n'
                 'show_page "$1" "$next_page" Test\n'
                 'show_page "$1" "$next_page" Test\n', 'pager', str(report)],
                capture_output=True, text=True, check=True)
        self.assertIn('page 1/3', result.stdout)
        self.assertIn('page 2/3', result.stdout)
        self.assertIn('page 3/3', result.stdout)
        self.assertEqual(result.stdout.count('line-01\n'), 2)
        for n in range(19, 41):
            self.assertEqual(result.stdout.count('line-%02d\n' % n), 1)

    def test_firmware_report_runs_once_and_pages_cached_result(self):
        menu = Path(__file__).with_name('menu.sh').read_text()
        pager = menu[menu.index('show_page() {'):menu.index('\nshow_preflight_page() {')]
        observer = menu[menu.index('show_firmware_page() {'):menu.index('\nshow_pci_page() {')]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / 'observer'
            report = root / 'report'
            count = root / 'count'
            executable.write_text('#!/bin/sh\nprintf x >> "$COUNT_FILE"\ni=1\nwhile [ "$i" -le 20 ]; do echo "line-$i"; i=$((i+1)); done\n')
            executable.chmod(0o755)
            observer = observer.replace('/atv-observe-firmware', str(executable)).replace(
                '/tmp/atv-firmware-observation.txt', str(report))
            result = subprocess.run(['sh', '-c', pager + '\n' + observer +
                                     '\nfirmware_page=0\nshow_firmware_page\nshow_firmware_page\n'],
                                    env={'COUNT_FILE': str(count)}, capture_output=True, text=True, check=True)
            self.assertEqual(count.read_text(), 'x')
        self.assertIn('page 1/2', result.stdout)
        self.assertIn('page 2/2', result.stdout)
        self.assertIn('line-20', result.stdout)


if __name__ == '__main__':
    unittest.main()
