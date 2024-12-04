# main.py
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, current_app, make_response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from pymongo import MongoClient, errors as pymongo_errors
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv
import certifi
from bson import ObjectId
import atexit
from threading import Thread
import folium
import json
from cachetools import TTLCache
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timezone, timedelta
import re
from flask_mail import Mail, Message
import secrets
import smtplib
from itsdangerous import URLSafeTimedSerializer
import requests
import pymongo
import time
import threading
import logging
import geojson
from tasks import celery
from tasks import generate_map_data_task

load_dotenv()
app = Flask(__name__)
mail = Mail(app)
app.secret_key = os.environ.get('SECRET_KEY')
s = URLSafeTimedSerializer(os.environ.get('SERIALIZER_SECRET'))

logging.basicConfig(level=logging.INFO,  # Changed to INFO
                    format='%(asctime)s - %(levelname)s - %(filename)s - %(lineno)d - %(message)s - %(exc_info)s',
                    filename='app.log',
                    filemode='w')

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
WAG_USER_ALERTS_COLLECTION_NAME = os.environ['WAG_USER_ALERTS_COLLECTION_NAME']
OWA_DATABASE_NAME = os.environ['OWA_DATABASE_NAME']
OWA_COLLECTION_NAME = os.environ['OWA_COLLECTION_NAME']

client = MongoClient(MONGODB_URI, tlsCAFile=certifi.where())
owa_db = client[OWA_DATABASE_NAME]
owa_collection = owa_db[OWA_COLLECTION_NAME]
wag_db = client[WAG_DATABASE_NAME]
wag_collection = wag_db[WAG_USERS_COLLECTION_NAME]
wag_user_alerts_collection = wag_db[WAG_USER_ALERTS_COLLECTION_NAME]

index_name = "start_end_index"
try:
    owa_collection.create_index([("start", pymongo.ASCENDING), ("end", pymongo.ASCENDING)], name=index_name)
    print(f"Index '{index_name}' created successfully (or already exists).")
except pymongo.errors.OperationFailure as e:
    if "already exists" in str(e):  # Check for specific error.
        print(f"Index '{index_name}' already exists.")
    else:
        print(f"Error creating index: {e}")
except Exception as e:
    print(f"An unexpected error occurred: {e}")

finally:
    print("\nIndex information:")
    print(owa_collection.index_information())

allowed_domains_str = os.getenv('ALLOWED_DOMAINS')
print(f"Environment variable ALLOWED_DOMAINS: {allowed_domains_str}")  # Added debugging line

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

print(f"ALLOWED_DOMAINS set: {ALLOWED_DOMAINS}")  # Added debugging line

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


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
            logging.error(f"Database error fetching user: {e}")
            return None
        except Exception as e:
            logging.exception(f"Unexpected error fetching user: {e}")
            return None


@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        logging.info(f"Login attempt: email={email}")

        try:
            user_data = wag_collection.find_one({"email": email})
            if user_data and check_password_hash(user_data["password"], password) and user_data["verified"]:
                user = User(str(user_data["_id"]), user_data["email"], user_data["password"],
                            user_data["first_name"], user_data["last_name"], user_data["verified"])
                login_user(user, remember=True)
                logging.info(f"Login successful: {user.email}")
                return redirect(url_for('index'))
            elif user_data and check_password_hash(user_data["password"], password) and not user_data["verified"]:
                flash("Please verify your email address before logging in.")
            else:
                flash("Invalid email or password")
                logging.warning("Invalid login credentials.")
        except pymongo_errors.PyMongoError as e:
            logging.error(f"Database error during login: {e}")
            flash("Database error")
        except Exception as e:
            logging.exception(f"Unexpected error during login: {e}")
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

    print(f"ALLOWED_DOMAINS in register function: {ALLOWED_DOMAINS}")  # Added debugging line

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
        logging.error(f"Database error during registration: {e}")
        flash("Database error")
        return render_template("register.html", email=email, first_name=first_name, last_name=last_name,
                               allowed_domains=ALLOWED_DOMAINS)
    except Exception as e:
        logging.exception(f"Unexpected error during registration: {e}")
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


# Cache and Scheduled Task
cache = TTLCache(maxsize=100000, ttl=60 * 60 * 24)
# Use a lock to protect the cache update from race conditions
cache_lock = threading.Lock()

# Trim the database
QUERY_LIMIT = 100


def keep_recent_entries_efficient():  # Deletes entries older than last midnight UTC
    try:
        today_utc = datetime.now(tz=timezone.utc)
        yesterday_midnight_timestamp = int(
            (today_utc.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)).timestamp())
        result = owa_collection.delete_many({"$or": [
            {"start": {"$lt": yesterday_midnight_timestamp}},
            {"end": {"$lt": yesterday_midnight_timestamp}}
        ]})
        logging.info(f"Deleted {result.deleted_count} entries older than midnight UTC yesterday.")
    except Exception as e:
        logging.exception("Error cleaning up entries:")


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


@app.route("/")
def index():
    logging.info(
        f"Index page accessed by user: {current_user.email if current_user.is_authenticated else 'Anonymous User'}")
    if current_user.is_authenticated:
        try:
            task = generate_map_data_task.delay(3)  # Launch the Celery task
            task_id = task.id
            # Check for completion, and set loading to False when done
            result = task.get(timeout=1)  # Check for completion after 1s, can be longer
            if result:
                loading = False
                map_data = result
                alerts = map_data['alerts']
                map_js = map_data['map_js']
                active_alerts_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                current_date = datetime.now().strftime('%Y-%m-%d')
                alert_count, date_range = get_alert_stats(alerts)
                alert_counts = {}
                for alert in alerts:
                    severity = alert['severity']
                    alert_counts[severity] = alert_counts.get(severity, 0) + 1

                return render_template('index.html', map_js=map_js, alerts=alerts,
                                       active_alerts_time=active_alerts_time, current_date=current_date,
                                       alert_count=alert_count, date_range=date_range,
                                       alert_counts=alert_counts, loading=loading)
            else:
                loading = True
                map_data = {'map_js': '', 'alerts': []}  # Show empty map

                return render_template('index.html', map_js=map_data['map_js'], alerts=map_data['alerts'],
                                       loading=loading, task_id=task_id)  # Pass task_id to track in js

        except celery.exceptions.TimeoutError:
            loading = True
            map_data = {'map_js': '', 'alerts': []}  # Show empty map
            return render_template('index.html', map_js=map_data['map_js'], alerts=map_data['alerts'],
                                   loading=loading, task_id=task_id)  # Pass task_id to track in js

        except Exception as e:
            logging.exception("Unhandled error in index route:")
            flash("An unexpected error occurred.")
            return render_template('error.html')
    else:
        return redirect(url_for("login"))

@app.route('/task_status/<task_id>')
def task_status(task_id):
    task = generate_map_data_task.AsyncResult(task_id)
    if task.state == 'PENDING':
        response = {
            'state': task.state,
        }
    elif task.state != 'FAILURE':
        response = {
            'state': task.state,
            'result': task.get()
        }
    else:
        # something went wrong in the background job
        response = {
            'state': task.state,
            'result': str(task.info),  # Include error message for debugging
        }
    return jsonify(response)

def get_alert_stats(alerts):
    if alerts:
        earliest_start = min(alert['start'] for alert in alerts)
        latest_start = max(alert['start'] for alert in alerts)
        earliest_date = datetime.fromtimestamp(earliest_start, tz=timezone.utc).strftime('%Y-%m-%d')
        latest_date = datetime.fromtimestamp(latest_start, tz=timezone.utc).strftime('%Y-%m-%d')
        date_range = f"{earliest_date} - {latest_date}"
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

        except geojson.errors.GeoJSONError as e:
            return jsonify({"error": f"Invalid GeoJSON: {str(e)}"}), 400
        except (KeyError, IndexError) as e:
            return jsonify({"error": f"Invalid GeoJSON structure: {str(e)}"}), 400

        alert_description = data.get('alert_description', "No description provided")
        alert_description = alert_description.replace("<", "&lt;").replace(">", "&gt;")
        alert_name = data.get('alert_name', "Unnamed Alert")
        alert_name = alert_name.replace("<", "&lt;").replace(">", "&gt;")

        alert_data = {
            "user_id": current_user.id,
            "geometry": geometry,
            "alert_creation_time": datetime.now(tz=timezone.utc),
            "email_sent": False,
            "alert_description": alert_description,
            "email": current_user.email,
            "alert_name": alert_name
        }

        result = wag_user_alerts_collection.insert_one(alert_data)
        alert_id = str(result.inserted_id)
        task = celery.send_task('tasks.send_alert_notification_zone_creation_email', args=[alert_id])
        return jsonify({"message": "Alert created successfully", "task_id": task.id, "alert_id": alert_id}), 202

    except Exception as e:
        logging.exception("Error in create_alert_zone:")
        return jsonify({"error": f"Error creating alert: {str(e)}"}), 500


@app.route('/delete_alert_zone/<alert_id>', methods=['DELETE'])
@login_required  # Assuming you have login_required decorator
def delete_alert_zone(alert_id):
    try:
        alert_id_object = ObjectId(alert_id)
        result = wag_user_alerts_collection.delete_one({"_id": alert_id_object, "user_id": current_user.id})

        if result.deleted_count == 1:
            return jsonify({"message": "Alert zone deleted successfully"}), 200
        else:
            return jsonify({"error": "Alert zone not found or you don't have permission to delete it"}), 404
    except pymongo_errors.PyMongoError as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Error deleting alert zone: {str(e)}"}), 500


def send_alert_notification_zone_creation_email(alert_id):
    try:
        with MongoClient(MONGODB_URI, tlsCAFile=certifi.where()) as client:
            db = client[WAG_DATABASE_NAME]
            collection = db[WAG_USER_ALERTS_COLLECTION_NAME]
            alert_data = collection.find_one({"_id": ObjectId(alert_id)})

            if alert_data is None:
                logging.warning(f"Alert with ID {alert_id} not found.")
                return  # Exit early if alert not found

            logging.info(f"Retrieved Alert Data: {alert_data}")  # More detailed logging

            # Use .get() for safer access; provide defaults
            email = alert_data.get('email', 'support@weatheralerts.global')  # Safe default email
            name = alert_data.get('alert_name', "Unnamed Alert")
            description = alert_data.get('alert_description', 'No description provided')
            creation_time = alert_data.get('alert_creation_time', datetime.now(tz=timezone.utc))
            geometry = alert_data.get('geometry', {})
            coordinates = geometry.get('coordinates', [])
            geojson_str = json.dumps(geometry) if coordinates else "Geometry data not available"
            center_lat, center_lon = calculate_center(geometry)

            msg = Message('Active Alert Notification Zone Created', sender=app.config['MAIL_DEFAULT_SENDER'],
                          recipients=[email])
            msg.body = f"""You have created a new Active Alert Notification Zone.

            Name: {name}
            Description: {description}
            Creation Time/Date: {creation_time}
            GeoJSON: {geojson_str}
            Center Latitude: {center_lat}
            Center Longitude: {center_lon}
            """
            with app.app_context():
                mail.send(msg)  # Sending the message

            collection.update_one({"_id": ObjectId(alert_id)}, {"$set": {"email_sent": True}})
            logging.info(f"Alert Email sent to {email} for alert ID: {alert_id}")

    except pymongo_errors.PyMongoError as e:
        logging.exception(f"PyMongo database error in send_alert_notification_zone_creation_email: {e}")
    except smtplib.SMTPException as e:
        logging.exception(f"SMTP error sending email: {e}")
    except Exception as e:
        logging.exception(f"Unexpected error in send_alert_notification_zone_creation_email: {e}")


@app.route('/get_user_alerts', methods=['GET'])
@login_required
def get_user_alerts():
    try:
        user_alerts = wag_user_alerts_collection.find({"user_id": current_user.id})
        alerts_data = []
        for alert in user_alerts:
            alert['_id'] = str(alert['_id'])
            alerts_data.append(alert)
        logging.info(
            f"Returning {len(alerts_data)} alerts for user {current_user.id}: {alerts_data}")  # More detailed logging
        return jsonify({'alerts': alerts_data})

        return jsonify({'alerts': alerts_data})
    except pymongo_errors.PyMongoError as e:
        logging.exception(f"PyMongo database error in get_user_alerts: {e}")
        return jsonify({"error": "Database error"}), 500
    except Exception as e:
        logging.exception(f"Unexpected error in get_user_alerts: {e}")
        return jsonify({"error": "Server error"}), 500


def check_alert_overlap(user_id, alert_geojson):
    """Checks if an alert overlaps with any of a user's saved alert zones."""

    try:
        # Query for user's alert zones
        user_alerts = wag_user_alerts_collection.find({"user_id": user_id, "email_sent": False},
                                                      {"geometry": 1, "_id": 1})  # Only fetch necessary fields

        for user_alert in user_alerts:
            user_geometry = user_alert['geometry']
            if user_geometry and user_geometry.get('coordinates'):  # additional check to prevent errors
                # Check for overlap using $geoIntersects (requires GEOSPHERE index)
                if owa_collection.find({"$geoIntersects": {"geometry": alert_geojson}}, limit=1).count() > 0:
                    return True  # Overlaps, send email
        return False

    except pymongo_errors.PyMongoError as e:
        logging.exception(f"Database error during alert overlap check: ")
        return False
    except Exception as e:
        logging.exception(f"Unexpected error during alert overlap check: ")
        return False


# Needs work - rewrite
def check_for_and_send_alerts():
    try:
        # Correct GeoJSON Handling within Aggregation Pipeline
        intersecting_alerts = owa_collection.aggregate([
            {
                "$lookup": {
                    "from": WAG_USER_ALERTS_COLLECTION_NAME,
                    "let": {"geometry": {"type": "$geometry.type", "coordinates": "$geometry.coordinates"}},
                    # Important change: correctly pass geometry
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [  # Ensure both geometries are valid before comparison
                                        {"$eq": ["$geometry.type", "Polygon"]},  # Check if it's a polygon
                                        {"$geoIntersects": ["$geometry", "$$geometry"]}  # Correctly use geoIntersects
                                    ]
                                }
                            }
                        },
                        {"$project": {"_id": 1, "user_id": 1, "email": 1}}
                    ],
                    "as": "users"
                }
            },
            {"$unwind": "$users"},
            {"$match": {"users.user_id": {"$exists": True, "$ne": []}}},
            {"$project": {"_id": 1, "users.user_id": 1, "users.email": 1, "geometry": 1, "msg_type": 1, "categories": 1,
                          "urgency": 1, "severity": 1, "certainty": 1, "start": 1, "end": 1, "sender": 1,
                          "description": 1}}
        ])

        # Improved iteration and email handling
        for alert in intersecting_alerts:
            for user_info in alert['users']:
                user_email = user_info['email']
                send_alert_email(user_email, alert)

    except pymongo.errors.OperationFailure as e:
        logging.exception(
            f"Database error during alert check and email sending ({e.code}): {e.details}")  # Detailed error logging
    except Exception as e:
        logging.exception(f"Unexpected error during alert check and email sending: {e}")


def send_alert_email(user_email, alert_data):
    try:
        msg = Message('Weather Alert Notification', sender=app.config['MAIL_DEFAULT_SENDER'], recipients=[user_email])
        msg.body = f"""A new weather alert matches your saved zone.

        Alert Details:
        Message Type: {alert_data['msg_type']}
        Categories: {', '.join(alert_data['categories'])}
        Urgency: {alert_data['urgency']}
        Severity: {alert_data['severity']}
        Certainty: {alert_data['certainty']}
        Start Time: {datetime.fromtimestamp(alert_data['start']).strftime('%Y-%m-%d %H:%M:%S UTC')}
        End Time: {datetime.fromtimestamp(alert_data['end']).strftime('%Y-%m-%d %H:%M:%S UTC')}
        Sender: {alert_data['sender']}
        Description: {alert_data['description']}
        """
        with app.app_context():
            mail.send(msg)
        logging.info(f"Alert email sent to {user_email}")

    except smtplib.SMTPException as e:
        logging.exception(f"SMTP error sending alert email: ")
    except Exception as e:
        logging.exception(f"Unexpected error sending alert email: ")


def scheduled_task():
    try:
        keep_recent_entries_efficient()
        map_data = generate_map_data()  # generate_map_data is called from the scheduler
        cache['map_data'] = map_data
        logging.info("Scheduled task completed.")
    except Exception as e:
        logging.exception("Error in scheduled task:")


scheduler = BackgroundScheduler()
scheduler.add_job(scheduled_task, 'interval', seconds=7200)  # Update every 2 hours


# scheduler.add_job(check_for_and_send_alerts, 'interval', seconds=60, max_instances=500)

def start_scheduler():
    try:
        # Run the task once at startup
        scheduled_task()
        scheduler.start()
        logging.info("Scheduler started.")
    except Exception as e:
        logging.exception("Error starting scheduler:")


def shutdown_scheduler():
    try:
        scheduler.shutdown()
        logging.info("Scheduler shut down successfully.")
    except Exception as e:
        logging.exception("Error shutting down scheduler: ")


atexit.register(shutdown_scheduler)
Thread(target=start_scheduler).start()

if __name__ == '__main__':
    app.run(debug=False)  # or app.run(debug=False, host='0.0.0.0', port=5000)