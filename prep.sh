#!/bin/bash

if [[ -z "$(which docker)" ]];
then 
    sudo groupadd docker
    sudo usermod -aG docker ubuntu
    curl -fsSL https://get.docker.com -o get-docker.sh
    chmod +x get-docker.sh
    get-docker.sh
fi
DOCKER_BUILDKIT=1 docker build --no-cache -t adjudicator-local:latest --build-arg user=adjudicator --build-arg uid=1000 --build-arg gid=1000 -f ./Dockerfile .