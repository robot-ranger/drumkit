#!/bin/bash

#=======================#
# Docker Setup Script
# This script sets up Docker and Docker Compose on Debian/Ubuntu systems.
#=======================#

# Detect the OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo "Cannot detect the OS."
    exit 1
fi

# Set the GPG URL based on the OS
if [ "$OS" = "debian" ]; then
    GPG_URL="https://download.docker.com/linux/debian"
elif [ "$OS" = "ubuntu" ]; then
    GPG_URL="https://download.docker.com/linux/ubuntu"
else
    echo "Unsupported OS: $OS"
    exit 1
fi

echo "Using GPG URL: $GPG_URL"

# Add Docker's official GPG key:
sudo apt update
sudo apt install -y ca-certificates curl python3 python3-pip python3-venv
python3 -m venv .venv
source .venv/bin/activate
pip3 install -r requirements.txt


sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL $GPG_URL/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc



# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] $GPG_URL \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update

sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Create Docker group if it doesn't exist
sudo groupadd docker

# Add user to Docker group
sudo usermod -aG docker $USER

# Prompt user to log out and log back in
echo "Rebooting to enable new docker group permissions..."

# sudo reboot