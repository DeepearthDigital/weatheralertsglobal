This is the framework for Google Cloud Functions which send the data from the webhook to the MongoDB.

Make sure to set environment variables within Google Cloud Functions eg;
'MONGO_URI'
'MONGO_DBNAME'
'MONGO_COLLECTION'

Also include requirements.txt, run pip freeze > requirements.txt from local project to list all requirements to txt file.

And don't forget to whitelist the sender IP addresss for the MongoDB server within 'MongoDB Network'


Requirements.txt creation
pip freeze > requirements.txt

Or installation
pip install -r requirements.txt


Google Cloud Environment Variables

Go to Cloud Run page in your Console
Click on the service you want to configure
Click on the edit button
Go to the "Variables" tab, where you can set environment variables that will be available to your application.


Celery
Terminal run for Celery and Main (Pycharm or GCP):
celery -A tasks:app worker --loglevel=info -c 10 --pool=gevent

Beat
celery -A tasks:app beat --loglevel=info


Main
gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 5 main:app -b 0.0.0.0:8080
gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 main:app -b 0.0.0.0:8080 --log-level debug

Local testing
gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 5 main:app -b localhost:8080 --log-level debug


gunicorn -b 0.0.0.0:8080 main:app --worker-class gevent

if you need to stop processs locally then

            lsof -i :8080
            kill
            lsof -i :8080 | awk 'NR!=1 {print $2}' | xargs kill
            lsof -i :8080 | awk 'NR!=1 {print $2}' | xargs kill -9

celery -A tasks inspect active


curl -X POST -d 'username=simon@deepearth.digital&password=sydjes-1finjA-jevbor' -c cookies.txt  http://localhost:8080/login


