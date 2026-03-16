#!/bin/bash
# MongoDB 7.0 installation for Fedora
# Run with: bash setup_mongodb.sh

echo "Installing MongoDB on Fedora..."

# Create MongoDB repo file
sudo tee /etc/yum.repos.d/mongodb-org-7.0.repo << 'EOF'
[mongodb-org-7.0]
name=MongoDB Repository
baseurl=https://repo.mongodb.org/yum/redhat/9/mongodb-org/7.0/x86_64/
gpgcheck=1
enabled=1
gpgkey=https://www.mongodb.org/static/pgp/server-7.0.asc
EOF

# Install MongoDB
sudo dnf install -y mongodb-org

# Start and enable MongoDB
sudo systemctl start mongod
sudo systemctl enable mongod

echo ""
echo "Checking MongoDB status..."
sudo systemctl status mongod --no-pager

echo ""
echo "Done. MongoDB running on mongodb://localhost:27017/"
