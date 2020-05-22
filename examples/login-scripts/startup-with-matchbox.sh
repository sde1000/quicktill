#!/bin/bash

matchbox-window-manager -use_titlebar no -use_cursor no &
xset s off
runtill -c mainbar -l till.log start \
	--gtk \
	--keyboard \
	-e 0 "Exit / restart till software" \
	-e 2 "Power off till" \
	-e 3 "Reboot till" \
	-i 4
tillstatus="$?"
sleep 2
case "$tillstatus" in
    0) exit ;;
    2) userv root poweroff ;;
    3) userv root reboot ;;
    4) echo "Idle - restarting" ; exit ;;
esac
sleep 1
exit
