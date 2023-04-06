all:
	sudo bash build.sh

clean:
	sudo umount ./debian-appletv-filesystem/proc || true
	sudo rm -rf ./debian-appletv-filesystem || true
	sudo rm -f *.tar.xz >/dev/null 2>&1
	sudo rm -f *.md5 >/dev/null 2>&1
