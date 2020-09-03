#!/bin/sh

RELOAD_CODE=42
path="$(dirname "$(readlink -f "$0")")"
python="${path}/env/bin/python"
main="${path}/src/run.py"

if [ ! -f "$python" ]; then
  python="python3"
fi

echo "$python -u $main"
while :; do
    "$python" -u "$main"
    code=$?
    if [ $code -ne $RELOAD_CODE ]; then exit $code; fi
done
