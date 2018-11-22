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
ARCH="$(uname -m)"

cd "$(dirname "${BASH_SOURCE[0]}")/.."
scripts_dir="$(dirname "${BASH_SOURCE[0]}")"
repo_path=$(pwd)

# make sure we're running as the owner of the checkout directory
RUN_AS="$(ls -ld "$scripts_dir" | awk 'NR==1 {print $3}')"
if [ "$USER" != "$RUN_AS" ]
then
    echo "This script must run as $RUN_AS, trying to change user..."
    exec sudo -u ${RUN_AS} $0
fi

echo 'Подготовка к сборке _snowboydetect.so'
if [ -d "${repo_path}/snow_boy" ]; then
    rm -rf "${repo_path}/snow_boy"
fi
git clone https://github.com/Kitt-AI/snowboy.git "${repo_path}/snow_boy"
cd "${repo_path}/snow_boy"
git checkout 3f5f944
if [ "$ARCH" == "aarch64" ]
then
    echo 'Use dirty hack for aarch64'
    cp -f lib/aarch64-ubuntu1604/libsnowboy-detect.a lib/ubuntu64/libsnowboy-detect.a
fi
cd swig/Python3
echo 'Собираю....'
make
cp -f _snowboydetect.so "${repo_path}/src/lib/"
cd "${repo_path}"
rm -rf "${repo_path}/snow_boy"
echo "Установлено успешно $repo_path/src/lib/_snowboydetect.so"

