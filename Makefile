all:
	make -C image

# ASD_SYSTEM, ATV1SM and NETBSD_IMAGE must be supplied explicitly.
netbsd-efi-check:
	bash netbsd/build.sh --check --asd-system "$(ASD_SYSTEM)" --atv1sm "$(ATV1SM)" --output "$(NETBSD_IMAGE)"

netbsd-efi:
	sudo bash netbsd/build.sh --asd-system "$(ASD_SYSTEM)" --atv1sm "$(ATV1SM)" --output "$(NETBSD_IMAGE)"

clean:
	make -C image clean
	make -C filesystem clean
