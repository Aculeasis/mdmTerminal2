#!/bin/bash

user="$(whoami)"
cd "$(dirname "${BASH_SOURCE[0]}")/.."
repo_path=$(pwd)

{
echo '[Unit]'
echo 'Description=MDM Terminal 2'
echo 'After=network.target'


echo '[Service]'
echo 'User='${user}
echo 'ExecStartPre=/bin/sleep 5'
echo 'Environment=VIRTUAL_ENV='${repo_path}'/env'
echo 'Environment=PATH='${repo_path}'/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
echo 'ExecStart='${repo_path}'/env/bin/python -u '${repo_path}'/src/main.py'
echo 'WorkingDirectory='${repo_path}
echo 'StandardOutput=inherit'
echo 'StandardError=inherit'
echo 'Restart=always'
echo 'StartLimitInterval=300'
echo 'StartLimitBurst=10'

echo '[Install]'
echo 'WantedBy=multi-user.target'
} > ${repo_path}/mdmterminal2.service


sudo mv -f ${repo_path}/mdmterminal2.service /etc/systemd/system/mdmterminal2.service

sudo systemctl daemon-reload
sudo systemctl enable mdmterminal2.service
sudo systemctl start mdmterminal2.service

