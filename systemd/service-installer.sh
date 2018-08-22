#!/bin/bash

cp /dev/null mdmterminal2.service

user="$(whoami)"

cd "$(dirname "${BASH_SOURCE[0]}")/.."
repo_path="$PWD"

{
echo '[Unit]'
echo 'Description=MDM Terminal 2'
echo 'After=network.target'


echo '[Service]'
echo 'Environment=VIRTUAL_ENV='$repo_path'/env'
echo 'Environment=PATH='$repo_path'/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
echo 'ExecStart='$repo_path'/env/bin/python -u '$repo_path'/src/main.py'
echo 'WorkingDirectory='$repo_path
echo 'StandardOutput=inherit'
echo 'StandardError=inherit'
echo 'Restart=always'
echo 'User='$user

echo '[Install]'
echo 'WantedBy=multi-user.target'
} > $repo_path/systemd/mdmterminal2.service

sudo cp $repo_path/systemd/mdmterminal2.service /etc/systemd/system/mdmterminal2.service

