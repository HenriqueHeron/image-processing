#!/bin/bash

set -e

echo "Setting up firewall rules..."

if command -v ufw &> /dev/null; then
    echo "Using UFW firewall"
    
    ufw default deny incoming
    ufw default allow outgoing
    
    ufw allow 22/tcp
    ufw allow 80/tcp
    ufw allow 443/tcp
    
    ufw --force enable
elif command -v firewall-cmd &> /dev/null; then
    echo "Using firewalld"
    
    firewall-cmd --permanent --add-service=ssh
    firewall-cmd --permanent --add-service=http
    firewall-cmd --permanent --add-service=https
    
    firewall-cmd --reload
else
    echo "Loading iptables rules..."
    
    if [ -f "$(dirname "$0")/iptables.rules" ]; then
        iptables-restore < "$(dirname "$0")/iptables.rules"
    fi
fi

echo "Firewall setup complete"