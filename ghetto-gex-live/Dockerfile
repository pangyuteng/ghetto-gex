
FROM python:3.10-bullseye

COPY requirements.txt /opt/requirements.txt

RUN pip install -U pip
RUN pip install -r /opt/requirements.txt

WORKDIR /opt
# original 
RUN git clone https://github.com/Matteo-Ferrara/gex-tracker.git
# RUN git clone https://github.com/pangyuteng/gex-tracker.git


WORKDIR /opt/app

