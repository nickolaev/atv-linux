# Experimental large-payload image packaging

`package.py` prepares a new regular image using the existing HFS+ recovery
builder. Its Mach-O input must already embed the complete, uncompressed i386
kernel ELF; this tool does not provide a disk reader, make a loader, or prove
that the payload is safe on an Apple TV. The emulation fixture is not a
hardware loader and must not be presented as one.

The wrapper verifies the ELF program headers, exact embedded bytes, Mach-O
load-command bounds and executable thread entry. It derives the recovery
partition's hybrid MBR sector count from the resulting CRC-checked GPT, while
preserving the format and saturated CHS fields from a previously working ATV1
diagnostic image. A 96 MiB recovery partition in a 128 MiB image is the
default. This differs from the 32 MB partition tested on hardware: booting the
larger layout remains unverified.

```sh
python3 netbsd/macho/target/packaging/package.py --check \
  --macho /path/to/target-mach_kernel --kernel /path/to/netbsd-INSTALL \
  --reference-image /path/to/working-diagnostic.img --output /path/to/new.img
sudo python3 netbsd/macho/target/packaging/package.py \
  --macho /path/to/target-mach_kernel --kernel /path/to/netbsd-INSTALL \
  --reference-image /path/to/working-diagnostic.img --output /path/to/new.img
```

Builds require the existing builder's Linux tools and loop-device privileges.
The output must not already exist; neither the wrapper nor builder accepts a
physical device as its output. Image creation writes a temporary regular file,
validates its GPT, adds a hybrid MBR, and publishes via a no-replace link.
The `--check` mode validates inputs without building an image. Supplying a
verified kernel and valid Mach-O is not evidence that Apple firmware can load
the payload, that firmware tables remain safe, or that NetBSD boots on ATV1.
