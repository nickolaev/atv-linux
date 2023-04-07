all:
	make -C image
clean:
	make -C image clean
	make -C filesystem clean
