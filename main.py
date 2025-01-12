# main.py with Websockets
# Patch gevent *before* Flask and SocketIO
from gevent import monkey
monkey.patch_all()
import geventwebsocket
import gevent
import certifi
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from pymongo import MongoClient, errors as pymongo_errors
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv
from bson import ObjectId
import atexit
from threading import Thread
import json
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone, timedelta
import re
from flask_mail import Mail, Message
import secrets
import smtplib
from itsdangerous import URLSafeTimedSerializer
import requests
import pymongo
import threading
import logging.handlers
import geojson
from celery.result import AsyncResult
import redis
from redis.exceptions import ConnectionError
from celery import Celery
from flask_socketio import SocketIO, emit, send
import logging
import asyncio
import aiohttp
import flask_socketio
from flask_socketio import join_room

load_dotenv()

app = Flask(__name__)
mail = Mail(app)
app.secret_key = os.environ.get('SECRET_KEY')
s = URLSafeTimedSerializer(os.environ.get('SERIALIZER_SECRET'))

# Initialize SocketIO
print('Request from: ', os.environ.get('CORS_ALLOWED_ORIGINS')) # test call.
cors_origins = os.environ.get('CORS_ALLOWED_ORIGINS')
if cors_origins == '*':
    socketio = SocketIO(app, cors_allowed_origins='*', max_http_buffer_size=1024*1024)
else:
    socketio = SocketIO(app, cors_allowed_origins=cors_origins, max_http_buffer_size=1024*1024)

# Create a logger for the Flask app
APP_LOGGER_NAME = 'main-weather-alerts-global'
app_logger = logging.getLogger(APP_LOGGER_NAME)
app_logger.setLevel(logging.INFO)

# Create a formatter for both file and stream handlers
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s - %(lineno)d - %(message)s')

# Check if running locally, if not, log to stdout only.
if os.environ.get('ENVIRONMENT') != 'PRODUCTION':

    # Truncate the log file at the start
    log_file_path = 'main-weather-alerts-global.log'
    with open(log_file_path, 'w'):
        pass #This line erases the file

    # Create a file handler for local development
    file_handler = logging.handlers.RotatingFileHandler(log_file_path, maxBytes=10 * 1024 * 1024, backupCount=5)
    file_handler.setFormatter(formatter)
    app_logger.addHandler(file_handler)

# Create a stream handler for app logs (to stdout for both local/GCP)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
app_logger.addHandler(stream_handler)

# Log that the app is started
app_logger.info(f"Flask application logger created, logging started for {APP_LOGGER_NAME}")

# Email Configuration (Use environment variables for security!)
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER')

# Initialize Flask-Mail
mail = Mail(app)

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


def create_index(collection, field_name, index_type=pymongo.ASCENDING):
    """Creates an index on the specified field. Handles potential errors."""
    try:
        index_name = f"_"
        result = collection.create_index([(field_name, index_type)], name=index_name)
        app_logger.info(f"Index '{index_name}' created successfully on collection '{collection.name}'.")
        return result
    except pymongo.errors.OperationFailure as e:
        if "already exists" in str(e):
            app_logger.info(f"Index '{index_name}' already exists on collection '{collection.name}'.")
        else:
            app_logger.info(f"Error creating index '{index_name}' on collection '{collection.name}': ")
            # Consider logging this error
        return None
    except Exception as e:
        app_logger.info(f"An unexpected error occurred while creating index on collection '{collection.name}': ")
        # Log this error
        return None


def create_geospatial_index(collection, field_name):
    """Creates a 2dsphere index on the specified field. Handles potential errors."""
    try:
        index_name = f"{field_name}_2dsphere" # Create a name for the index based on the field name
        result = collection.create_index([(field_name, pymongo.GEOSPHERE)], name=index_name)
        app_logger.info(f"Index '{index_name}' created successfully on collection '{collection.name}'.")
        return result
    except pymongo.errors.OperationFailure as e:
        if "already exists" in str(e):
            app_logger.info(f"Index '{index_name}' already exists on collection '{collection.name}'.")
        else:
            app_logger.info(f"Error creating index '{index_name}' on collection '{collection.name}': ")
            # Consider logging this error
        return None
    except Exception as e:
        app_logger.info(f"An unexpected error occurred while creating index '{index_name}' on collection '{collection.name}': ")
        # Log this error
        return None


# Create indexes
create_geospatial_index(owa_collection, "geometry")
create_geospatial_index(wag_user_alerts_notification_zone_collection, "geometry")
create_index(owa_collection, "start")
create_index(owa_collection, "end")

# Verify indexes (optional but recommended)
app_logger.info("\nIndex information for owa_collection:")
app_logger.info(owa_collection.index_information())
app_logger.info("\nIndex information for wag_user_alerts_notification_zone_collection:")
app_logger.info(wag_user_alerts_notification_zone_collection.index_information())

allowed_domains_str = os.getenv('ALLOWED_DOMAINS')
app_logger.info(f"Environment variable ALLOWED_DOMAINS: {allowed_domains_str}") # Added debugging line

ALLOWED_DOMAINS = set()
for i in range(1, 100):  # Adjust 100 to a sufficiently large number
    domain = os.getenv(f'ALLOWED_DOMAINS_{i}')
    if domain:
        ALLOWED_DOMAINS.add(domain.strip().lower())
    else:
        break  # Stop when no more domains are found

if not ALLOWED_DOMAINS:
    ALLOWED_DOMAINS = {"example.com"}  # Default
    logging.warning("Environment variable ALLOWED_DOMAINS not set. Using default domains.")

app_logger.info(f"ALLOWED_DOMAINS set: {ALLOWED_DOMAINS}") # Added debugging line

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Redis configuration (already in your tasks.py, but we need it here too)
redis_cloud_host = os.environ.get('REDIS_CLOUD_HOST')
redis_cloud_port = os.environ.get('REDIS_CLOUD_PORT')
redis_cloud_password = os.environ.get('REDIS_CLOUD_PASSWORD')
redis_cloud_db = os.environ.get('REDIS_CLOUD_DB', 0)

try:
    redis_cloud_db = int(redis_cloud_db)
except ValueError:
    raise ValueError("redis_cloud_db must be an integer.")

redis_client = redis.Redis(host=redis_cloud_host, port=redis_cloud_port, password=redis_cloud_password,
                           db=redis_cloud_db)

# Celery configuration
celery_app = Celery('tasks',
             broker=f'redis://:{redis_cloud_password}@{redis_cloud_host}:{redis_cloud_port}/{redis_cloud_db}',
             backend=f'redis://:{redis_cloud_password}@{redis_cloud_host}:{redis_cloud_port}/{redis_cloud_db}')

app_logger.info(f"Broker URL: {celery_app.conf.broker_url}")
app_logger.info(f"Backend URL: {celery_app.conf.result_backend}")


def generate_verification_token():
    return secrets.token_urlsafe(32)


class User(UserMixin):
    def __init__(self, user_id, email, password, first_name, last_name, verified=False):
        self.id = user_id
        self.email = email
        self.password = password
        self.first_name = first_name
        self.last_name = last_name
        self.verified = verified

    def get_id(self):
        return self.id

    @staticmethod
    def get(user_id):
        try:
            user_data = wag_collection.find_one({"_id": ObjectId(user_id)},
                                                {"_id": 1, "email": 1, "password": 1, "first_name": 1, "last_name": 1,
                                                 "verified": 1})
            if user_data:
                user = User(str(user_data["_id"]), user_data["email"], user_data["password"],
                            user_data["first_name"], user_data["last_name"], user_data["verified"])
                return user
            return None
        except pymongo_errors.PyMongoError as e:
            app_logger.error(f"Database error fetching user: ")
            return None
        except Exception as e:
            app_logger.exception(f"Unexpected error fetching user: ")
            return None


@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        app_logger.info(f"Login attempt: email=")

        try:
            user_data = wag_collection.find_one({"email": email})
            if user_data and check_password_hash(user_data["password"], password) and user_data["verified"]:
                user = User(str(user_data["_id"]), user_data["email"], user_data["password"],
                            user_data["first_name"], user_data["last_name"], user_data["verified"])
                login_user(user, remember=True)
                app_logger.info(f"Login successful: {user.email}")
                return redirect(url_for('index'))
            elif user_data and check_password_hash(user_data["password"], password) and not user_data["verified"]:
                flash("Please verify your email address before logging in.")
            else:
                flash("Invalid email or password")
                app_logger.warning("Invalid login credentials.")
        except pymongo_errors.PyMongoError as e:
            app_logger.error(f"Database error during login: ")
            flash("Database error")
        except Exception as e:
            app_logger.exception(f"Unexpected error during login: ")
            flash("An unexpected error occurred")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html", allowed_domains=ALLOWED_DOMAINS, error_message=None)

    email = request.form.get("email")
    password = request.form.get("password")
    first_name = request.form.get("first_name")
    last_name = request.form.get("last_name")
    hashed_password = generate_password_hash(password)

    error = None  # Define error variable
    error_message = None  # Better variable name for displaying to the user
    if not is_valid_email(email):
        error_message = "Please enter a valid email address."
        error = True  # Set error if validation fails
    elif email.split('@')[-1].lower() not in ALLOWED_DOMAINS:
        error_message = f"Registration is restricted to users from {', '.join(ALLOWED_DOMAINS)}."
        error = True  # Set error if domain is invalid

    if error:  # Now error is defined
        return render_template("register.html", allowed_domains=ALLOWED_DOMAINS, error_message=error_message,
                               email=email, first_name=first_name, last_name=last_name)

    app_logger.info(f"ALLOWED_DOMAINS in register function: ")  # Added debugging line

    if error:
        return render_template("register.html", error=error, email=email, first_name=first_name, last_name=last_name,
                               allowed_domains=ALLOWED_DOMAINS)

    try:
        user_data = wag_collection.find_one({"email": email})
        if user_data:
            flash("Email already exists")
            return render_template("register.html", email=email, first_name=first_name, last_name=last_name,
                                   allowed_domains=ALLOWED_DOMAINS)
        else:
            token = generate_verification_token()
            wag_collection.insert_one({
                "email": email,
                "password": hashed_password,
                "first_name": first_name,
                "last_name": last_name,
                "verified": False,
                "verification_token": token
            })
            if send_verification_email(email, token):
                flash("Registration successful. Please check your email to verify your account.")
            else:
                flash("Error sending verification email. Please try again or contact support.")
            return redirect(url_for("login"))
    except pymongo_errors.PyMongoError as e:
        app_logger.error(f"Database error during registration: ")
        flash("Database error")
        return render_template("register.html", email=email, first_name=first_name, last_name=last_name,
                               allowed_domains=ALLOWED_DOMAINS)
    except Exception as e:
        app_logger.exception(f"Unexpected error during registration: ")
        flash("An unexpected error occurred")
        return render_template("register.html", email=email, first_name=first_name, last_name=last_name,
                               allowed_domains=ALLOWED_DOMAINS)


def send_verification_email(email, token):
    verification_url = url_for('verify_email', token=token, _external=True)
    msg = Message('Confirm Your Email', sender=app.config['MAIL_DEFAULT_SENDER'], recipients=[email])
    msg.body = f"""Thank you for registering!
    Please click the link below to verify your email address:

    {verification_url}

    If you did not request this, please ignore this email.
    """
    try:
        mail.send(msg)
        return True
    except smtplib.SMTPException as e:
        logging.error(f"SMTP error sending verification email: {e}")
        return False
    except Exception as e:
        logging.exception(f"Unexpected error sending verification email: {e}")
        return False


@app.route("/verify/<token>")
def verify_email(token):
    user = wag_collection.find_one({"verification_token": token})
    if user:
        wag_collection.update_one({"_id": user["_id"]}, {"$set": {"verified": True, "verification_token": None}})
        flash("Email verified successfully!")
        return redirect(url_for("login"))
    else:
        flash("Invalid verification token.")
        return redirect(url_for("login"))


def is_valid_email(email):
    email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(email_regex, email) is not None


def send_password_reset_email(email, token):
    reset_url = url_for('reset', token=token, _external=True)
    msg = Message('Reset Your Password', sender=app.config['MAIL_DEFAULT_SENDER'], recipients=[email])
    msg.body = f"""Hello,

    You have requested a password reset. Please click the link below to reset your password:

    {reset_url}

    If you did not request this, please ignore this email.
    """
    try:
        mail.send(msg)
        return True
    except smtplib.SMTPException as e:
        logging.error(f"SMTP error sending password reset email: {e}")
        return False
    except Exception as e:
        logging.exception(f"Unexpected error sending password reset email: {e}")
        return False


@app.route('/forgot', methods=['GET', 'POST'])
def forgot():
    if request.method == 'POST':
        email = request.form['email']
        # Ensure the email exists in your database here.

        token = s.dumps(email, salt='email-confirm')

        # Send the email with the token here.
        send_password_reset_email(email, token)

        flash('An email has been sent with instructions to reset your password.', 'success')
        return redirect(url_for('login'))

    return render_template('forgot.html')


@app.route('/reset/<token>', methods=['GET', 'POST'])
def reset(token):
    try:
        email = s.loads(token, salt='email-confirm', max_age=3600)
    except SignatureExpired:
        flash('The password reset link is invalid or expired.', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        password = request.form['password']
        hashed_password = generate_password_hash(password)  # Hash the password

        # Update the password in the database here.
        wag_collection.update_one({"email": email}, {"$set": {"password": hashed_password}})

        flash('Your password has been updated!', 'success')
        return redirect(url_for('login'))

        # if a GET request was made, return the reset form
    return render_template('reset_with_token.html', token=token)


@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old_password = request.form['old_password']
        new_password = request.form['new_password']
        confirm_new_password = request.form['confirm_new_password']

        user_data = wag_collection.find_one({"_id": ObjectId(current_user.id)})
        if not user_data:
            flash("User not found")
            return redirect(url_for('index'))

        if not check_password_hash(user_data['password'], old_password):
            flash("Incorrect old password.")
            return redirect(url_for('change_password'))

        if new_password != confirm_new_password:
            flash("New passwords do not match.")
            return redirect(url_for('change_password'))

        # Add password strength validation here if needed (e.g., using a library like `password-strength`)

        hashed_new_password = generate_password_hash(new_password)
        wag_collection.update_one({"_id": ObjectId(current_user.id)}, {"$set": {"password": hashed_new_password}})
        flash("Password changed successfully!")
        return redirect(url_for('index'))

    return render_template('change_password.html')


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/")
def index():
    app_logger.info(
        f"Index page accessed by user: {current_user.email if current_user.is_authenticated else 'Anonymous User'}")
    if current_user.is_authenticated:
        map_data = {'map_js': "", 'alerts': []}  # Initialize map_data here.  Important!
        loading = False
        task_id = None

        try:
            app_logger.info("Attempting to retrieve map_data from Redis...")
            map_data_json = redis_client.get('map_data')
            cached_task_id = redis_client.get('map_data_task_id')  # Returns None if not found

            if map_data_json:
                try:
                    map_data = json.loads(map_data_json)
                    app_logger.info("Retrieved map_data from Redis.")
                    loading = False
                except json.JSONDecodeError:
                    app_logger.error("Error decoding map_data from redis in / route")
                    loading = True
                if map_data and map_data.get('alerts'):
                    app_logger.info(f"Number of alerts found in map data: {len(map_data['alerts'])}")
                else:
                    app_logger.info(f"No alerts found in map data")
            elif cached_task_id:
                app_logger.info("Task ID found in Redis, checking if running...")
                async_result = AsyncResult(cached_task_id.decode('utf-8'), app=celery_app)
                if async_result.state in ['PENDING', 'STARTED', 'RETRY']:
                    app_logger.info("Map Data task is running, setting loading screen")
                    loading = True
                elif async_result.state == 'SUCCESS':
                    map_data_json = redis_client.get('map_data')
                    if map_data_json:
                        map_data = json.loads(map_data_json)
                        app_logger.info("Retrieved map_data from Redis after successful task completion")
                        loading = False
                    else:
                        app_logger.info("Redis data not found after a successful task.")
                        redis_client.set('map_data_task_id', task.id)
                        app_logger.info(f"Triggered map data generation, task id: {task.id}")
                        loading = True
                elif async_result.state == 'FAILURE':
                    app_logger.error(f"Previous task failed with traceback: {async_result.traceback}")
                    flash("Error generating map data. Please try again later.")
                    loading = False  # Ensure loading is false
                    # Optionally trigger a new task here
                    task = celery_app.send_task('populate_map_data_if_needed')
                    redis_client.set('map_data_task_id', task.id)
                    app_logger.info(f"Triggered new map data generation, task id: {task.id}")
                else:
                    app_logger.warning(
                        f"Previous task in unknown state: {async_result.state}")  # Handle task failure (e.g., retry or display an error)
                    flash("Error generating map data. Please try again later.")
                    loading = False  # Ensure loading is false
            else:
                app_logger.info("Map data not found in Redis. Generating...")
                loading = True
                task = celery_app.send_task('populate_map_data_if_needed')
                redis_client.set('map_data_task_id', task.id)
                app_logger.info(f"Starting map data generation task id: {task.id}")

        except ConnectionError as e:
            app_logger.error(f"Redis connection error: ")
            flash("A temporary error occurred. Please try again later.")  # More user-friendly message
            return render_template('error.html')  # Handle Redis connection errors appropriately
        except Exception as e:
            app_logger.exception("Unhandled error in index route:")
            flash("An unexpected error occurred.")
            return render_template('error.html')

        # Handle the response - this section is now ALWAYS executed
        alerts = map_data.get('alerts', [])
        map_js = map_data.get('map_js', '')

        app_logger.info(f"Number of alerts sent to template: {len(alerts)}")

        active_alerts_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        current_date = datetime.now().strftime('%Y-%m-%d')
        alert_count, date_range = get_alert_stats(alerts)
        alert_counts = {}
        app_logger.info(f"Alerts found for index route: {alert_count}, Date Range: {date_range}")
        for alert in alerts:
            severity = alert.get('severity', 'Unknown')  # Handle potential missing keys
            alert_counts[severity] = alert_counts.get(severity, 0) + 1

        # app_logger.info(f"Alerts sent to template: ")  # Debugging
        return render_template('index.html', map_js=map_js, alerts=alerts,
                               active_alerts_time=active_alerts_time, current_date=current_date,
                               alert_count=alert_count, date_range=date_range,
                               alert_counts=alert_counts, loading=loading, task_id=task_id)
    else:  # If not authenticated
        return redirect(url_for('login'))


def get_alert_stats(alerts):
    if alerts:
        earliest_start = min(alert['start'] for alert in alerts)
        latest_start = max(alert['start'] for alert in alerts)
        earliest_date = datetime.fromtimestamp(earliest_start, tz=timezone.utc).strftime('%Y-%m-%d')
        latest_date = datetime.fromtimestamp(latest_start, tz=timezone.utc).strftime('%Y-%m-%d')
        date_range = f"{earliest_date} - {latest_date}"
        return len(alerts), date_range
        app_logger.info(f"Alerts found: {len(alerts)}, Date Range: {date_range}")
    else:
        app_logger.info(f"No alerts found")  # Added this log
        return 0, "No alerts currently displayed"


def translate_text(text, target_language='en'):
    translate_url = 'https://translation.googleapis.com/language/translate/v2'

    headers = {'Content-Type': 'application/json'}

    key = os.getenv('GOOGLE_TRANSLATE_API_KEY')  # Replace with your own API key
    payload = {"q": text, "target": target_language}

    response = requests.post(translate_url, headers=headers, params={'key': key}, data=json.dumps(payload))

    if response.status_code == 200:
        return response.json()['data']['translations'][0]['translatedText']
    else:
        return f"Error: {response.status_code}"

@app.route('/translate', methods=['GET'])
def translate():
    text = request.args.get('text')
    target_language = 'en'  # or whatever language you want
    translated_text = translate_text(text, target_language)
    return {'translated_text': translated_text}


@app.route('/create_alert_zone', methods=['POST'])
@login_required
def create_alert_zone():
    try:
        data = request.get_json()
        geojson_data = data.get('geojson')
        if not geojson_data:
            return jsonify({"error": "Missing 'geojson' key"}), 400

        try:
            geojson.loads(json.dumps(geojson_data))
            feature = geojson_data.get('features')[0]
            geometry = feature.get('geometry')
            if geometry is None:
                return jsonify({"error": "Invalid GeoJSON: Missing 'geometry'"}), 400
            if geometry['type'] not in ['Polygon', 'Point', 'MultiPolygon', 'LineString']:
                return jsonify({'error': f"Invalid geometry type: {geometry['type']}"}), 400

            # Validate coordinates are within bounds
            for coord_set in geometry['coordinates']:
                for coord_pair in coord_set:
                    longitude = coord_pair[0]
                    latitude = coord_pair[1]
                    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
                        raise ValueError(f"Longitude/latitude out of bounds: lng= lat=")

        except geojson.errors.GeoJSONError as e:
            return jsonify({"error": f"Invalid GeoJSON: {str(e)}"}), 400
        except (KeyError, IndexError, ValueError) as e:
            return jsonify({"error": f"Invalid GeoJSON structure or coordinates out of bounds: {str(e)}"}), 400

        alert_description = data.get('alert_description', "No description provided")
        alert_description = alert_description.replace("<", "&lt;").replace(">", "&gt;")
        alert_name = data.get('alert_name', "Unnamed Alert")
        alert_name = alert_name.replace("<", "&lt;").replace(">", "&gt;")

        alert_data = {
            "user_id": current_user.id,
            "geometry": geometry,
            "alert_creation_time": datetime.now(tz=timezone.utc),
            "alert_description": alert_description,
            "email": current_user.email,
            "alert_name": alert_name,
            "notification_types": ["alert_zone_creation", "weather_alert"],  # Array of types
            "notifications": []  # Initialize notifications array
        }

        result = wag_user_alerts_notification_zone_collection.insert_one(alert_data)
        alert_id = str(result.inserted_id)

        # Send ONLY the necessary email data to the Celery task:
        email_data = {
            'recipient': current_user.email,
            'alert_id': alert_id,
            'alert_name': alert_name,
            'alert_description': alert_description,
            'geojson_str': json.dumps(geometry),
            'center_lat': calculate_center(geometry)[0],
            'center_lon': calculate_center(geometry)[1],
        }

        task = celery_app.send_task('send_alert_notification_zone_creation_email', args=[email_data,
                                                                                         app.config['MAIL_SERVER'],
                                                                                         app.config['MAIL_PORT'],
                                                                                         app.config['MAIL_USERNAME'],
                                                                                         app.config['MAIL_PASSWORD']])
        return jsonify({"message": "Alert created successfully", "task_id": task.id, "alert_id": alert_id}), 202

    except Exception as e:
        app_logger.exception("Error in create_alert_zone:")
        return jsonify({"error": f"Error creating alert: {str(e)}"}), 500


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


@app.route('/delete_alert_zone/<alert_id>', methods=['DELETE'])
@login_required  # Assuming you have login_required decorator
def delete_alert_zone(alert_id):
    try:
        alert_id_object = ObjectId(alert_id)
        result = wag_user_alerts_notification_zone_collection.delete_one(
            {"_id": alert_id_object, "user_id": current_user.id})

        if result.deleted_count == 1:
            return jsonify({"message": "Alert zone deleted successfully"}), 200
        else:
            return jsonify({"error": "Alert zone not found or you don't have permission to delete it"}), 404
    except pymongo_errors.PyMongoError as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Error deleting alert zone: {str(e)}"}), 500


@app.route('/delete_all_alert_zones', methods=['DELETE'])
@login_required
def delete_all_alert_zones():
    try:
        result = wag_user_alerts_notification_zone_collection.delete_many({"user_id": current_user.id})
        if result.deleted_count > 0:
            return jsonify({"message": f"Deleted {result.deleted_count} alert zones successfully."}), 200
        else:
            return jsonify({"message": "No alert zones found for this user."}), 200  # No error, just a message
    except pymongo_errors.PyMongoError as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Error deleting alert zones: {str(e)}"}), 500


@app.route('/get_user_alerts', methods=['GET'])
@login_required
def get_user_alerts():
    """Returns user's saved alert zones."""
    try:
        user_alerts = wag_user_alerts_notification_zone_collection.find({"user_id": current_user.id})
        alerts_data = []
        for alert in user_alerts:
            alert['_id'] = str(alert['_id'])
            alerts_data.append(alert)
        app_logger.info(f"Returning {len(alerts_data)} alerts for user {current_user.id}: ")  # More detailed logging
        return jsonify({'alerts': alerts_data})

        return jsonify({'alerts': alerts_data})
    except pymongo_errors.PyMongoError as e:
        app_logger.exception(f"PyMongo database error in get_user_alerts: ")
        return jsonify({"error": "Database error"}), 500
    except Exception as e:
        app_logger.exception(f"Unexpected error in get_user_alerts: ")
        return jsonify({"error": "Server error"}), 500


@app.route('/get_alerts_for_zone', methods=['GET'])
@login_required
def get_alerts_for_zone():
    """Returns OWA alerts intersecting with a specified GeoJSON geometry."""
    try:
        geometry_str = request.args.get('geometry')
        app_logger.info(f"get_alerts_for_zone called with geometry: ")
        if not geometry_str:
            return jsonify({"error": "Missing geometry parameter"}), 400
        try:
            geometry = json.loads(geometry_str)
            geojson.loads(json.dumps(geometry))  # Verify valid geometry
            if geometry['type'] not in ['Polygon', 'MultiPolygon', 'Point', 'LineString']:
                return jsonify({'error': f"Invalid geometry type: {geometry['type']}"}), 400
        except (json.JSONDecodeError, geojson.errors.GeoJSONError, KeyError) as e:
            app_logger.info("Error parsing geometry")
            return jsonify({"error": f"Invalid geometry data: {str(e)}"}), 400
        # Generate a unique cache key based on the geometry
        cache_key = f"alerts_for_zone_{hash(geometry_str)}"  # Hash the string to ensure a valid key.
        # Try to fetch from the cache
        cached_data = redis_client.get(cache_key)
        if cached_data:
            app_logger.info(f"Retrieved alert data from Redis with key: ")
            return jsonify({"alerts": json.loads(cached_data)})

        # If no cached data, fetch from MongoDB
        task = celery_app.send_task('find_matching_owa_alerts_task', args=[geometry])
        matching_alerts = task.get()

        alerts_data = []
        for alert in matching_alerts:
            alerts_data.append(alert)

        # Cache data before sending to the user.
        redis_client.setex(cache_key, 7200, json.dumps(alerts_data))  # Store for 2 hours
        app_logger.info(f"Returning {len(alerts_data)} alerts and saving with key: ")
        return jsonify({"alerts": alerts_data})
    except Exception as e:
        app_logger.exception("Error in get_alerts_for_zone: ")
        return jsonify({"error": "Error fetching alerts for zone"}), 500


@socketio.on('map_data')
def handle_map_data():
    """ Emits the map data to a specific client """
    app_logger.info(f'Initial map data requested via SocketIO')
    # Emit the loading signal for the frontend to know data fetching has started.
    flask_socketio.emit('loading', {'loading': True}, room=request.sid)  # Start loading
    app_logger.info(f"loading event emitted to room: {request.sid}")


    try:
            app_logger.info("Attempting to retrieve map_data from Redis...")
            map_data_json = redis_client.get('map_data')
            cached_task_id = redis_client.get('map_data_task_id')  # Returns None if not found

            if map_data_json:
                try:
                    map_data = json.loads(map_data_json)
                    cache_timestamp = None  # Initialize cache_timestamp here
                    if isinstance(map_data,
                                  dict) and 'map_data' in map_data:  # Check for map_data, and that its a dict.
                        cache_timestamp = map_data.get('cache_timestamp')  # Retrieve the timestamp from the cache
                        app_logger.info(f"Retrieved map_data from Redis with a cache timestamp of {cache_timestamp}.")
                        socketio.emit('map_data_update', {'map_data': map_data, 'cache_timestamp': cache_timestamp})
                        flask_socketio.emit('loading', {'loading': False}, room=request.sid)
                        app_logger.info(f"loading event emitted to room: {request.sid}")

                    else:
                        cache_timestamp = map_data.get('cache_timestamp')  # Retrieve the timestamp from the cache
                        app_logger.info(
                            f"Retrieved old style map_data from with a cache timestamp of {cache_timestamp}.")
                        socketio.emit('map_data_update', {'map_data': map_data, 'cache_timestamp': cache_timestamp})
                        flask_socketio.emit('loading', {'loading': False}, room=request.sid)
                        app_logger.info(f"loading event emitted to room: {request.sid}")

                except json.JSONDecodeError:
                    cache_timestamp = None  # Initialize cache_timestamp here
                    # Attempt to get the cache timestamp from the old style object.
                    try:
                        map_data = json.loads(map_data_json)
                        cache_timestamp = map_data.get('cache_timestamp')
                    except:
                        pass  # If we can't decode, the value stays at None.
                    app_logger.info(
                        f"Retrieved non JSON map_data from Redis  with a cache timestamp of {cache_timestamp}.")
                    socketio.emit('map_data_update', {'map_data': map_data_json, 'cache_timestamp': cache_timestamp})

            elif cached_task_id:
                app_logger.info("Task ID found in Redis, checking if running...")
                async_result = AsyncResult(cached_task_id.decode('utf-8'), app=celery_app)
                if async_result.state in ['PENDING', 'STARTED', 'RETRY']:
                    app_logger.info("Map Data task is running, setting loading screen")
                    #Do nothing, wait for task to complete
                    flask_socketio.emit('loading', {'loading': True}, room=request.sid)
                    app_logger.info(f"loading event emitted to room: {request.sid}")

                elif async_result.state == 'SUCCESS':
                    map_data_json = redis_client.get('map_data')
                    if map_data_json:
                         try:
                            map_data = json.loads(map_data_json)
                            if isinstance(map_data, dict) and 'map_data' in map_data:
                                app_logger.info("Retrieved map_data from Redis after successful task completion")
                                cache_timestamp = map_data.get('cache_timestamp')  # Retrieve the timestamp from the cache
                                socketio.emit('map_data_update', {'map_data': map_data['map_data'], 'cache_timestamp': cache_timestamp})
                                flask_socketio.emit('loading', {'loading': False}, room=request.sid)
                                app_logger.info(f"loading event emitted to room: {request.sid}")
                            else:
                                app_logger.info("Retrieved old style map_data from Redis after successful task completion")
                                socketio.emit('map_data_update', {'map_data': map_data, 'cache_timestamp': None})
                                flask_socketio.emit('loading', {'loading': False}, room=request.sid)
                                app_logger.info(f"loading event emitted to room: {request.sid}")
                         except json.JSONDecodeError:
                             app_logger.info("Retrieved non JSON map_data from Redis after successful task completion")
                             socketio.emit('map_data_update', {'map_data': map_data_json, 'cache_timestamp': None})
                             flask_socketio.emit('loading', {'loading': False}, room=request.sid)
                             app_logger.info(f"loading event emitted to room: {request.sid}")
                    else:
                        app_logger.info("Redis data not found after a successful task.")
                        task = celery_app.send_task('populate_map_data_if_needed')
                        redis_client.set('map_data_task_id', task.id)
                        app_logger.info(f"Triggered map data generation, task id: {task.id}")
                        # If the task has completed or failed, emit the loading signal as False.
                        # Keep 'loading' as True while the task is being run.
                        flask_socketio.emit('loading', {'loading': True}, room=request.sid)
                        app_logger.info(f"loading event emitted to room: {request.sid}")
                else:
                    app_logger.warning(
                        "Previous task failed.")  # Handle task failure (e.g., retry or display an error)
            else:
                app_logger.info("Map data not found in Redis. Generating...")
                task = celery_app.send_task('populate_map_data_if_needed')
                redis_client.set('map_data_task_id', task.id)
                app_logger.info(f"Starting map data generation task id: {task.id}")

    except ConnectionError as e:
        app_logger.error(f"Redis connection error: ")
        # In case of an error emit loading as False.
        flask_socketio.emit('loading', {'loading': False}, room=request.sid)
        app_logger.info(f"loading event emitted to room: {request.sid}")
    except Exception as e:
        app_logger.exception("Unhandled error in index route:")
        # In case of an error emit loading as False.
        flask_socketio.emit('loading', {'loading': False}, room=request.sid)
        app_logger.info(f"loading event emitted to room: {request.sid}")


# Socket.IO event handler for receiving map data
@socketio.on('connect')
def handle_connect():
    app_logger.info('Client connected via SocketIO')
    join_room(request.sid)  # Creates a private room for each connected client.
    # emits message only to the client in the room with session ID as room name.
    flask_socketio.emit('loading', {'loading': True}, room=request.sid)  # Start loading
    app_logger.info(f"loading event emitted to room: {request.sid}")
    emit('map_data')

# main with Websockets.py
@app.route('/map_data_callback', methods=['POST'])  # Changed to POST method
def map_data_callback():
    data = request.get_json()
    app_logger.info("map_data_callback request.get_json():", data)
    """ Callback endpoint to retrieve map data from Redis and send it via SocketIO. """
    try:
        app_logger.info("map_data_callback() route has been called...")

        data = request.get_json()  # Get the json data
        if data and 'map_data' in data:
            map_data = data['map_data']
            app_logger.info(f"map_data has been received")
            # Retrieve existing map data from redis.
            existing_map_data_json = redis_client.get('map_data')
            if existing_map_data_json:
                existing_map_data = json.loads(existing_map_data_json)
                # Add the new alerts to existing alerts, only if the page is > 1.  On the first request the whole set is overwritten.
                if map_data['page'] > 1:
                    existing_map_data['alerts'].extend(map_data['alerts'])
                    map_data['alerts'] = existing_map_data['alerts']  # Ensure all data is sent to the user.
                    app_logger.info(f"Added {len(map_data['alerts'])} new alerts to redis: ")
                else:
                    app_logger.info("This is the first page, overwriting the cache")

                # Check if cache_timestamp exists in the redis data, if not add one.
                cache_timestamp = existing_map_data.get('cache_timestamp')
                if not cache_timestamp:
                    cache_timestamp = datetime.now(timezone.utc).isoformat()
                    existing_map_data['cache_timestamp'] = cache_timestamp
                    redis_client.set('map_data', json.dumps({'map_data': map_data, 'cache_timestamp': cache_timestamp}))
                else:
                    redis_client.set('map_data', json.dumps({'map_data': map_data, 'cache_timestamp': cache_timestamp}))
                socketio.emit('map_data_update', {'map_data': map_data, 'cache_timestamp': cache_timestamp})  # Send the data via socketio
                flask_socketio.emit('loading', {'loading': False}, room=request.sid)
                app_logger.info(f"loading event emitted to room: {request.sid}")
                app_logger.info(f'Map data broadcasted via SocketIO, page: {map_data["page"]} of {map_data["total_pages"] if map_data.get("total_pages") else "Unknown"}')
                return jsonify({'status': 'success', 'message': 'Map data broadcasted via SocketIO'}), 200
            else:
                 app_logger.info("No existing data in redis.")
                 #Create a default timestamp.
                 cache_timestamp = datetime.now(timezone.utc).isoformat()
                 redis_client.set('map_data', json.dumps({'map_data': map_data, 'cache_timestamp': cache_timestamp}))
                 socketio.emit('map_data_update', {'map_data': map_data, 'cache_timestamp': cache_timestamp})
                 flask_socketio.emit('loading', {'loading': False}, room=request.sid)
                 app_logger.info(f"loading event emitted to room: {request.sid}")
                 return jsonify({'status': 'success', 'message': 'Map data broadcasted via SocketIO'}), 200
        else:
            app_logger.info(f'No map data found in request body. Nothing to emit')
            return jsonify({'status': 'success', 'message': 'No map data found in request body. Nothing to emit'}), 200
    except Exception as e:
        app_logger.exception("Error in map_data_callback")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/get_user_email_alert_state', methods=['GET'])
@login_required
def get_user_email_alert_state():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({"error": "Missing user_id parameter"}), 400
        user_data = wag_user_alerts_notification_zone_collection.find_one({"_id": ObjectId(user_id)})
        if user_data:
            email_alerts_enabled = user_data.get('email_alerts_enabled', False)  # Default to False if not set
            return jsonify({"email_alerts_enabled": email_alerts_enabled}), 200
        else:
           return jsonify({'error': "User not found"}), 404

    except pymongo_errors.PyMongoError as e:
        app_logger.error(f"Database error fetching user email alert state: ")
        return jsonify({"error": "Database error"}), 500
    except Exception as e:
        app_logger.exception(f"Unexpected error fetching user email alert state: ")
        return jsonify({"error": "Server error"}), 500

@app.route('/update_user_email_alert_state', methods=['POST'])
@login_required
def update_user_email_alert_state():
    try:
        data = request.get_json()
        if not data or 'user_id' not in data or 'email_alerts_enabled' not in data:
            return jsonify({"error": "Invalid data format"}), 400
        user_id = data['user_id']
        email_alerts_enabled = data['email_alerts_enabled']

        # Update the user's email_alerts_enabled setting in MongoDB
        result = wag_user_alerts_notification_zone_collection.update_one({"_id": ObjectId(user_id)}, {"$set": {"email_alerts_enabled": email_alerts_enabled}})
        if result.modified_count == 1:
            # Check if email alerts is enabled, and if so trigger a scan and send.
            if email_alerts_enabled:
                app_logger.info(f"Email alerts enabled for user {user_id}. Starting send alerts.")
                task = celery_app.send_task('check_for_and_send_alerts') # Call the function via Celery, and get a task id.
                return jsonify({"message": "User email alert state updated successfully", "task_id": task.id}), 200
            return jsonify({"message": "User email alert state updated successfully"}), 200
        else:
            return jsonify({"error": "User not found or state not updated"}), 404
    except pymongo_errors.PyMongoError as e:
        app_logger.error(f"Database error updating user email alert state: {e}")
        return jsonify({"error": "Database error"}), 500
    except Exception as e:
        app_logger.exception(f"Unexpected error updating user email alert state: {e}")
        return jsonify({"error": "Server error"}), 500

@app.route('/send_alert_snapshots', methods=['POST'])
@login_required
def send_alert_snapshots():
    """Sends current OWA alerts within user's alert zones to the user via email."""
    try:
        app_logger.info(f"Manual alert snapshot requested by user: {current_user.email}")
        alert_id = request.form.get('alert_id')
        # Fetch the specific alert zone, not all of the users zones
        zone = wag_user_alerts_notification_zone_collection.find_one({"_id": ObjectId(alert_id)},
                                                                         {"_id": 1, "user_id": 1, "email": 1,
                                                                          "geometry": 1, "notifications": 1})
        if not zone:
            return jsonify({"error": f"Error: Alert zone ID not found: {alert_id}"}), 404

        num_alerts_sent = 0
        user_id = zone["user_id"]
        user_email = zone["email"]
        wag_zone_geometry = zone.get("geometry", None)

        if wag_zone_geometry:
            task = celery_app.send_task('find_matching_owa_alerts_task', args=[wag_zone_geometry])
            matching_alerts = task.get()  # get the results of the task
            num_alerts = 0
            for owa_alert in matching_alerts:
                num_alerts += 1
                app_logger.info(
                    f"send alert snapshot is sending alert for User {user_email} : , Alert ID: {zone['_id']}, OWA Alert: {owa_alert} ")
                celery_app.send_task('send_weather_alert', args=[user_email, owa_alert, str(zone["_id"])])

            num_alerts_sent += num_alerts
            app_logger.info(f"Number of alerts sent {num_alerts_sent} for {user_email}.")
        else:
            app_logger.info(f"User  has no valid geometry defined")
        app_logger.info(f"Manual alert snapshot process completed. Total alerts sent: {num_alerts_sent}")
        return jsonify({"message": f"Alert snapshots sent for {num_alerts_sent} alerts."}), 200
    except Exception as e:
        app_logger.exception("Error in send_alert_snapshots:")
        return jsonify({"error": f"Error sending alert snapshots: {str(e)}"}), 500


@app.route('/send_single_alert_snapshot', methods=['POST'])
@login_required
def send_single_alert_snapshot():
    """Sends a single OWA alert based on the alert key."""
    try:
        app_logger.info(f"Manual single alert snapshot requested by user: {current_user.email}")
        alert_key = request.form.get('alert_key')

        # Convert the alert_key string to an ObjectId
        try:
            alert_key_object_id = ObjectId(alert_key)
            app_logger.info(f"Attempting to find alert with key: {alert_key_object_id}")
        except Exception as e:
            app_logger.error(f"Invalid ObjectId format: {alert_key}. Error: {str(e)}")
            return jsonify({"error": f"Invalid ObjectId format."}), 400

        # Fetch the specific alert using the alert_key as an ObjectId
        alert = owa_collection.find_one({"_id": alert_key_object_id})

        if not alert:
            app_logger.error(f"Error: Alert with id {alert_key} not found.")
            return jsonify({"error": f"Error: Alert with id {alert_key} not found."}), 404
        app_logger.info(f"Found Alert: {alert}")
        user_email = alert.get("email")
        owa_alert = alert.get("owa_alert")

        app_logger.info(f"User email: {user_email}, owa_alert: {owa_alert}")

        if owa_alert:
            app_logger.info(
                f"Sending single alert for User: {user_email}, Alert ID: {alert_key}")
            celery_app.send_task('send_weather_alert', args=[user_email, owa_alert, str(alert_key)])
        else:
            app_logger.info(f"User {user_email} has no valid owa_alert defined for alert {alert_key}.")
            celery_app.send_task('send_weather_alert', args=[user_email, owa_alert, str(alert_key)])

        app_logger.info(f"Manual single alert snapshot process completed.")
        return jsonify({"message": f"Alert snapshot sent for alert: {alert_key}."}), 200
    except Exception as e:
        app_logger.exception("Error in send_single_alert_snapshot:")
        return jsonify({"error": f"Error sending alert snapshot: {str(e)}"}), 500
'''

#Something for further development, the Mongo DB Change Sream which adds live alerts as they are recieved. Also need to adapt the map generation or create generate_partial_map_data_task

def start_change_stream():
    try:
        app_logger.info("Starting MongoDB Change Stream")
        # Create a new thread, this is required because you cannot execute the change_stream in the main thread.
        change_stream_thread = threading.Thread(target=watch_for_owa_changes, daemon=True)
        change_stream_thread.start()
        app_logger.info("MongoDB Change Stream Started.")
    except pymongo_errors.PyMongoError as e:
         app_logger.error(f"MongoDB error starting change stream:")
    except Exception as e:
         app_logger.exception(f"Error starting MongoDB change stream: ")

def watch_for_owa_changes():
 try:
     with MongoClient(MONGODB_URI, tlsCAFile=certifi.where()) as client:
         db = client[OWA_DATABASE_NAME]
         collection = db[OWA_COLLECTION_NAME]
         change_stream = collection.watch(full_document="updateLookup")  # Initialize change stream
         for change in change_stream:
             if change['operationType'] in ['insert', 'update']:
                full_document = change['fullDocument']
                # Convert any ObjectId values to strings before sending to celery
                if full_document and isinstance(full_document, dict):
                    full_document_stringified = {
                        key: str(value) if isinstance(value, ObjectId) else value
                            for key, value in full_document.items()
                    }
                    celery_app.send_task('generate_partial_map_data_task', args=[full_document_stringified])  # Send stringified doc
                else:
                    celery_app.send_task('generate_partial_map_data_task', args=[full_document])  # Send as is if not dict
                # Add this line to trigger alerts after an alert is updated.
                celery_app.send_task('check_for_and_send_alerts')

 except pymongo_errors.PyMongoError as e:
      app_logger.error(f"MongoDB error in change stream: ")
 except Exception as e:
      app_logger.exception(f"Error in MongoDB change stream: ")

start_change_stream()
'''

def scheduled_task_two_hours():
    try:
        celery_app.send_task('keep_recent_entries_efficient')
        celery_app.send_task('check_for_and_send_alerts')
        app_logger.info("scheduled_task_two_hours Scheduled task completed.")
    except Exception as e:
        app_logger.exception("Error in scheduled_task_two_hours scheduled task:")

def scheduled_task_one_hour():
    try:
        celery_app.send_task('populate_map_data_if_needed')
        app_logger.info("scheduled_task_one_hour Scheduled task completed.")
    except Exception as e:
        app_logger.exception("Error in scheduled_task_one_hour scheduled task:")

scheduler_running = threading.Event()
scheduler = BackgroundScheduler()

def start_scheduler():
    try:
        if scheduler_running.is_set():
            app_logger.warning("Scheduler is already running.")
            return

        scheduler.add_job(
            scheduled_task_two_hours,
            'interval',
            seconds=7200,
            next_run_time=datetime.now()
        )
        scheduler.add_job(
            scheduled_task_one_hour,
            'interval',
            seconds=3600,
            next_run_time=datetime.now()
        )


        scheduler.start()
        scheduler_running.set()
        app_logger.info("Scheduler started.")
    except Exception as e:
        app_logger.exception("Error starting scheduler:")
        scheduler_running.clear()

def shutdown_scheduler():
    try:
        if scheduler_running.is_set():
            scheduler.shutdown(wait=True)
            scheduler_running.clear()
            app_logger.info("Scheduler shut down successfully.")
        else:
            app_logger.info("Scheduler is not running. Shutdown skipped.")
    except Exception as e:
        app_logger.exception("Error shutting down scheduler:")

def close_mongo_connection():
    try:
        client.close()
        app_logger.info("MongoDB connection closed successfully.")
    except Exception as e:
        app_logger.info(f"Error closing MongoDB connection: ")

Thread(target=start_scheduler, daemon=True).start() #Daemon thread so it doesn't block app shutdown.
atexit.register(close_mongo_connection)
atexit.register(shutdown_scheduler)

if __name__ == '__main__':
    #socketio.run(app, debug=False) # or app.run(debug=False, host='0.0.0.0', port=5000)
    #socketio.run(app, debug=False, allow_unsafe_werkzeug=True, host='0.0.0.0', port=8080)
    # Make sure to run Deployment using Gunicorn (Recommended for Production)
    #socketio.run(app, debug=False, allow_unsafe_werkzeug=True) # or app.run(debug=False, host='0.0.0.0', port=5000)
    pass
