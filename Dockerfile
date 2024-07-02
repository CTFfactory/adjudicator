FROM ubuntu:22.04

### Stage 1

# Ensure scripts are available for use in next command
COPY .idea/scopes/* /.idea/scopes/
COPY ./code/* /code/
COPY ./scripts/* /scripts/
COPY ./requirements.txt /requirements.txt
COPY ./docker /

ARG user
ARG uid
ARG gid

ENV USERNAME $user
RUN useradd -m $USERNAME && \
        echo "$USERNAME:$USERNAME" | chpasswd && \
        usermod --shell /bin/bash $USERNAME && \
        usermod  --uid $uid $USERNAME && \
        groupmod --gid $gid $USERNAME

RUN /bin/bash apt_config.sh && \
    /bin/bash apt_sources.sh && \
    /bin/bash security_updates.sh

RUN apt-get update && apt-get upgrade -y && \
    apt-get install -yqq \
      curl \
      gpg \
      apt-transport-https \
      python3 \
      python3-pip

RUN chmod 777 /run.sh
RUN chown -R adjudicator:adjudicator /code/
RUN chown -R adjudicator:adjudicator /scripts/

# Overlay the root filesystem from this repo
USER ${user}

RUN  /usr/bin/env python3 -m pip install -U pip --user && \
     /usr/bin/env python3 -m pip install -Ur /requirements.txt --user

### Stage 2 
WORKDIR /code/

# NOTE: intentionally NOT using s6 init as the entrypoint
# This would prevent container debugging if any of those service crash
CMD ["/bin/bash", "/run.sh"]
