
FROM python:3.10-bullseye

COPY requirements.txt /opt/requirements.txt

RUN pip install -U pip
RUN pip install -r /opt/requirements.txt

RUN mkdir -p /opt/.config/matplotlib
ENV MPLCONFIGDIR /opt/.config/matplotlib

WORKDIR /opt/app

