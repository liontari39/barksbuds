FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py mailer.py accounts.py webapp.py seed.py meetups.py meetweb.py ./
COPY data-seed ./data-seed
COPY public ./public
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python3", "server.py"]
