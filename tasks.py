# tasks with Websockets
# Patch gevent *before* Flask and SocketIO
from gevent import monkey

monkey.patch_all()
import geventwebsocket
import certifi
from celery import Celery
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
import folium
from pymongo import MongoClient, errors as pymongo_errors
import pymongo
import os
from dotenv import load_dotenv
from bson import ObjectId, json_util
import json
from datetime import datetime, timezone, timedelta
import logging.handlers
import requests
import redis
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import ssl
from shapely.geometry import shape, mapping
from shapely.ops import transform
import pyproj
from functools import partial
import geojson
import math
from celery.schedules import crontab
from celery.result import AsyncResult
import logging.config
import logging
from celery import shared_task
from flask import current_app

load_dotenv()

# Email Configuration (Use environment variables for security!)
MAIL_SERVER = os.environ['MAIL_SERVER']
MAIL_PORT = os.environ['MAIL_PORT']
MAIL_USERNAME = os.environ['MAIL_USERNAME']
MAIL_PASSWORD = os.environ['MAIL_PASSWORD']
MAIL_USE_TLS = True
MAIL_USE_SSL = False
MAIL_DEFAULT_SENDER = os.environ['MAIL_DEFAULT_SENDER']

# Google Maps
GOOGLE_MAPS_API_KEY = os.environ['GOOGLE_MAPS_API_KEY']

# MongoDB Configuration=++
MONGODB_URI = os.environ['MONGODB_URI']
WAG_DATABASE_NAME = os.environ['WAG_DATABASE_NAME']
WAG_USERS_COLLECTION_NAME = os.environ['WAG_USERS_COLLECTION_NAME']
WAG_USER_ALERTS_NOTIFICATION_ZONE_COLLECTION_NAME = os.environ['WAG_USER_ALERTS_NOTIFICATION_ZONE_COLLECTION_NAME']
OWA_DATABASE_NAME = os.environ['OWA_DATABASE_NAME']
OWA_COLLECTION_NAME = os.environ['OWA_COLLECTION_NAME']

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

redis_client = redis.Redis(host=redis_cloud_host, port=redis_cloud_port, password=redis_cloud_password,
                           db=redis_cloud_db)

# Celery configuration
app = Celery('tasks',
             broker=f'redis://:{redis_cloud_password}@{redis_cloud_host}:{redis_cloud_port}/{redis_cloud_db}',
             backend=f'redis://:{redis_cloud_password}@{redis_cloud_host}:{redis_cloud_port}/{redis_cloud_db}')
app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    worker_heartbeat_interval=120,
)

# Create a logger for the Celery app
APP_LOGGER_NAME = 'celery-weather-alerts-global'
app_logger = logging.getLogger(APP_LOGGER_NAME)
app_logger.setLevel(logging.INFO)

# Create a formatter for both file and stream handlers
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s - %(lineno)d - %(message)s')

# Check if running locally, if not, log to stdout only.
if os.environ.get('ENVIRONMENT') != 'PRODUCTION':
    # Truncate the log file at the start
    log_file_path = 'celery-weather-alerts-global.log'
    with open(log_file_path, 'w'):
        pass  # This line erases the file

    # Create a file handler for local development
    file_handler = logging.handlers.RotatingFileHandler(log_file_path, maxBytes=10 * 1024 * 1024, backupCount=5)
    file_handler.setFormatter(formatter)
    app_logger.addHandler(file_handler)

# Create a stream handler for app logs (to stdout for both local/GCP)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
app_logger.addHandler(stream_handler)

# Log that the app is started
app_logger.info(f"Celery application logger created, logging started for {APP_LOGGER_NAME}")

celery_config = {
    "worker_log_format": '[%(asctime)s: %(levelname)s/%(processName)s] %(message)s',
    "worker_task_log_format": '[%(asctime)s: %(levelname)s/%(processName)s] %(message)s',
    "log_level": "INFO",
    "task_default_queue": "celery",
    "worker_hijack_root_logger": False,
    'task_routes': {
        'tasks.keep_recent_entries_efficient': {'queue': 'celery-map-data'},
        'tasks.generate_map_data_task': {'queue': 'celery-map-data'},
        'tasks.populate_map_data_if_needed': {'queue': 'celery-map-data'},
        'tasks.find_matching_owa_alerts_task': {'queue': 'celery-alert-matching'},
        'tasks.process_matching_alerts': {'queue': 'celery-alert-processing'},
        'tasks.check_for_and_send_alerts': {'queue': 'celery-alert-processing'},
        'tasks.send_alert_notification_zone_creation_email': {'queue': 'celery-email'},
        'tasks.send_weather_alert': {'queue': 'celery-email'},
        'tasks.send_weather_alert_email': {'queue': 'celery-email'},
    },
}

# Database connections using MongoClient
mongo_client = MongoClient(MONGODB_URI, tlsCAFile=certifi.where())
owa_db = mongo_client[OWA_DATABASE_NAME]
owa_collection = owa_db[OWA_COLLECTION_NAME]
wag_db = mongo_client[WAG_DATABASE_NAME]
wag_collection = wag_db[WAG_USERS_COLLECTION_NAME]
wag_user_alerts_notification_zone_collection = wag_db[WAG_USER_ALERTS_NOTIFICATION_ZONE_COLLECTION_NAME]

MAP_DATA_CALLBACK_URL = os.getenv('MAP_DATA_CALLBACK_URL')


def get_mongo_client():
    client = MongoClient(MONGODB_URI)
    return client[MONGODB_DATABASE]


# Define a function to format timestamps for alert names
def format_timestamp(timestamp):
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S UTC')


# Define a function for creating redis client
def create_redis_client():
    return redis.Redis(host=redis_cloud_host, port=redis_cloud_port, password=redis_cloud_password,
                       db=redis_cloud_db)


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
        app_logger.info(f"Sending POST request to: {url} with data sample: {str(data)[:100]}...")
        response = session.post(url, json=data)
        response.raise_for_status()
        app_logger.info(
            f"Successful POST request to: {url}, Status Code: {response.status_code}, Response Text: {response.text}")
        return response
    except requests.exceptions.RequestException as e:
        app_logger.exception(f"Error sending request to {url} after {max_retries} retries: ")
        if 'response' in locals() and response:
            app_logger.error(f"Response status code: {response.status_code}")
        return None


# Trim the database
@app.task(name='keep_recent_entries_efficient')
def keep_recent_entries_efficient(days_to_keep=1):
    try:
        today_utc = datetime.now(timezone.utc)
        retention_cutoff_utc = today_utc - timedelta(days=days_to_keep)
        retention_cutoff_timestamp = int(retention_cutoff_utc.timestamp())

        # Delete only alerts that are completely in the past
        result = owa_collection.delete_many({"end": {"$lte": retention_cutoff_timestamp}})
        app_logger.info(f"Deleted {result.deleted_count} entries completely in the past.")
    except Exception as e:
        app_logger.exception("Error cleaning up entries:")


@app.task(name='generate_map_data_task')
def generate_map_data_task(future_days=14, page=1, page_size=3000, total_alerts=0):
    start_time = time.time()
    app_logger.info(
        f"Generating map data task... Celery task started. QUERY_LIMIT_BATCH: , QUERY_LIMIT: , Page: {page}, Page Size: {page_size}")
    my_map = folium.Map(location=[51.4779, 0.0015], zoom_start=5)
    alerts = []  # Initialize if passed.

    today_utc = datetime.now(timezone.utc)
    today_start_utc = today_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end_utc = today_start_utc + timedelta(days=1)
    today_start_timestamp = int(today_start_utc.timestamp())
    today_end_timestamp = int(today_end_utc.timestamp())
    future_timestamp = int((today_utc + timedelta(days=future_days)).timestamp())

    total_alerts = owa_collection.count_documents({
        "$or": [
            {"start": {"$gte": today_start_timestamp}, "end": {"$lte": today_end_timestamp}},
            # Alerts starting and ending today
            {"start": {"$lt": today_end_timestamp}, "end": {"$gt": today_start_timestamp}},  # Alerts spanning today
            {"start": {"$gte": today_end_timestamp}, "end": {"$lte": future_timestamp}}
            # Future alerts within the future_days range

        ]
    })
    if total_alerts == 0:
        app_logger.info(f"Total alerts is 0. Halting map data generation.")

    total_pages = (total_alerts + page_size - 1) // page_size
    if page > total_pages:
        app_logger.info(f"Requested page is greater than the total number of pages. Halting map data generation.")
        return {'map_js': "", 'alerts': [], 'total_pages': total_pages,
                'page': page}  # Exit early if page is out of range

    skip = (page - 1) * page_size

    cursor = owa_collection.aggregate([
        {
            "$match": {
                "$or": [
                    {"start": {"$gte": today_start_timestamp}, "end": {"$lte": today_end_timestamp}},
                    {"start": {"$lt": today_end_timestamp}, "end": {"$gt": today_start_timestamp}},
                    {"start": {"$gte": today_end_timestamp}, "end": {"$lte": future_timestamp}}
                ]
            }
        },
        {
            "$addFields": {
                "alert_key": {
                    "$concat": [
                        {"$toString": "$start"},
                        {"$toString": "$end"}
                    ]
                }
            }
        },
        {
            "$group": {
                "_id": "$alert_key",
                "doc": {"$first": "$$ROOT"}
            }
        },
        {
            "$replaceRoot": {"newRoot": "$doc"}
        },
        {
            "$skip": skip
        },
        {
            "$limit": page_size
        },
        {
            "$project": {
                'alert': 1, 'msg_type': 1, 'categories': 1,
                'urgency': 1, 'severity': 1, 'certainty': 1, 'start': 1, 'end': 1, 'sender': 1,
                'description': 1, 'alert_key': 1
            }
        }
    ])

    for alert_data in cursor:
        try:
            alert = alert_data['alert']
            center_lat, center_lon = calculate_center(alert['geometry'])
            geometry = alert['geometry']

            # Simplify the geometry using shapely
            try:
                original_shape = shape(geometry)

                # Define the projections using the correct syntax
                target_crs = f'epsg:326{int(1 + (center_lon + 180) / 6)}'
                project_wgs_to_utm = partial(
                    pyproj.Transformer.from_crs("epsg:4326", target_crs, always_xy=True).transform,
                )

                # Define inverse projection for transform back
                project_utm_to_wgs = partial(
                    pyproj.Transformer.from_crs(target_crs, "epsg:4326", always_xy=True).transform,
                )

                simplified_shape = transform(project_wgs_to_utm, original_shape).simplify(tolerance=20).buffer(0)
                simplified_geometry = mapping(transform(project_utm_to_wgs, simplified_shape))
                geometry = simplified_geometry
            except Exception as e:
                app_logger.exception(f"Error simplifying geometry for alert id: {alert_data.get('_id')}")

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
            description = f"""
                    <p><b>Language:</b> {language}</p>
                    <p><b>Event:</b> {event}</p>
                    <p><b>Headline:</b> {headline}</p>
                    <p><b>Instruction:</b> {instruction}</p>
            """
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
                'name': f"Alert ({format_timestamp(start_timestamp)} - {format_timestamp(end_timestamp)})",
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
                'language': language,
                'event': event,
                'headline': headline,
                'instruction': instruction,
                'color': color,
                'id': alert_data['alert_key']
            })

            folium.GeoJson(geometry, style_function=lambda x: {'fillColor': color, 'color': '#000000', 'weight': 1,
                                                               'dashArray': '', 'fillOpacity': 0.5},
                           name=f"Alert ").add_to(my_map)

        except Exception as e:
            app_logger.exception("Critical error generating map data:")
            return None  # Indicate failure

        except (KeyError, TypeError, IndexError) as e:
            app_logger.exception(f"Error processing alert data from MongoDB: ")

    folium.LayerControl().add_to(my_map)
    map_js = my_map.get_root().render()
    end_time = time.time()
    elapsed_time = end_time - start_time
    app_logger.info(f"Map data generated in {elapsed_time:.4f} seconds. Celery task completed.")  # Added this line

    map_data = {'map_js': map_js, 'alerts': alerts, 'total_pages': total_pages, 'page': page}

    # Add the timestamp here!
    cache_timestamp = datetime.now(timezone.utc).isoformat()
    map_data['cache_timestamp'] = cache_timestamp

    redis_client = create_redis_client()

    if page == 1:
        app_logger.info(f"Setting Redis key 'temp_map_data'")
    else:
        # For pages > 1, attempt to get the existing data and append the new alerts.
        existing_map_data_json = redis_client.get('temp_map_data')
        if existing_map_data_json:
            existing_map_data = json.loads(existing_map_data_json)
            existing_map_data['alerts'].extend(map_data['alerts'])
            map_data = existing_map_data
    redis_client.set('temp_map_data', json.dumps(map_data))

    app_logger.info(f"Celery task completed successfully: ")

    # Send the map data to the callback URL - this will trigger the socket.io broadcast.
    redis_client.set('map_data_task_id', generate_map_data_task.request.id)  # Set the task ID
    app_logger.info(f"Task ID {generate_map_data_task.request.id} saved to Redis for generate_map_data.")
    try:
        response = send_request_with_retry(MAP_DATA_CALLBACK_URL, data={'map_data': map_data})
        if response and response.status_code == 200:
            # Now include the timestamp when saving to Redis
            if page == 1:
                app_logger.info(f"Setting Redis key 'temp_map_data'")
                redis_client.set('temp_map_data', json.dumps(map_data))
            app_logger.info("Map data update successful, sent via socketio.")
        else:
            app_logger.error("Map data update failed via SocketIO.")
    except requests.exceptions.RequestException as e:
        app_logger.exception(f"Error sending request to : ")
        raise e  # Instead of return None, raise the exception

    return map_data


@app.task(name='populate_map_data_if_needed')
def populate_map_data_if_needed():
    """Check if we need to regenerate the map data"""
    try:
        map_data_json = redis_client.get('map_data')
        cached_task_id = redis_client.get('map_data_task_id')
        if not map_data_json or not cached_task_id:
            app_logger.info("Map data not found in Redis or Task ID is missing. Generating...")
            generate_map_data_task.apply_async()
            cache_map_data_task.apply_async()
            return
        app_logger.info(f"Task ID {cached_task_id} retrieved from Redis.")
        task = app.AsyncResult(cached_task_id.decode('utf-8'))
        if task.status in ['PENDING', 'STARTED', 'RETRY']:
            app_logger.info(
                f"Map data found in Redis, and a task with id: {cached_task_id.decode('utf-8')} is already running.")
            cache_map_data_task.apply_async()
            return
        else:
            app_logger.info("Previous task finished, and map data found in Redis. Regenerating data...")
            generate_map_data_task.apply_async()
            cache_map_data_task.apply_async()
    except ConnectionError as e:
        app_logger.error(f"Redis connection error: ")
    except Exception as e:
        app_logger.exception("Error checking or populating map data:")


@app.task(name='cache_map_data_task')
def cache_map_data_task():
    while True:
        cached_task_id = redis_client.get('map_data_task_id')

        if cached_task_id is not None:
            task = app.AsyncResult(cached_task_id.decode('utf-8'))

            if task.state == 'SUCCESS':
                # The map data has finished generating and can now be saved to the main key
                temp_data = redis_client.get('temp_map_data')  # Get the temp data

                if temp_data is not None:
                    redis_client.set('map_data', temp_data)  # Save the temp data to main key
                    redis_client.delete('temp_map_data')  # Now you can delete the temp key
                else:
                    app_logger.info("No temporary map data available.")
                    break
            elif task.state in ['FAILURE', 'REVOKED']:
                # The task failed, no new map data will be arriving
                break

        # Wait between checks
        time.sleep(5)


@app.task(name='find_matching_owa_alerts_task')
def find_matching_owa_alerts(wag_zone_geometry, future_days=14):
    """
    Finds matching OWA alerts within a given geometry and time range, using the logic from generate_map_data_task.
    """
    try:
        # Validate geometry before querying.
        geojson.loads(json.dumps(wag_zone_geometry))
        if wag_zone_geometry['type'] not in ['Polygon', 'MultiPolygon', 'Point', 'LineString']:
            app_logger.info(f"Invalid geometry type in find_matching_owa_alerts: {wag_zone_geometry['type']}")
            return []  # Return empty list for invalid geometry

        today_utc = datetime.now(timezone.utc)
        today_start_utc = today_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end_utc = today_start_utc + timedelta(days=1)
        today_start_timestamp = int(today_start_utc.timestamp())
        today_end_timestamp = int(today_end_utc.timestamp())
        future_timestamp = int((today_utc + timedelta(days=future_days)).timestamp())

        redis_client = create_redis_client()
        cached_map_data = redis_client.get('map_data')
        if cached_map_data:
            try:
                map_data = json.loads(cached_map_data)
                alerts = map_data.get('alerts', [])
                formatted_alerts = []
                for alert in alerts:
                    try:
                        # Validate the geometry with the GeoJson lib
                        geojson.loads(json.dumps(alert['geometry']))
                        alert_shape = shape(alert['geometry'])

                        # Perform geometry intersection check
                        wag_zone_shape = shape(wag_zone_geometry)
                        if wag_zone_shape.intersects(alert_shape):
                            formatted_alerts.append({
                                'geometry': alert['geometry'],
                                'msg_type': alert['msg_type'],
                                'categories': alert['categories'],
                                'urgency': alert['urgency'],
                                'severity': alert['severity'],
                                'certainty': alert['certainty'],
                                'start': alert['start'],
                                'end': alert['end'],
                                'sender': alert['sender'],
                                'description': alert['description'],
                                'language': alert.get('language', 'N/A'),  # Use .get to safely access language
                                'event': alert.get('event', 'N/A'),  # Use .get to safely access language
                                'headline': alert.get('headline', 'N/A'),  # Use .get to safely access language
                                'instruction': alert.get('instruction', 'N/A'),  # Use .get to safely access language
                                'color': alert['color'],
                                'id': alert['id']
                            })
                    except (KeyError, TypeError) as e:
                        app_logger.exception(f"Error processing cached alert data: ")
                        continue
                return formatted_alerts
            except json.JSONDecodeError:
                app_logger.error("Error decoding cached map data from Redis.")
                # Fallback to database query if we cannot use cached data.

            cursor = owa_collection.aggregate([
                {
                    "$match": {
                        "$or": [
                            {"start": {"$gte": today_start_timestamp}, "end": {"$lte": today_end_timestamp}},
                            {"start": {"$lt": today_end_timestamp}, "end": {"$gt": today_start_timestamp}},
                            {"start": {"$gte": today_end_timestamp}, "end": {"$lte": future_timestamp}}
                        ],
                        "alert.geometry": {
                            "$geoIntersects": {
                                "$geometry": wag_zone_geometry
                            }
                        }
                    }
                },
                {
                    "$addFields": {
                        "alert_key": {
                            "$concat": [
                                {"$toString": "$start"},
                                {"$toString": "$end"}
                            ]
                        }
                    }
                },
                {
                    "$group": {
                        "_id": "$alert_key",
                        "doc": {"$first": "$$ROOT"}
                    }
                },
                {
                    "$replaceRoot": {"newRoot": "$doc"}
                },

                {
                    "$project": {
                        'alert': 1, 'msg_type': 1, 'categories': 1,
                        'urgency': 1, 'severity': 1, 'certainty': 1, 'start': 1, 'end': 1, 'sender': 1,
                        'description': 1, 'alert_key': 1
                    }
                }
            ])

            formatted_alerts = []
            for alert_data in cursor:
                try:
                    # Extract information from the database
                    geometry = alert_data['alert']['geometry']
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
                    description = f"<b>Language:</b> <br><b>Event:</b>  <br><b>Headline:</b> <br><b>Instruction:</b> "

                    # Calculate colour based on severity
                    severity_color = {
                        'Minor': '#00FF00',
                        'Moderate': '#FFA500',
                        'Severe': '#FF0000',
                        'Extreme': '#313131',
                        'Unknown': '#313131'
                    }
                    color = severity_color.get(severity, '#313131')

                    formatted_alerts.append({
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
                        'language': language,
                        'event': event,
                        'headline': headline,
                        'instruction': instruction,
                        'color': color,
                        'id': alert_data['alert_key']

                    })
                except (KeyError, TypeError, IndexError) as e:
                    app_logger.exception(f"Error processing alert data from MongoDB: {e}")
                    continue
            return formatted_alerts

    except (KeyError, TypeError) as e:
        app_logger.info(f"Error validating or querying OWA alerts: {e}")
        return []


def calculate_center(geometry):
    """Calculates the center of a GeoJSON geometry."""
    try:
        shape_obj = shape(geometry)  # Check to make sure shape is correct
        if shape_obj.geom_type == 'Polygon':
            centroid = shape_obj.centroid
            return centroid.y, centroid.x  # Returns a tuple of latitude and longitude.
        elif shape_obj.geom_type == 'MultiPolygon':  # Handle the MultiPolygon type too
            centroid = shape_obj.convex_hull.centroid
            return centroid.y, centroid.x
        elif shape_obj.geom_type == 'Point':  # Handle the point type
            return shape_obj.y, shape_obj.x
        elif shape_obj.geom_type == 'LineString':  # Handle the LineString type
            coords = shape_obj.coords
            lats = [coord[1] for coord in coords]
            lons = [coord[0] for coord in coords]
            center_lat = sum(lats) / len(lats)
            center_lon = sum(lons) / len(lons)
            return center_lat, center_lon
        else:
            app_logger.info(f"Invalid GeoJSON type. Type: {shape_obj.geom_type}")
            return None, None
    except Exception as e:
        app_logger.exception(f"Error calculating center: ")
        return None, None


def send_email(recipient_email, subject, body, mail_server, mail_port, mail_username, mail_password):
    try:
        msg = MIMEText(body, 'html')
        msg['Subject'] = subject
        msg['From'] = mail_username
        msg['To'] = recipient_email

        with smtplib.SMTP(mail_server, mail_port) as server:
            server.starttls()
            server.login(mail_username, mail_password)
            server.send_message(msg)
        return True
    except Exception as e:
        app_logger.error(f"Error sending email: {e}")
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

        color = "#898989"  # default value
        map_url = create_map_image_url(center_lat, center_lon, geojson_str, GOOGLE_MAPS_API_KEY, color)

        body = f"""
        <html>
        <head>
            <style>
                @import url('https://fonts.googleapis.com/css2?family=Parkinsans:wght@300..800&display=swap');

                body {{
                    font-family: 'Parkinsans', sans-serif;
                    font-optical-sizing: auto;
                    font-weight: 300;
                    font-style: normal;
                    font-size: 14px;
                    color: #000000;
                    line-height: 1.5;
                }}

                .alert-container {{
                    border: 15px solid {color}; /* Dynamic border color */
                    border-radius: 10px;
                    padding: 15px;
                    margin: 10px;
                    background-color: #FFFFFF;

                }}
                .alert-header {{
                    color: {color}; /* Dynamic header color to match border */
                    font-size: 1.2em;
                    margin-bottom: 10px;
                }}
                .alert-item {{
                    margin-bottom: 5px;
                }}
                .bold {{
                    font-weight: bold;
                }}
            </style>
        </head>
        <body>
            <div class="alert-container">
                <h2 class="alert-header">You have created a new Active Alert Notification Zone:</h2>
                {f'<div class="alert-item"><img src="{map_url}" alt="Map of alert zone"></div>' if map_url else ''}
                <div class="alert-item"><span class="bold">Name:</span> {alert_name if alert_name else "N/A"}</div>
                <div class="alert-item"><span class="bold">Description:</span> {alert_description if alert_description else "N/A"}</div>
                <div class="alert-item"><span class="bold">Creation Time/Date:</span> {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</div>
                <div class="alert-item"><span class="bold">GeoJSON:</span><br> {geojson_str if geojson_str else "N/A"}</div>
                <div class="alert-item"><span class="bold">Center Latitude:</span> {center_lat if center_lat else "N/A"}</div>
                <div class="alert-item"><span class="bold">Center Longitude:</span> {center_lon if center_lon else "N/A"}</div>
            </div>
        </body>
        </html>
        """
        success = send_email(recipient, "Active Alert Notification Zone Created", body, mail_server, mail_port,
                             mail_username, mail_password)

        wag_user_alerts_notification_zone_collection.update_one(
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
            app_logger.info(f"Alert zone creation email sent to  for alert ID: {alert_id}")
        else:
            app_logger.error(f"Failed to send alert zone creation email to {recipient} for alert ID: {alert_id}")

    except Exception as e:
        app_logger.exception(f"Error in send_alert_notification_zone_creation_email: {e}")


def calculate_zoom_level(geometry, image_size=(400, 400)):
    """Calculates an appropriate zoom level for a given geometry."""
    try:
        shape_obj = shape(geometry)
        if shape_obj.geom_type == 'Polygon' or shape_obj.geom_type == 'MultiPolygon':
            minx, miny, maxx, maxy = shape_obj.bounds
        elif shape_obj.geom_type == 'LineString':
            coords = shape_obj.coords
            minx = min([coord[0] for coord in coords])
            miny = min([coord[1] for coord in coords])
            maxx = max([coord[0] for coord in coords])
            maxy = max([coord[1] for coord in coords])

        elif shape_obj.geom_type == 'Point':
            minx, miny, maxx, maxy = shape_obj.x - 0.001, shape_obj.y - 0.001, shape_obj.x + 0.001, shape_obj.y + 0.001

        else:
            return 7
        # Calculate the width and height of the bounding box in degrees
        width = maxx - minx
        height = maxy - miny

        # Get the dimensions of the map image
        image_width, image_height = image_size

        # Calculate the zoom level based on the bounding box and the image dimensions
        zoom_x = math.floor(math.log2(360 * image_width / (256 * width)))
        zoom_y = math.floor(math.log2(180 * image_height / (256 * height)))
        zoom = min(zoom_x, zoom_y)

        # Adjust the zoom to zoom out, ensure it's within a valid range
        adjusted_zoom = max(int(zoom) - 2, 1)  # Zoom out by 2, but don't go below zoom level 1

        return adjusted_zoom

    except Exception as e:
        app_logger.exception(f"Error calculating zoom level: ")
        return 7  # Return a default value


def create_map_image_url(center_lat, center_lon, geojson_str, api_key, color):
    if not center_lat or not center_lon or not geojson_str or not api_key:
        return None

    try:
        geojson_data = json.loads(geojson_str)
        if geojson_data and geojson_data.get("type") == "Polygon":
            coords = geojson_data["coordinates"][0]

            # Convert Hex color to Google Maps API color format (for fill)
            hex_color = color.lstrip('#')  # Remove the #

            # Calculate the alpha value for 25% opacity (0.25 * 255 = 63.75, round to 64)
            alpha_hex = '40'

            # Google Maps expects RRGGBBAA for the fill
            fill_color = f'0x{hex_color}{alpha_hex}'

            # Create the fill path string
            fill_path_str = f"path=color:{fill_color}|fillcolor:{fill_color}"
            for coord in coords:
                fill_path_str += f"|{coord[1]},{coord[0]}"

            # Create the border path string with a 1px solid black border
            border_color = '0x000000ff'  # Solid black
            border_path_str = f"path=color:{border_color}|weight:1"
            for coord in coords:
                border_path_str += f"|{coord[1]},{coord[0]}"

            zoom = calculate_zoom_level(geojson_data)
            map_url = f"https://maps.googleapis.com/maps/api/staticmap?center={center_lat},{center_lon}&zoom={zoom}&size=400x200&maptype=roadmap&{fill_path_str}&{border_path_str}&key={api_key}"
            app_logger.info(f"Map URL generated: {map_url}")
            return map_url

    except Exception as e:
        app_logger.error(f"Error creating map URL: {e}")
    return None


@app.task(name='send_weather_alert')
def send_weather_alert(user_email, owa_alert, wag_alert_id):
    """Sends a weather alert email to a user."""
    try:
        # Fetch alert zone details
        zone = wag_user_alerts_notification_zone_collection.find_one({"_id": ObjectId(wag_alert_id)},
                                                                     {"alert_name": 1, "alert_description": 1})
        alert_name = zone.get('alert_name', 'N/A') if zone else 'N/A'
        alert_description = zone.get('alert_description', 'N/A') if zone else 'N/A'

        # Extract relevant information from the owa_alert.
        msg_type = owa_alert.get('msg_type', 'N/A')
        categories = ", ".join(owa_alert.get('categories', [])) or 'N/A'
        urgency = owa_alert.get('urgency', 'N/A')
        severity = owa_alert.get('severity', 'N/A')
        certainty = owa_alert.get('certainty', 'N/A')
        start_timestamp = owa_alert.get('start', 'N/A')
        end_timestamp = owa_alert.get('end', 'N/A')
        sender = owa_alert.get('sender', 'N/A')
        description_data = owa_alert.get('description', [])
        description_text = ""
        if description_data:
            if isinstance(description_data, list):
                description_text = description_data[0].get('headline', 'N/A')
            else:
                description_text = description_data
        language = owa_alert.get('language', 'N/A')
        event = owa_alert.get('event', 'N/A')
        headline = owa_alert.get('headline', 'N/A')
        instruction = owa_alert.get('instruction', 'N/A')
        color = owa_alert.get('color', '#313131')
        geometry = owa_alert.get('geometry')
        if geometry:
            app_logger.info(f"Geometry found: ")  # Check what the geometry is
            try:
                geojson.loads(json.dumps(geometry))
                app_logger.info("Geometry is valid")
            except Exception as e:
                app_logger.info(f"Error validating geometry: {e}")
        else:
            app_logger.info("No geometry found")

        # Generate Map URL
        map_url = None
        if geometry:
            center_lat, center_lon = calculate_center(geometry)
            map_url = create_map_image_url(center_lat, center_lon, json.dumps(geometry), GOOGLE_MAPS_API_KEY, color)

        # Construct the email body with the extracted content.
        subject = "Weather Alert!"
        body = f"""
            <html>
            <head>
                <style>
                    @import url('https://fonts.googleapis.com/css2?family=Parkinsans:wght@300..800&display=swap');

                    body {{
                        font-family: 'Parkinsans', sans-serif;
                        font-optical-sizing: auto;
                        font-weight: 300;
                        font-style: normal;
                        font-size: 14px;
                        color: #000000;
                        line-height: 1.5;
                    }}

                    .alert-container {{
                        border: 15px solid {color}; /* Dynamic border color */
                        border-radius: 10px;
                        padding: 15px;
                        margin: 10px;
                        background-color: #FFFFFF;

                    }}
                    .alert-header {{
                        color: {color}; /* Dynamic header color to match border */
                        font-size: 1.2em;
                        margin-bottom: 10px;
                    }}
                    .alert-item {{
                        margin-bottom: 5px;
                    }}
                    .bold {{
                        font-weight: bold;
                    }}
                </style>
            </head>
            <body>
                    <div class="alert-container">
                        <h2 class="alert-header">A weather alert has been issued affecting your zone:</h2>
                        <div class="alert-item"><span class="bold"><b>Alert Zone Name:</b></span> {alert_name}</div>
                        <div class="alert-item"><span class="bold"><b>Alert Zone Description:</b></span> {alert_description}</div>
                        <h2 class="alert-header">{headline if headline else "N/A"}</h2>
                        {f'<div class="alert-item"><img src="{map_url}" alt="Map of OWA Alert"></div>' if map_url else ''}
                        <div class="alert-item"><span class="bold"><b>Message Type:</b></span> {msg_type if msg_type else "N/A"}</div>
                        <div class="alert-item"><span class="bold"><b>Categories:</b></span> {categories if categories else "N/A"}</div>
                        <div class="alert-item"><span class="bold"><b>Urgency:</b></span> {urgency if urgency else "N/A"}</div>
                        <div class="alert-item"><span class="bold"><b>Severity:</b></span> {severity if severity else "N/A"}</div>
                        <div class="alert-item"><span class="bold"><b>Certainty:</b></span> {certainty if certainty else "N/A"}</div>
                        <div class="alert-item"><span class="bold"><b>Start Time:</b></span> {datetime.fromtimestamp(start_timestamp).strftime('%Y-%m-%d %H:%M:%S UTC') if start_timestamp != 'N/A' else 'N/A'}</div>
                        <div class="alert-item"><span class="bold"><b>End Time:</b></span> {datetime.fromtimestamp(end_timestamp).strftime('%Y-%m-%d %H:%M:%S UTC') if end_timestamp != 'N/A' else 'N/A'}</div>
                        <div class="alert-item"><span class="bold"><b>Sender:</b></span> {sender if sender else "N/A"}</div>
                        <div class="alert-item"><span class="bold"><b>Description:</b></span><br></div>
                        <div class="alert-item"><span class="bold"><b>Language:</b></span><br> {language if language else "N/A"}</div>
                        <div class="alert-item"><span class="bold"><b>Event:</b></span><br> {event if event else "N/A"}</div>
                        <div class="alert-item"><span class="bold"><b>Headline:</b></span><br> {headline if headline else "N/A"}</div>
                        <div class="alert-item"><span class="bold"><b>Instruction:</b></span><br> {instruction if instruction else "N/A"}</div>
                    </div>
            </body>
            </html>
            """
        send_weather_alert_email.delay(user_email, subject, body, MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD)


    except Exception as e:
        app_logger.error(f"Error in send_weather_alert: {e}")


@app.task(name='check_for_and_send_alerts')
def check_for_and_send_alerts():
    """Checks for new OWA alerts and sends emails to affected users."""
    app_logger.info("check_for_and_send_alerts task is running")  # Added this log

    try:
        app_logger.info("Starting check_for_and_send_alerts process")

        users = wag_user_alerts_notification_zone_collection.find({},
                                                                  {"_id": 1, "user_id": 1, "email": 1, "geometry": 1,
                                                                   "notifications": 1,
                                                                   "email_alerts_enabled": 1, "owa_alerts": 1}).limit(
            100)
        users_list = list(users)
        app_logger.info(f"Number of users found: {len(users_list)}")

        if not users_list:
            app_logger.info("User list is empty - Exiting")
            return  # Exit if user list is empty

        for user in users_list:
            user_id = user["_id"]
            user_email = user["email"]
            wag_zone_geometry = user.get("geometry", None)
            app_logger.info(
                f"Processing user: {user_id}, User ID: {user.get('user_id', 'N/A')}, Geometry: {wag_zone_geometry}")
            app_logger.info(f"USER: {user}")

            if user.get('email_alerts_enabled', False) == True:
                app_logger.info(f"Email alerts enabled for user: ")
                if wag_zone_geometry:
                    app_logger.info(f"Finding matching alerts for user: ")
                    # Convert _id to string
                    user_id_str = str(user["_id"])
                    # Extract only serializable data
                    serializable_user = {
                        "_id": user_id_str,
                        "user_id": user.get("user_id", None),
                        "email": user.get("email", None),
                        "notifications": user.get("notifications", None),
                        "email_alerts_enabled": user.get("email_alerts_enabled", None),
                        "owa_alerts": user.get("owa_alerts", []),
                    }
                    find_matching_owa_alerts.apply_async(
                        args=[wag_zone_geometry, 14],
                        link=process_matching_alerts.s(serializable_user, user_email)
                    )


                else:
                    app_logger.info(f"User:  has no valid geometry defined")
            else:
                app_logger.info(f"Email alerts are disabled for user:  - Skipping")
        app_logger.info("Completed check_for_and_send_alerts process")
    except Exception as e:  # Colon added here
        app_logger.exception("Error in check_for_and_send_alerts:")


@app.task(name='process_matching_alerts')
def process_matching_alerts(matching_alerts, user, user_email):
    """Processes matching OWA alerts for a user and sends notifications."""
    app_logger.info(f"Starting process_matching_alerts for user: {user.get('user_id', 'N/A')}")

    try:
        # Ensure owa_alerts exists, create it if it does not

        # Get existing alerts
        sent_alert_ids = [alert.get("id") for alert in user.get("owa_alerts", [])]

        #  check if matching_alerts is None. If so, assign an empty list instead.
        if matching_alerts is None:
            matching_alerts = []
        new_alerts = [alert for alert in matching_alerts if alert["id"] not in sent_alert_ids]

        num_alerts = len(new_alerts)
        app_logger.info(f"Number of matching alerts for user: : {num_alerts}")
        if num_alerts > 0:
            # Log a sample of the alerts, not all of them
            sample_alerts = new_alerts[:min(num_alerts, 5)]  # Limit to 5 for logging
            app_logger.info(f"Sample of matching alerts for user: : {sample_alerts}")
            for owa_alert in new_alerts:
                app_logger.info(
                    f"Sending alert for User: {user.get('user_id', 'N/A')}, Alert ID: {owa_alert['id']}, OWA Alert: {owa_alert}")
                send_weather_alert.delay(user_email, owa_alert, user["_id"])  # Delay the task.

                # Add the owa_alert to the database
                wag_user_alerts_notification_zone_collection.update_one(
                    {"_id": ObjectId(user["_id"])},
                    {
                        "$push": {
                            "owa_alerts": {
                                "id": owa_alert["id"],
                                "sent": True,
                                "timestamp": datetime.now(tz=timezone.utc)
                            }
                        }
                    }
                )
        else:
            app_logger.info(f"No matching alerts found for user: {user.get('user_id', 'N/A')}")

    except Exception as e:
        app_logger.exception(
            f"Error in process_matching_alerts task: {e} - for user: {user.get('user_id', 'N/A')}")

    except Exception as e:
        app_logger.exception(
            f"Error in process_matching_alerts task: {e} - for user: {user.get('user_id', 'N/A')}")


@app.task(name='send_weather_alert_email')
def send_weather_alert_email(user_email, subject, body, MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD):
    """Sends a weather alert email to a user."""
    try:
        # Extract the wag_alert_id from the body
        wag_alert_id = body.split("Wag Alert ID: ")[1].strip() if "Wag Alert ID: " in body else None

        # Construct the email
        msg = MIMEText(body, 'html')
        msg['Subject'] = subject
        msg['From'] = MAIL_USERNAME
        msg['To'] = user_email

        # Send the email
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.send_message(msg)

        # Update the database
        if wag_alert_id:
            wag_user_alerts_notification_zone_collection.update_one(
                {"_id": ObjectId(wag_alert_id)},
                {"$push": {
                    "notifications": {"type": "weather_alert", "timestamp": datetime.now(timezone.utc), "sent": True}}}
            )

    except smtplib.SMTPException as e:
        app_logger.error(f"SMTP error sending weather alert email to : {e}")
    except pymongo.errors.PyMongoError as e:
        app_logger.error(f"Database error updating notification status: {e}")
    except Exception as e:
        app_logger.exception(f"Unexpected error sending weather alert email to : {e}")
