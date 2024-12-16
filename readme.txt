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


Celery terminal run:
celery -A celery_app worker -l info


For production, need to set the following

         in tasks.py

                QUERY_LIMIT = 100000

                redis_client.setex('map_data', 7200, json.dumps(map_data))    # Run every two hours

                callback_url = 'http://127.0.0.1:5000/map_data_callback'  # Replace with your server address in production.




         in main.py
                scheduler.add_job(scheduled_task, 'interval', seconds=7200)  # Run every two hours



Also,

        if __name__ == '__main__':
            #socketio.run(app, debug=False) # or app.run(debug=False, host='0.0.0.0', port=5000)
            # Make sure to run Deployment using Gunicorn (Recommended for Production)
            socketio.run(app, debug=False, allow_unsafe_werkzeug=True) # or app.run(debug=False, host='0.0.0.0', port=5000)


