#!/bin/bash
# Copyright 2017 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -o errexit

USER="$(whoami)"
cd "$(dirname "${BASH_SOURCE[0]}")/.."
scripts_dir="$(dirname "${BASH_SOURCE[0]}")"
install_path=$(pwd)

# make sure we're running as the owner of the checkout directory
RUN_AS="$(ls -ld "$scripts_dir" | awk 'NR==1 {print $3}')"
if [ "$USER" != "$RUN_AS" ]
then
    echo "This script must run as $RUN_AS, trying to change user..."
    exec sudo -u "${RUN_AS}" "$0"
fi

sudo apt-get update -y
sed 's/#.*//' "${install_path}/Requirements/system-requirements.txt" | xargs sudo apt-get install -y --no-install-recommends


if ! [ -d ~/tmp ]; then
    mkdir ~/tmp
fi

python3 -m venv env
source env/bin/activate
export TMPDIR=~/tmp
pip install --upgrade pip setuptools wheel
pip install -r "${install_path}/Requirements/pip-requirements.txt"

rm -R ~/tmp

chmod +x "${install_path}/src/main.py"
chmod +x "${install_path}/scripts/snowboy_build.sh"
chmod +x "${install_path}/scripts/systemd_install.sh"

if [ ! -f "${install_path}/src/detectors/snowboy/_snowboydetect.so" ]; then
    echo ""
    SWIG_VERSION="$(swig -version | grep -i Version | \
	sed "s/^.* //g" | sed -e "s/\.\([0-9][0-9]\)/\1/g" -e "s/\.\([0-9]\)/0\1/g" -e "s/^[0-9]\{3,4\}$$/&00/")"
    if [ ! "$SWIG_VERSION" -ge 30010 ]; then
        echo "#################################################################"
        echo "  Внимание! Для сборки snowboy нужен swig не ниже 3.0.10,"
        echo "  Установлен $(swig -version | grep -i Version)"
        echo "  Если терминал не запустится, обновите swig вручную и пересоберите snowboy"
        echo "  См. https://github.com/Aculeasis/mdmTerminal2#сборка-snowboy-_snowboydetectso"
        echo "##################################################################"
        echo ""
        exit 0
    fi
    "${install_path}/scripts/snowboy_build.sh"
fi

echo "Установка завершена"
