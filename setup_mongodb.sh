#!/bin/bash
# MongoDB installation script — auto-detects Ubuntu or Fedora
# Run with: bash setup_mongodb.sh

set -e

detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID"
    else
        echo "unknown"
    fi
}

OS=$(detect_os)
echo "Detected OS: $OS"
echo ""

install_ubuntu() {
    echo "Installing MongoDB 8.0 for Ubuntu 24.04 (Noble)..."

    # Remove any old MongoDB repo files that may cause conflicts
    sudo rm -f /etc/apt/sources.list.d/mongodb-org-7.0.list
    sudo rm -f /etc/apt/sources.list.d/mongodb-org-*.list

    curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | \
        sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor

    echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] \
https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" | \
        sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list

    sudo apt update
    sudo apt install -y mongodb-org

    sudo systemctl start mongod
    sudo systemctl enable mongod
}

install_fedora() {
    echo "Installing MongoDB 7.0 for Fedora..."

    sudo tee /etc/yum.repos.d/mongodb-org-7.0.repo << 'EOF'
[mongodb-org-7.0]
name=MongoDB Repository
baseurl=https://repo.mongodb.org/yum/redhat/9/mongodb-org/7.0/x86_64/
gpgcheck=1
enabled=1
gpgkey=https://www.mongodb.org/static/pgp/server-7.0.asc
EOF

    sudo dnf install -y mongodb-org

    sudo systemctl start mongod
    sudo systemctl enable mongod
}

case "$OS" in
    ubuntu)
        install_ubuntu
        ;;
    fedora)
        install_fedora
        ;;
    *)
        echo "Unsupported OS: $OS"
        echo "Please install MongoDB manually: https://www.mongodb.com/docs/manual/installation/"
        exit 1
        ;;
esac

echo ""
echo "Checking MongoDB status..."
sudo systemctl status mongod --no-pager

echo ""
echo "Done. MongoDB running on mongodb://localhost:27017/"