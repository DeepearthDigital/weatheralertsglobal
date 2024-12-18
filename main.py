# main.py with Websockets
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from pymongo import MongoClient, errors as pymongo_errors
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv
import certifi
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
import gevent

load_dotenv()
app = Flask(__name__)
mail = Mail(app)
app.secret_key = os.environ.get('SECRET_KEY')
s = URLSafeTimedSerializer(os.environ.get('SERIALIZER_SECRET'))

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")  # Allow cross-origin for local development

# Create a logger for Celery tasks
app_logger = logging.getLogger('app')
app_logger.setLevel(logging.INFO)

# Truncate the log file at the start
log_file_path = 'app.log'
if os.path.exists(log_file_path):
    with open(log_file_path, 'w'):
        pass  # Simply open the file in write mode and immediately close it; this truncates it.

# Create a file handler for Celery task logs
file_handler = logging.handlers.RotatingFileHandler(log_file_path, maxBytes=10 * 1024 * 1024,
                                                    backupCount=5)  # 10MB, 5 backups
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s - %(lineno)d - %(message)s - %(exc_info)s')
file_handler.setFormatter(formatter)
app_logger.addHandler(file_handler)

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


# Trim the database
def keep_recent_entries_efficient(days_to_keep=0):
    try:
        today_utc = datetime.now(timezone.utc)
        retention_cutoff_utc = today_utc - timedelta(days=days_to_keep)
        retention_cutoff_timestamp = int(retention_cutoff_utc.timestamp())

        # Delete only alerts that are completely in the past
        result = owa_collection.delete_many({"end": {"$lte": retention_cutoff_timestamp}})
        app_logger.info(f"Deleted {result.deleted_count} entries completely in the past.")
    except Exception as e:
        app_logger.exception("Error cleaning up entries:")


@app.route("/")
def index():
    app_logger.info(
        f"Index page accessed by user: {current_user.email if current_user.is_authenticated else 'Anonymous User'}")
    if current_user.is_authenticated:
        map_data = {'map_js': "", 'alerts': []}  # Initialize map_data here.  Important!
        loading = False
        task_id = None  # Initialize task_id to None here.

        try:
            app_logger.info("Attempting to retrieve map_data from Redis...")
            map_data_json = redis_client.get('map_data')
            if map_data_json:
                map_data = json.loads(map_data_json)
                app_logger.info("Retrieved map_data from Redis.")
                loading = False
            else:
                app_logger.info("Redis cache miss for map_data. Retrieving from database...")
                loading = True
                task_id = redis_client.get('map_data_task_id')  # Populate task_id
                if task_id:
                    async_result = AsyncResult(task_id, app=celery_app)
                    if async_result.state == 'PENDING' or async_result.state == 'STARTED':
                        app_logger.info('Map data generation task already running.')
                        loading = True  # Set loading to true to indicate that task is running
                    elif async_result.state == 'SUCCESS':
                        map_data_json = redis_client.get('map_data')
                        if map_data_json:
                            map_data = json.loads(map_data_json)
                            app_logger.info("Retrieved map_data from Redis.")
                            loading = False
                    else:
                        app_logger.warning(
                            "Previous task failed.")  # Handle task failure (e.g., retry or display an error)
                        flash("Error generating map data. Please try again later.")
                        loading = False  # Ensure loading is false
                else:
                    app_logger.info("Task ID not found in Redis.")
                    loading = True

            # Handle the response - this section is now ALWAYS executed
            alerts = map_data.get('alerts', [])
            map_js = map_data.get('map_js', '')

            active_alerts_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            current_date = datetime.now().strftime('%Y-%m-%d')
            alert_count, date_range = get_alert_stats(alerts)
            alert_counts = {}
            for alert in alerts:
                severity = alert.get('severity', 'Unknown')  # Handle potential missing keys
                alert_counts[severity] = alert_counts.get(severity, 0) + 1

            #app_logger.info(f"Alerts sent to template: {alerts}")  # Debugging
            return render_template('index.html', map_js=map_js, alerts=alerts,
                                   active_alerts_time=active_alerts_time, current_date=current_date,
                                   alert_count=alert_count, date_range=date_range,
                                   alert_counts=alert_counts, loading=loading, task_id=task_id)

        except ConnectionError as e:
            app_logger.error(f"Redis connection error: ")
            flash("A temporary error occurred. Please try again later.")  # More user-friendly message
            return render_template('error.html')  # Handle Redis connection errors appropriately
        except Exception as e:
            app_logger.exception("Unhandled error in index route:")
            flash("An unexpected error occurred.")
            return render_template('error.html')

    else:
        return redirect(url_for("login"))


def get_alert_stats(alerts):
    if alerts:
        earliest_start = min(alert['start'] for alert in alerts)
        latest_start = max(alert['start'] for alert in alerts)
        earliest_date = datetime.fromtimestamp(earliest_start, tz=timezone.utc).strftime('%Y-%m-%d')
        latest_date = datetime.fromtimestamp(latest_start, tz=timezone.utc).strftime('%Y-%m-%d')
        date_range = f" - "
        return len(alerts), date_range
    else:
        return 0, "No alerts currently displayed"


def translate_text(text, target_language='en'):
    translate_url = 'https://translation.googleapis.com/language/translate/v2'

    headers = {'Content-Type': 'application/json'}

    key = os.getenv('GOOGLE_API_KEY')  # Replace with your own API key
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

def find_matching_owa_alerts(wag_zone_geometry):
    """Finds OWA alerts intersecting with a WAG alert zone.

    Args:
        wag_zone_geometry: The GeoJSON geometry of the WAG alert zone.

    Returns:
        A pymongo cursor of matching OWA alerts.  Returns an empty cursor if none are found or if the input geometry is invalid.
    """
    try:
        #Validate geometry before querying.  A more robust approach than in the original code.
        geojson.loads(json.dumps(wag_zone_geometry))
        if wag_zone_geometry['type'] not in ['Polygon', 'MultiPolygon', 'Point', 'LineString']:
            app_logger.info(f"Invalid geometry type in find_matching_owa_alerts: {wag_zone_geometry['type']}")
            return owa_collection.find({})  # Return empty cursor for invalid geometry

        return owa_collection.find({
            "geometry": {
                "$geoIntersects": {"$geometry": wag_zone_geometry}
            },
            "end": {"$gt": int(datetime.now(timezone.utc).timestamp())} #Only include active alerts
        })
    except (KeyError, TypeError, geojson.errors.GeoJSONError) as e:
        app_logger.info(f"Error validating or querying OWA alerts: ")
        return owa_collection.find({}) #Return an empty cursor


def check_for_and_send_alerts():
    """Checks for new OWA alerts and sends emails to affected users."""
    try:
        users = wag_user_alerts_notification_zone_collection.find({}, {"_id": 1, "user_id": 1, "email": 1, "geometry": 1, "notifications": 1}).limit(100)
        app_logger.info(f"Number of users found: {len(list(users))}")

        for user in users:
            user_id = user["user_id"]
            user_email = user["email"]
            wag_zone_geometry = user.get("geometry", None)
            app_logger.debug(f"Processing user: , User ID: , Geometry: ")

            if wag_zone_geometry:
                matching_alerts = find_matching_owa_alerts(wag_zone_geometry)
                num_alerts = matching_alerts.count()
                app_logger.info(f"Number of matching alerts for user : ")
                if num_alerts > 0:
                    #Log a sample of the alerts, not all of them
                    sample_alerts = list(matching_alerts.limit(min(num_alerts, 5))) # Limit to 5 for logging
                    app_logger.info(f"Sample of matching alerts for user : ")
                    for owa_alert in matching_alerts:
                        app_logger.info(f"Sending alert for User: , Alert ID: {user['_id']}, OWA Alert: ")
                        send_weather_alert.delay(user_email, owa_alert, user["_id"])
                else:
                    app_logger.info(f"No matching alerts found for user ")
            else:
                app_logger.warning(f"User  has no valid geometry defined")

    except Exception as e:  # Colon added here
        app_logger.exception("Error in check_for_and_send_alerts:")

def populate_map_data_if_needed():
    """Populates map data in Redis only if it doesn't exist or is expired or a task is not in process."""
    try:
        map_data_json = redis_client.get('map_data')  # Returns none if not found
        cached_task_id = redis_client.get('map_data_task_id')  # Returns None if not found
        if not map_data_json or not cached_task_id:
            app_logger.info("Map data not found in Redis or Task ID is missing, Generating...")
            generate_and_cache_map_data_task()
            return
        app_logger.info(f"Task ID {cached_task_id} retrieved from Redis.")
        task = celery_app.AsyncResult(cached_task_id.decode('utf-8'))
        if task.status in ['PENDING', 'STARTED', 'RETRY']:
            app_logger.info(f"Map data found in Redis and last task with id: {cached_task_id.decode('utf-8')} is still running.")
            return  # Task is still running so don't regenerate.
        else:
             # If no task is running and we have map data, lets check expiry.
             expiry_time = redis_client.ttl('map_data')
             if expiry_time == -2:  # Key not found (should not happen in this section)
                 app_logger.info("Map data not found in Redis. Generating...")
                 generate_and_cache_map_data_task()
                 redis_client.delete('map_data_task_id')  # Only clear the task ID if map data was cleared.
                 logger.info(f"Data with key 'map_data_task_id' deleted from Redis")
                 return
             elif expiry_time == -1:  # No expiry, which means the data is valid.
                app_logger.info(f"Map data found in Redis and it has not expired.")
                return
             elif expiry_time <= 0:  # If expiry is less than or equal to 0, the data is expired.
                 app_logger.info("Map data in Redis is expired. Regenerating...")
                 redis_client.delete('map_data')  # delete the expired data
                 logger.info(f"Data with key 'map_data' deleted from Redis")
                 redis_client.delete('map_data_task_id')  # Only clear the task ID if map data was cleared.
                 logger.info(f"Data with key 'map_data_task_id' deleted from Redis")
                 generate_and_cache_map_data_task()
                 return
    except ConnectionError as e:
        app_logger.error(f"Redis connection error: ")
    except Exception as e:
        app_logger.exception("Error checking or populating map data:")

def generate_and_cache_map_data_task():
    """Triggers Celery task to generate map data, and then emit the data to clients."""
    task = celery_app.send_task('generate_map_data_task')
    redis_client.set('map_data_task_id', task.id)  #Cache the task ID
    app_logger.info(f"Map data generation task triggered, task id: {task.id}")
    app_logger.info(f"Task ID {task.id} saved to Redis.")


# Socket.IO event handler for receiving map data
@socketio.on('connect')
def handle_connect():
    app_logger.info('Client connected via SocketIO')
    #handle_get_map_data() # Call get_map_data on connection

# Socket.IO event handler for receiving map data
@socketio.on('get_map_data')
def handle_get_map_data():
    try:
        map_data_json = redis_client.get('map_data')
        if map_data_json:
            map_data = json.loads(map_data_json)
            emit('map_data_update', {'map_data': map_data})
            app_logger.info(f'Map data sent to client via SocketIO')
        else:
            app_logger.info(f'No map data found in redis, nothing sent')
    except Exception as e:
        app_logger.exception("Error handling get_map_data via SocketIO")

# main with Websockets.py
@app.route('/map_data_callback', methods=['POST'])  # Changed to POST method
def map_data_callback():
    """ Callback endpoint to retrieve map data from Redis and send it via SocketIO. """
    try:
        print("map_data_callback() route has been called...")
        app_logger.info("map_data_callback() route has been called...")

        data = request.get_json()  # Get the json data
        if data and 'map_data' in data:
            map_data = data['map_data']
            print(f"map_data received")
            app_logger.info(f"map_data received:")
            socketio.emit('map_data_update', {'map_data': map_data})  # Send the data via socketio
            app_logger.info(f'Map data broadcasted via SocketIO: ')
            return jsonify({'status': 'success', 'message': 'Map data broadcasted via SocketIO'}), 200
        else:
            app_logger.info(f'No map data found in request body. Nothing to emit')
            return jsonify({'status': 'success', 'message': 'No map data found in request body. Nothing to emit'}), 200
    except Exception as e:
        app_logger.exception("Error in map_data_callback")
        return jsonify({'status': 'error', 'message': str(e)}), 500


def alert_notification_timer():
    try:
        check_for_and_send_alerts()
        app_logger.info("alert_notification_timer Scheduled task completed.")
    except Exception as e:
        app_logger.exception("Error in alert_notification_timer: ")

def scheduled_task():
    """Combined scheduled task. Only runs check_for_and_send_alerts and updates the map data every 4 hours."""
    try:
        keep_recent_entries_efficient()
        populate_map_data_if_needed()
        app_logger.info("Scheduled task completed.")
    except Exception as e:
        app_logger.exception("Error in scheduled task:")

scheduler = BackgroundScheduler()
scheduler.add_job(scheduled_task, 'interval', seconds=7200)  # Run two hours
scheduler.add_job(alert_notification_timer, 'interval', seconds=60, max_instances=500)

scheduler_running = threading.Event()
def start_scheduler():
    try:
        populate_map_data_if_needed()
        keep_recent_entries_efficient()
        alert_notification_timer()
        scheduler.start()
        scheduler_running.set()
        app_logger.info("Scheduler started.")
    except Exception as e:
        app_logger.exception("Error starting scheduler:")
        scheduler_running.clear()
def shutdown_scheduler():
    try:
        scheduler_running.wait() #Wait for the scheduler to start
        scheduler.shutdown(wait=True) #Gracefully shutdown
        app_logger.info("Scheduler shut down successfully.")
    except Exception as e:
        app_logger.exception("Error shutting down scheduler:")

def close_mongo_connection():
    try:
        client.close()
        app_logger.info("MongoDB connection closed successfully.")
    except Exception as e:
        app_logger.info(f"Error closing MongoDB connection: ")

atexit.register(close_mongo_connection)
atexit.register(shutdown_scheduler)
Thread(target=start_scheduler, daemon=True).start() #Daemon thread so it doesn't block app shutdown.

if __name__ == '__main__':
    #socketio.run(app, debug=False, allow_unsafe_werkzeug=True, host='0.0.0.0', port=8080)
    # Make sure to run Deployment using Gunicorn (Recommended for Production)
    pass