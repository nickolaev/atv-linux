# Optional network diagnostic bootstrap (prototype)

`bootstrap.sh` defines `network_bootstrap` for a future returning Linux menu.
It has not been packaged into a USB image or tested on the Apple TV. Selecting
it configures DHCP, downloads a shell diagnostic into `/tmp`, checks an
operator-supplied SHA-256, and requires an explicit local `yes` before running
it. Its output is served on port 8081. The launcher itself does not write to
physical disks; a diagnostic script has full root privileges and could do so.
Use only trusted scripts and a trusted LAN: HTTP and report export are
unencrypted and unauthenticated, and the digest must come from a trusted
separate channel. The size limit is 8192 units of the shell's `ulimit -f`.

This runs under the *existing Linux kernel*. It does not recreate Apple EFI
entry state, launch NetBSD, or make stale EFI pointers safe. Existing distro
menu code uses `/sbin/kexec` for Linux kernels, but the running diagnostic's
actual kexec capability and a correct NetBSD handoff remain unverified.
Network logs after NetBSD takes over require separate NetBSD-side support.

`poll.sh HTTP_BASE_URL BEARER_TOKEN` is an alternative after a one-time local
opt-in and DHCP setup. It polls `/manifest` (one line: job ID and lowercase
SHA-256), fetches `/payload/ID`, verifies the digest, and executes each new ID
once. It serves the latest output at port 8081. The development host must
authenticate the bearer token. HTTP sends both token and content in cleartext;
the digest is delivered by that same host and is not a defense against a LAN
attacker. This is suitable only for an isolated trusted network. Payloads run
as root and can write disks; the launcher cannot enforce otherwise. The poller
has not been integrated into an image or tested on the Apple TV.
The poller limits payload files to 65536 shell file-limit units (at least
32 MiB with 512-byte units), sufficient for the staged 23 MiB kernel; tmpfs
space and free memory must still be checked on the actual 256 MiB device.

The experimental signed controller reports newly observed session nonces from
manifest requests. Those requests are unauthenticated: treat a reported nonce
as unverified until `fetch-signed` authenticates a report for that session and
the expected job sequence. Signed report verification is currently stateless;
an older valid running snapshot can be replayed after a final snapshot for the
same job. HTTP also provides no confidentiality. This remains a prototype,
not a released or hardware-tested network service.

For a trusted, isolated development network, a host can serve a shell job with:

```sh
python3 netbsd/macho/network_bootstrap/controller.py serve ./diagnostic.sh \
  --bind HOST_LAN_IP --token RANDOM_TOKEN
```

After the future bootstrap has enabled Ethernet, run on the Apple TV:

```sh
sh /path/to/poll.sh http://HOST_LAN_IP:8082 RANDOM_TOKEN
```

Retrieve the current report on the host with `python3 controller.py fetch
APPLE_TV_IP`. Restart the controller with another script to publish another
job. The controller currently serves shell scripts, not NetBSD kernels.
By default an identical payload retains the same job ID; pass a new
`--job-id` to deliberately rerun it. Failed downloads and digest mismatches
are retried; once a verified job starts, it is not repeated during that poller
session, even if it exits unsuccessfully.
Jobs receive `/dev/null` as input. A watchdog sends TERM after 120 seconds and
KILL five seconds later to the job's process group. This is not a sandbox: a
job can create a new session or otherwise escape supervision. The file-size
limit also affects any files a job writes, not just the report. This prototype
must not be enabled in an image before authentication and supervision are
independently reviewed.

**Supervision remains unverified.** A BusyBox 1.18.4 test on `mbp` killed a
TERM-ignoring group leader with status 137, but the process group still appeared
present immediately afterwards; child reaping and cleanup are not proven.
Stopping the shell watchdog can also leave its `sleep` child behind. Do not use
this prototype to run unattended jobs until those cases are resolved.
