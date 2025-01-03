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


Terminal run for Celery and Main (Pycharm or GCP):
celery -A tasks worker --loglevel=info
celery -A tasks beat --loglevel=INFO


gunicorn -b :8080 main:app --worker-class gevent
gunicorn -b 0.0.0.0:8080 main:app --worker-class gevent -w 5

THIS ONE!
gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 main:app -b 0.0.0.0:8080

gunicorn -b 0.0.0.0:8080 main:app --worker-class gevent

if you need to stop processs locally then

            lsof -i :8080
            kill
            lsof -i :8080 | awk 'NR!=1 {print $2}' | xargs kill
