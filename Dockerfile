FROM python:3.9.18

ADD src /app

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
# Disabled for now, as it's not working in arm64
#chromium \
#chromium-common \
#chromium-driver \
&& rm -rf /var/lib/apt/lists/*
RUN pip install -r requirements.txt

CMD ["python", "-u", "xaibot.py"]