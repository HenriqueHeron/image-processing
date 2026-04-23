#!/usr/bin/env bash
set -e
ports=(22 80 443 81)   # 81 is a port we deliberately did NOT open
for p in "${ports[@]}"; do
	    echo -n "Port $p → "
	        if nc -z -w2 127.0.0.1 "$p"; then
			        echo "OPEN"
				    else
					            echo "BLOCKED"
						        fi
						done
