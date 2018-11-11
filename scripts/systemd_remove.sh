#!/bin/bash

sudo systemctl stop mdmterminal2.service
sudo systemctl disable mdmterminal2.service
sudo rm /etc/systemd/system/mdmterminal2.service
sudo systemctl daemon-reload
