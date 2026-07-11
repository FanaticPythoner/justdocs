# justdocs-config: {{ config_json }}

default:
    @just --list

install:
    @justdocs projects install --root .

check:
    @justdocs projects check --root .

build:
    @justdocs projects build --root .

serve:
    @justdocs projects serve --root .

serve-clean:
    @justdocs projects serve-clean --root .

free-port:
    @justdocs projects free-port --root .

clean:
    @justdocs projects clean --root .

dist-clean:
    @justdocs projects dist-clean --root .
