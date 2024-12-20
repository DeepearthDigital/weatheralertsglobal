# tasks with Websockets
from celery import Celery
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
import folium
from pymongo import MongoClient, errors as pymongo_errors
import os
from dotenv import load_dotenv
import certifi
from bson import ObjectId
import json
from datetime import datetime, timezone, timedelta
import logging.handlers
import requests  # Import requests
import redis #Import Redis here
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import ssl

def send_request_with_retry(url, data, max_retries=3, backoff_factor=1, status_forcelist=(500, 502, 503, 504)):
    """
    Sends a POST request with retry logic using exponential backoff.

    Args:
        url (str): The URL to send the POST request to.
        data (dict): The JSON data to send in the request body.
        max_retries (int): The maximum number of retry attempts.
        backoff_factor (float): The factor by which to increase the delay between retries.
        status_forcelist (tuple): A set of HTTP status codes to retry.

    Returns:
        requests.Response or None: The Response object if successful, otherwise None.

    Raises:
        requests.exceptions.RequestException: If the request fails after all retry attempts.
    """
    retries = Retry(total=max_retries, backoff_factor=backoff_factor, status_forcelist=status_forcelist)

    # Create an SSL context and set the desired TLS version and CA file
    context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
    context.load_verify_locations(certifi.where())

    adapter = HTTPAdapter(max_retries=retries)
    session = requests.Session()
    session.mount('https://', adapter)

    session.get_adapter('https://').init_poolmanager(
        maxsize=10,
        ssl_context=context,
        connections=10
    )

    try:
        response = session.post(url, json=data)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        celery_logger.exception(f"Error sending request to {url} after {max_retries} retries: ")
        return None

# Create a logger for Celery tasks
celery_logger = logging.getLogger('celery_app')
celery_logger.setLevel(logging.INFO)

# Truncate the log file at the start
log_file_path = 'celery_app.log'
if os.path.exists(log_file_path):
    with open(log_file_path, 'w'):
        pass  # Simply open the file in write mode and immediately close it; this truncates it.

# Create a file handler for Celery task logs
file_handler = logging.handlers.RotatingFileHandler(log_file_path, maxBytes=10 * 1024 * 1024,
                                                    backupCount=5)  # 10MB, 5 backups
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s - %(lineno)d - %(message)s - %(exc_info)s')
file_handler.setFormatter(formatter)
celery_logger.addHandler(file_handler)

load_dotenv()

# Email Configuration (Use environment variables for security!)
MAIL_SERVER = os.environ['MAIL_SERVER']
MAIL_PORT = os.environ['MAIL_PORT']
MAIL_USERNAME = os.environ['MAIL_USERNAME']
MAIL_PASSWORD = os.environ['MAIL_PASSWORD']
MAIL_USE_TLS = True
MAIL_USE_SSL = False
MAIL_DEFAULT_SENDER = os.environ['MAIL_DEFAULT_SENDER']

# MongoDB Configuration=++
MONGODB_URI = os.environ['MONGODB_URI']
WAG_DATABASE_NAME = os.environ['WAG_DATABASE_NAME']
WAG_USERS_COLLECTION_NAME = os.environ['WAG_USERS_COLLECTION_NAME']
WAG_USER_ALERTS_NOTIFICATION_ZONE_COLLECTION_NAME = os.environ['WAG_USER_ALERTS_NOTIFICATION_ZONE_COLLECTION_NAME']
OWA_DATABASE_NAME = os.environ['OWA_DATABASE_NAME']
OWA_COLLECTION_NAME = os.environ['OWA_COLLECTION_NAME']

client = MongoClient(MONGODB_URI, tlsCAFile=certifi.where())
owa_db = client[OWA_DATABASE_NAME]
owa_collection = owa_db[OWA_COLLECTION_NAME]
wag_db = client[WAG_DATABASE_NAME]
wag_collection = wag_db[WAG_USERS_COLLECTION_NAME]
wag_user_alerts_notification_zone_collection = wag_db[WAG_USER_ALERTS_NOTIFICATION_ZONE_COLLECTION_NAME]

# Redis Cloud details from environment variables.
redis_cloud_host = os.environ.get('REDIS_CLOUD_HOST')
redis_cloud_port = os.environ.get('REDIS_CLOUD_PORT')
redis_cloud_password = os.environ.get('REDIS_CLOUD_PASSWORD')
redis_cloud_db = os.environ.get('REDIS_CLOUD_DB', 0)

if not all([redis_cloud_host, redis_cloud_port, redis_cloud_password]):
    raise ValueError("Redis Cloud environment variables are missing.")

try:
    redis_cloud_db = int(redis_cloud_db)
except ValueError:
    raise ValueError("redis_cloud_db must be an integer.")

# print(f"Redis Cloud Host: ")
# print(f"Redis Cloud Port: ")
# print(f"Redis Cloud Password: ")
# print(f"Redis Cloud DB: ")

# Celery configuration
app = Celery('tasks',
             broker=f'redis://:{redis_cloud_password}@{redis_cloud_host}:{redis_cloud_port}/{redis_cloud_db}',
             backend=f'redis://:{redis_cloud_password}@{redis_cloud_host}:{redis_cloud_port}/{redis_cloud_db}')

# print(f"Broker URL: {app.conf.broker_url}")
# print(f"Backend URL: {app.conf.result_backend}")

QUERY_LIMIT = 1000

@app.task(name='generate_map_data_task')
def generate_map_data(future_days=7):
    start_time = time.time()
    celery_logger.info("Generating map data... Celery task started.")
    my_map = folium.Map(location=[51.4779, 0.0015], zoom_start=5)
    alerts = []
    today_utc = datetime.now(timezone.utc)
    today_start_utc = today_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end_utc = today_start_utc + timedelta(days=1)
    today_start_timestamp = int(today_start_utc.timestamp())
    today_end_timestamp = int(today_end_utc.timestamp())
    future_timestamp = int((today_utc + timedelta(days=future_days)).timestamp())

    cursor = owa_collection.find({
        "$or": [
            {"start": {"$gte": today_start_timestamp}, "end": {"$lte": today_end_timestamp}},  # Alerts starting and ending today
            {"start": {"$lt": today_end_timestamp}, "end": {"$gt": today_start_timestamp}},  # Alerts spanning today
            {"start": {"$gte": today_end_timestamp}, "end": {"$lte": future_timestamp}}  # Future alerts within the future_days range

        ]
    }).limit(QUERY_LIMIT)

    explanation = cursor.explain()
    celery_logger.info(f"Query explanation:\n{json.dumps(explanation['executionStats'], indent=2)}")

    for alert_data in cursor:
        try:
            alert = alert_data['alert']
            geometry = alert['geometry']
            msg_type = alert_data['msg_type']
            categories = alert_data['categories']
            urgency = alert_data['urgency']
            severity = alert_data['severity']
            certainty = alert_data['certainty']
            start_timestamp = alert_data['start']
            end_timestamp = alert_data['end']
            sender = alert_data['sender']
            description_data = alert_data['description'][0]
            language = description_data.get('language', 'N/A')
            event = description_data.get('event', 'N/A')
            headline = description_data.get('headline', 'N/A')
            instruction = description_data.get('instruction', 'N/A')
            description = f"<b>Language:</b> {language}<br><b>Event:</b> {event}<br><b>Headline:</b> {headline}<br><b>Instruction:</b> {instruction}"
            center_lat, center_lon = calculate_center(geometry)

            severity_color = {
                'Minor': '#00FF00',
                'Moderate': '#FFA500',
                'Severe': '#FF0000',
                'Extreme': '#313131',
                'Unknown': '#313131'
            }
            color = severity_color.get(severity, '#313131')

            alerts.append({
                'name': f"Alert ({datetime.fromtimestamp(start_timestamp).strftime('%Y-%m-%d %H:%M:%S UTC')} - {datetime.fromtimestamp(end_timestamp).strftime('%Y-%m-%d %H:%M:%S UTC')})",
                'lat': center_lat,
                'lon': center_lon,
                'geometry': geometry,
                'msg_type': msg_type,
                'categories': categories,
                'urgency': urgency,
                'severity': severity,
                'certainty': certainty,
                'start': start_timestamp,
                'end': end_timestamp,
                'sender': sender,
                'description': description,
                'color': color
            })

            folium.GeoJson(geometry, style_function=lambda x: {'fillColor': color, 'color': '#000000', 'weight': 1, 'dashArray': '', 'fillOpacity': 0.5}, name=f"Alert ").add_to(my_map)

        except Exception as e:
            celery_logger.exception("Critical error generating map data:")
            return None  # Indicate failure

        except (KeyError, TypeError, IndexError) as e:
            celery_logger.exception(f"Error processing alert data from MongoDB: ")

    folium.LayerControl().add_to(my_map)
    map_js = my_map.get_root().render()
    end_time = time.time()
    elapsed_time = end_time - start_time
    celery_logger.info(f"Map data generated in {elapsed_time:.4f} seconds. Celery task completed.") #Added this line

    map_data = {'map_js': map_js, 'alerts': alerts}  # Return the data
    celery_logger.info(f"Celery task completed successfully: ")

    # Send the map data to the callback URL - this will trigger the socket.io broadcast.
    callback_url = 'http://0.0.0.0:8080/map_data_callback'  # Replace with your server address in production.
    redis_client = redis.Redis(host=redis_cloud_host, port=redis_cloud_port, password=redis_cloud_password,
                                    db=redis_cloud_db)
    redis_client.set('map_data_task_id', generate_map_data.request.id)  # Set the task ID
    celery_logger.info(f"Task ID {generate_map_data.request.id} saved to Redis.")
    try:
        response = send_request_with_retry(callback_url, data={'map_data': map_data})
        if response and response.status_code == 200:
            redis_client.setex('map_data', 14400, json.dumps(map_data))
            celery_logger.info("Map data update successful, sent via socketio.")
        else:
            celery_logger.error("Map data update failed via SocketIO.")
    except requests.exceptions.RequestException as e:
        celery_logger.exception(f"Error sending request to : ")

    return map_data


def calculate_center(geometry):
    center_lat = 37.0902
    center_lon = -95.7129
    if geometry and geometry['coordinates']:
        if geometry['type'] == 'Polygon':
            coords = geometry['coordinates'][0]
            center_lat = sum(coord[1] for coord in coords) / len(coords)
            center_lon = sum(coord[0] for coord in coords) / len(coords)
        elif geometry['type'] == 'MultiPolygon':
            all_coords = []
            for polygon in geometry['coordinates']:
                all_coords.extend(polygon[0])
            if all_coords:
                center_lat = sum(coord[1] for coord in all_coords) / len(all_coords)
                center_lon = sum(coord[0] for coord in all_coords) / len(all_coords)
        elif geometry['type'] == 'Point':
            center_lat = geometry['coordinates'][1]
            center_lon = geometry['coordinates'][0]
    return center_lat, center_lon


def send_email(recipient, subject, body, mail_server, mail_port, mail_username, mail_password):
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = mail_username
    msg['To'] = recipient
    msg.attach(MIMEText(body, 'plain'))
    celery_logger.info(f"Attempting to send email to ")

    try:
        with smtplib.SMTP(mail_server, mail_port) as server:  # Use SMTP for STARTTLS
            server.starttls()  # Upgrade to TLS
            server.login(mail_username, mail_password)
            server.sendmail(mail_username, recipient, msg.as_string())
            celery_logger.info(f"Email sent successfully to ")  # Use celery_logger
        return True
    except Exception as e:
        celery_logger.exception(f"Email sending failed: ")
        return False


@app.task(name='send_alert_notification_zone_creation_email')
def send_alert_notification_zone_creation_email(email_data, mail_server, mail_port, mail_username, mail_password):
    try:
        recipient = email_data['recipient']
        alert_id = email_data['alert_id']
        alert_name = email_data['alert_name']
        alert_description = email_data['alert_description']
        geojson_str = email_data['geojson_str']
        center_lat = email_data['center_lat']
        center_lon = email_data['center_lon']

        body = f"""You have created a new Active Alert Notification Zone.

Name: {alert_name}
Description: {alert_description}
Creation Time/Date: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
GeoJSON: {geojson_str}
Center Latitude: {center_lat}
Center Longitude: {center_lon}
"""

        success = send_email(recipient, "Active Alert Notification Zone Created", body, mail_server, mail_port,
                             mail_username, mail_password)

        with MongoClient(MONGODB_URI, tlsCAFile=certifi.where()) as client:
            db = client[WAG_DATABASE_NAME]
            collection = db[WAG_USER_ALERTS_NOTIFICATION_ZONE_COLLECTION_NAME]
            collection.update_one(
                {"_id": ObjectId(alert_id)},
                {
                    "$push": {
                        "notifications": {
                            "type": "alert_zone_creation",
                            "timestamp": datetime.now(tz=timezone.utc),
                            "sent": success
                        }
                    }
                }
            )
            if success:
                celery_logger.info(f"Alert zone creation email sent to  for alert ID: ")
            else:
                celery_logger.error(f"Failed to send alert zone creation email to  for alert ID: ")

    except Exception as e:
        celery_logger.exception(f"Error in send_alert_notification_zone_creation_email: ")


@app.task(name='send_weather_alert')
def send_weather_alert(user_email, owa_alert, wag_alert_id):
    """Sends a weather alert email to a user."""
    try:
        # Construct the email based on 'owa_alert' data
        subject = "Weather Alert!"
        body = f"A weather alert has been issued affecting your zone:\n"  # You'll need to format this

        # Update the database to mark the alert as sent or include sent status in email
        with MongoClient(MONGODB_URI, tlsCAFile=certifi.where()) as client:
            db = client[WAG_DATABASE_NAME]
            collection = db[WAG_USER_ALERTS_NOTIFICATION_ZONE_COLLECTION_NAME]
            collection.update_one(
                {"_id": ObjectId(wag_alert_id)},
                {"$push": {
                    "notifications": {"type": "weather_alert", "timestamp": datetime.now(timezone.utc), "sent": True}}}
            )

        send_email(user_email, subject, body, MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD)

    except smtplib.SMTPException as e:
        celery_logger.error(f"SMTP error sending weather alert email to : ")
    except pymongo.errors.PyMongoError as e:
        celery_logger.error(f"Database error updating notification status: ")
    except Exception as e:
        celery_logger.exception(f"Unexpected error sending weather alert email to : ")