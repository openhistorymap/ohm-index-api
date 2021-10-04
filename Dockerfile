FROM python:3.9

WORKDIR /srv

COPY requirements.txt /srv
RUN pip install -r /srv/requirements.txt

COPY ./app /srv/app
COPY *.json /srv/
COPY run.sh /srv
RUN chmod 755 /srv/run.sh
cmd "/srv/run.sh"