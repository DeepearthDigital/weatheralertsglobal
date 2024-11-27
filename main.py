from flask import Flask, render_template, request, redirect, url_for, flash, make_response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from pymongo import MongoClient, errors as pymongo_errors
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv
import certifi
from bson import ObjectId
import logging
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

load_dotenv()
app = Flask(__name__)
mail = Mail(app)
app.secret_key = os.environ.get('SECRET_KEY')
s = URLSafeTimedSerializer(os.environ.get('SERIALIZER_SECRET'))

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
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
WAG_COLLECTION_NAME = os.environ['WAG_COLLECTION_NAME']
OWA_DATABASE_NAME = os.environ['OWA_DATABASE_NAME']
OWA_COLLECTION_NAME = os.environ['OWA_COLLECTION_NAME']

client = MongoClient(MONGODB_URI, tlsCAFile=certifi.where())
wag_db = client[WAG_DATABASE_NAME]
owa_db = client[OWA_DATABASE_NAME]
wag_collection = wag_db[WAG_COLLECTION_NAME]
owa_collection = owa_db[OWA_COLLECTION_NAME]

allowed_domains_str = os.getenv('ALLOWED_DOMAINS')
print(f"Environment variable ALLOWED_DOMAINS: {allowed_domains_str}") # Added debugging line

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

print(f"ALLOWED_DOMAINS set: {ALLOWED_DOMAINS}") # Added debugging line

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

wag_collection.create_index([("email", pymongo.ASCENDING)])
owa_collection.create_index([("start", pymongo.ASCENDING)])
owa_collection.create_index([("end", pymongo.DESCENDING)])

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
            user_data = wag_collection.find_one({"_id": ObjectId(user_id)}, {"_id": 1, "email": 1, "password": 1, "first_name": 1, "last_name": 1, "verified": 1})
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
        return render_template("register.html", allowed_domains=ALLOWED_DOMAINS, error_message=None)# Pass allowed domains to template

    email = request.form.get("email")
    password = request.form.get("password")
    first_name = request.form.get("first_name")
    last_name = request.form.get("last_name")
    hashed_password = generate_password_hash(password)

    error_message = None
    if not is_valid_email(email):
        error_message = "Please enter a valid email address."
    elif email.split('@')[-1].lower() not in ALLOWED_DOMAINS:
        error_message = f"Registration is restricted to users from {', '.join(ALLOWED_DOMAINS)}."

    if error_message:
        return render_template("register.html", allowed_domains=ALLOWED_DOMAINS, error_message=error_message)

    print(f"ALLOWED_DOMAINS in register function: {ALLOWED_DOMAINS}")  # Added debugging line

    if error:
        return render_template("register.html", error=error, email=email, first_name=first_name, last_name=last_name, allowed_domains=ALLOWED_DOMAINS)


    try:
        user_data = wag_collection.find_one({"email": email})
        if user_data:
            flash("Email already exists")
            return render_template("register.html", email=email, first_name=first_name, last_name=last_name, allowed_domains=ALLOWED_DOMAINS)
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
        return render_template("register.html", email=email, first_name=first_name, last_name=last_name, allowed_domains=ALLOWED_DOMAINS)
    except Exception as e:
        logging.exception(f"Unexpected error during registration: {e}")
        flash("An unexpected error occurred")
        return render_template("register.html", email=email, first_name=first_name, last_name=last_name, allowed_domains=ALLOWED_DOMAINS)

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


def keep_recent_entries_efficient(days_to_keep=30): # Default limit - change for production (say 2 days - roughly 512mb storage required)
    try:
        cutoff_time = datetime.now(tz=timezone.utc) - timedelta(days=days_to_keep)
        cutoff_timestamp = int(cutoff_time.timestamp())
        result = owa_collection.delete_many({"$or": [
            {"start": {"$lt": cutoff_timestamp}},
            {"end": {"$lt": cutoff_timestamp}}
        ]})
        logging.info(f"Deleted {result.deleted_count} entries older than {days_to_keep} days.")
    except Exception as e:
        logging.exception("Error cleaning up entries:")

QUERY_LIMIT = 100  # Default limit - change for production (say 100000)

def generate_map_data():
    start_time = time.time()
    logging.info("Generating map data...")  # Start log message
    my_map = folium.Map(location=[51.4779, 0.0015], zoom_start=5)
    alerts = []
    today_utc = datetime.now(timezone.utc).date()
    start_of_two_days_ago_utc = int((datetime(today_utc.year, today_utc.month, today_utc.day, 0, 0, 0, tzinfo=timezone.utc) - timedelta(days=7)).timestamp())
    end_of_today_utc = int(datetime(today_utc.year, today_utc.month, today_utc.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())

    # Query to include events that span over midnight
    cursor = owa_collection.find({
        "$or": [
            {"start": {"$gte": start_of_two_days_ago_utc, "$lte": end_of_today_utc}},
            # start is within the last two days
            {"end": {"$gte": start_of_two_days_ago_utc, "$lte": end_of_today_utc}}  # end is within the last two days
        ]
    }).limit(QUERY_LIMIT)

    explanation = cursor.explain()
    logging.info(f"Query explanation:\n{explanation}")
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
                'Extreme': '#313131'
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

        except (KeyError, TypeError, IndexError) as e:
            logging.exception(f"Error processing alert data from MongoDB: {e}")

    folium.LayerControl().add_to(my_map)
    map_js = my_map.get_root().render()
    end_time = time.time()
    elapsed_time = end_time - start_time
    logging.info(f"Map data generated in {elapsed_time:.4f} seconds.")  # End log message with elapsed time
    return {'map_js': map_js, 'alerts': alerts}


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


def scheduled_task():
    try:
        keep_recent_entries_efficient()
        map_data = generate_map_data()  # generate_map_data is called from the scheduler
        cache['map_data'] = map_data
        logging.info("Scheduled task completed.")
    except Exception as e:
        logging.exception("Error in scheduled task:")

scheduler = BackgroundScheduler()
scheduler.add_job(scheduled_task, 'interval', seconds=600) # Update every 10 minutes

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


@app.route("/")
def index():
    logging.info(f"Index page accessed by user: {current_user.email if current_user.is_authenticated else 'Anonymous User'}")
    if current_user.is_authenticated:
        try:
            keep_recent_entries_efficient()
            map_data = cache.get('map_data')
            if map_data is None:
                map_data = generate_map_data()
                cache['map_data'] = map_data

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
                                   alert_counts=alert_counts) # Pass alert_counts to the template
        except Exception as e:
            logging.exception("Error in index route:")
            return "An error occurred."
    else:
        return redirect(url_for("login"))

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


if __name__ == '__main__':
    app.run(debug=False)