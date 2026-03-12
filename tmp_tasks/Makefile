.PHONY: build test clean

build:
	python3 setup.py build_ext --inplace

test: build
	python3 -m pytest tests/ -v

clean:
	rm -rf build/ dist/ *.egg-info
	find . -name '*.so' -delete
	find . -name '*.pyc' -delete
	rm -rf __pycache__
