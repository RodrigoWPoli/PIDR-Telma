#!/bin/bash
# MongoDB 7.0 installation script — Fedora and Ubuntu
# For Windows, see the README.md Setup section.
# Run with: bash setup_mongodb.sh

set -e

# ── Detect OS or prompt user ───────────────────────────────────────────────────
detect_os() {
    if [ -f /etc/fedora-release ]; then
        echo "fedora"
    elif [ -f /etc/lsb-release ] && grep -qi ubuntu /etc/lsb-release; then
        echo "ubuntu"
    elif grep -qi "microsoft" /proc/version 2>/dev/null; then
        echo "ubuntu"  # WSL — treat as Ubuntu
    else
        echo "unknown"
    fi
}

DETECTED=$(detect_os)

echo "MongoDB 7.0 Setup"
echo "─────────────────"
echo ""
echo "Detected OS: $DETECTED"
echo ""
echo "Select your OS:"
echo "  1) Fedora"
echo "  2) Ubuntu (20.04 / 22.04 / 24.04)"
echo ""
read -rp "Choice [1-2] (default: auto-detect): " CHOICE

if [ -z "$CHOICE" ]; then
    case "$DETECTED" in
        fedora)  CHOICE=1 ;;
        ubuntu)  CHOICE=2 ;;
        *) echo "Could not auto-detect. Please enter 1 or 2."; exit 1 ;;
    esac
fi

# ── Fedora ─────────────────────────────────────────────────────────────────────
install_fedora() {
    echo ""
    echo "Installing MongoDB on Fedora..."

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

    echo ""
    echo "Checking MongoDB status..."
    sudo systemctl status mongod --no-pager
}

# ── Ubuntu ─────────────────────────────────────────────────────────────────────
install_ubuntu() {
    echo ""
    echo "Installing MongoDB on Ubuntu..."

    sudo apt-get install -y gnupg curl

    curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
        sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor

    UBUNTU_CODENAME=$(lsb_release -cs 2>/dev/null || echo "jammy")
    case "$UBUNTU_CODENAME" in
        focal|jammy|noble) REPO_CODENAME="$UBUNTU_CODENAME" ;;
        *)
            echo "  Unknown Ubuntu version ($UBUNTU_CODENAME), using jammy repo"
            REPO_CODENAME="jammy"
            ;;
    esac

    echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] \
https://repo.mongodb.org/apt/ubuntu ${REPO_CODENAME}/mongodb-org/7.0 multiverse" | \
        sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list

    sudo apt-get update
    sudo apt-get install -y mongodb-org
    sudo systemctl start mongod
    sudo systemctl enable mongod

    echo ""
    echo "Checking MongoDB status..."
    sudo systemctl status mongod --no-pager
}

# ── Dispatch ───────────────────────────────────────────────────────────────────
case "$CHOICE" in
    1) install_fedora ;;
    2) install_ubuntu ;;
    *) echo "Invalid choice: $CHOICE"; exit 1 ;;
esac

echo ""
echo "Done. MongoDB running on mongodb://localhost:27017/"
