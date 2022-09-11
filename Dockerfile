FROM python:3-alpine

RUN apk add --no-cache --update \
    python3 python3-dev gcc \
    gfortran musl-dev g++ \
    libffi-dev openssl-dev \
    libxml2 libxml2-dev \
    libxslt libxslt-dev \
    libjpeg-turbo-dev zlib-dev

RUN pip install --upgrade pip
RUN pip install pandas
RUN pip install influxdb fitbit cherrypy

COPY cronjobs /etc/crontabs/root
COPY beats.py /
COPY oauth.py /

# start crond with log level 8 in foreground, output to stderr
CMD ["crond", "-f", "-d", "8"]