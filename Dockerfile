FROM python:3.9.18

ADD src /app

WORKDIR /app
RUN pip install -r requirements.txt

CMD ["python", "-u", "xaibot.py"]