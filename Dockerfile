FROM ubuntu:22.04

### Stage 1

# Ensure scripts are available for use in next command
COPY .idea/scopes/* /.idea/scopes/
COPY ./code/* /code/
COPY ./scripts/* /scripts/
COPY ./requirements.txt /requirements.txt
COPY ./docker /

# Create environment variables and process arguments
ARG user
ARG uid
ARG gid
ENV USERNAME=${user}

# Create user from args
RUN useradd -m ${USERNAME} && \
        echo "${USERNAME}:${USERNAME}" | chpasswd && \
        usermod --shell /bin/bash $USERNAME && \
        usermod  --uid $uid $USERNAME && \
        groupmod --gid $gid $USERNAME

### Stage 2

# Configure APT sources and updates
RUN /bin/bash apt_config.sh && \
    /bin/bash apt_sources.sh && \
    /bin/bash security_updates.sh

# Update system and install base packages
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -yqq \
      curl \
      gpg \
      apt-transport-https \
      python3 \
      python3-pip

# Fix permissions
RUN chmod 777 /run.sh
RUN chown -R ${USERNAME}:${USERNAME} /code/
RUN chown -R ${USERNAME}:${USERNAME} /scripts/

# Switch to created user
USER ${user}

# Upgrade PIP to newest version and install PYPI packages
RUN  /usr/bin/env python3 -m pip install -U pip --user && \
     /usr/bin/env python3 -m pip install -Ur /requirements.txt --user

### Stage 3

# Switch to working directory
WORKDIR /code/

# Run /run.sh to start adjudicator
CMD ["/bin/bash", "/run.sh"]
