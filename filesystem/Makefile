all:
	sudo bash build.sh

clean:
	sudo umount ./osmc-appletv-filesystem/proc || true
	sudo umount ./osmc-appletv-filesystem/sys || true
	sudo rm -rf ./osmc-appletv-filesystem || true
	sudo rm -f *.tar.xz >/dev/null 2>&1
