# --- START OF CORRECTED app.py ---
import secrets
import os
import re
import io # For sending file data in response
from datetime import timedelta, datetime
from functools import wraps

from flask import Flask, request, jsonify, session, redirect, url_for, render_template, flash, g, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import redis as redis

from sqlalchemy import func

r = redis.Redis(host='localhost', port=6379)        ## redis server object init



# Try importing pandas, required for import/export. Handle if not installed.
try:
    import pandas as pd
except ImportError:
    pd = None # Set pandas to None if not installed

# --- Configuration ---
app = Flask(__name__)
# Secret key: Essential for session security. Use environment variable in production.
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
# Database path: Use absolute path relative to this file.
db_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'database.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Session configuration: Filesystem-based sessions.
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30) # Session lifetime
# Ensure session directory exists relative to the app file
session_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'flask_session')
os.makedirs(session_dir, exist_ok=True)
app.config['SESSION_FILE_DIR'] = session_dir
app.config['SESSION_USE_SIGNER'] = True # Recommended for security (signs session cookie)
app.config['SESSION_COOKIE_HTTPONLY'] = True # Prevent client-side script access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax' # Basic CSRF protection

# --- Database Initialization ---
db = SQLAlchemy(app)

# --- Database Models ---

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True) # Added index
    password = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(20), default='user', nullable=False) # 'user', 'judge', 'admin'

    # --- Flag for Judge Role Request ---
    judge_request_pending = db.Column(db.Boolean, default=False, nullable=False)
    # --- END ---

    # --- Fields for Password Reset ---
    reset_token = db.Column(db.String(100), nullable=True, index=True) # Store the secure token
    reset_token_expiration = db.Column(db.DateTime, nullable=True) # Store expiration time
    # --- END ---

    # Relationships
    # Scores given by this user (if they are a judge)
    judge_scores = db.relationship('Scores', back_populates='judge', foreign_keys='Scores.judge_id', lazy='dynamic') # Added lazy='dynamic'

    def __repr__(self):
        return f'<User {self.id}: {self.email} ({self.role})>'

    def set_password(self, password):
        """Hashes and sets the user's password."""
        self.password = generate_password_hash(password)

    def check_password(self, password):
        """Checks if the provided password matches the stored hash."""
        return check_password_hash(self.password, password)

    # --- Methods for Password Reset ---
    def generate_reset_token(self):
        """Generates a secure reset token and sets expiration."""
        token = secrets.token_urlsafe(32)
        self.reset_token = token
        # Set expiration (e.g., 1 hour from now)
        self.reset_token_expiration = datetime.utcnow() + timedelta(hours=1)
        return token

    def is_reset_token_valid(self, token):
        """Checks if the provided token matches and hasn't expired."""
        # Ensure token exists, matches, expiration is set, and expiration is in the future
        return (self.reset_token is not None and
                self.reset_token == token and
                self.reset_token_expiration is not None and
                self.reset_token_expiration > datetime.utcnow())

    def invalidate_reset_token(self):
        """Clears the reset token and expiration after use or expiration."""
        self.reset_token = None
        self.reset_token_expiration = None
    # --- END NEW ---

class Projects(db.Model):
    __tablename__ = 'projects'
    project_id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column(db.String(100), nullable=False, index=True) # Added index
    group_id = db.Column(db.Integer, nullable=False, index=True) # Added index
    description = db.Column(db.Text, nullable=True)
    # Relationships
    # Scores associated with this project
    scores = db.relationship('Scores', back_populates='project', cascade="all, delete-orphan", lazy='dynamic') # Added lazy='dynamic'

    def __repr__(self):
        return f'<Project {self.project_id}: {self.project_name}>'

class Scores(db.Model):
    __tablename__ = 'scores'
    score_id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(100), nullable=False)
    score_given = db.Column(db.Integer, nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.project_id', ondelete='CASCADE'), nullable=False, index=True) # Added index and ondelete
    judge_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True) # Added index
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False) # Added nullable=False

    # Relationships
    project = db.relationship('Projects', back_populates='scores')
    judge = db.relationship('User', back_populates='judge_scores')

    # Constraints
    # Ensure a judge can only give one score per category for a specific project
    __table_args__ = (db.UniqueConstraint('project_id', 'judge_id', 'category', name='_project_judge_category_uc'),)

    def __repr__(self):
        return f'<Score {self.score_id} - Proj:{self.project_id} Judge:{self.judge_id} Cat:{self.category} Score:{self.score_given}>'


# --- Decorators ---
def login_required(f):
    """Decorator to ensure a user is logged in."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if g.current_user is None:
            flash('Please log in to access this page.', 'warning')
            # Store the intended destination in the session
            session['next_url'] = request.url
            return redirect(url_for('login'))
        # Clear the stored URL if login check passes (no longer needed)
        session.pop('next_url', None)
        return f(*args, **kwargs)
    return decorated_function

def role_required(role):
    """Decorator to ensure user has a specific role."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # First, ensure user is logged in
            if g.current_user is None:
                flash('Please log in to access this page.', 'warning')
                session['next_url'] = request.url
                return redirect(url_for('login'))
            # Then, check the role
            if g.current_user.role != role:
                flash(f'You must be an {role} to access this page.', 'danger')
                return redirect(url_for('index')) # Or a specific 'unauthorized' page
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def roles_required(roles):
    """Decorator to ensure user has one of the specified roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # First, ensure user is logged in
            if g.current_user is None:
                flash('Please log in to access this page.', 'warning')
                session['next_url'] = request.url
                return redirect(url_for('login'))
            # Then, check if user's role is in the allowed list
            if g.current_user.role not in roles:
                allowed_roles = ", ".join(roles)
                flash(f'You must have one of the following roles to access this page: {allowed_roles}.', 'danger')
                return redirect(url_for('index')) # Or a specific 'unauthorized' page
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# --- Helper Functions / Template Filters ---
@app.template_filter('format_datetime')
def _jinja2_filter_datetime(date, fmt=None):
    """Formats a datetime object for Jinja templates."""
    if date is None:
        return 'N/A'
    # Ensure it's a datetime object
    if not isinstance(date, datetime):
        try:
            # Attempt to parse if it's an ISO string
            date = datetime.fromisoformat(date)
        except (TypeError, ValueError):
             return date # Return original if not datetime or parsable string

    # Use default format if none provided
    format_str = fmt if fmt else '%Y-%m-%d %H:%M:%S' # More standard default format
    try:
        return date.strftime(format_str)
    except ValueError: # Handle potential issues with the format string
        return str(date) # Fallback

# --- Context Processors ---
@app.context_processor
def inject_user_and_now():
    """Inject current_user and datetime.utcnow into templates."""
    return dict(current_user=g.current_user, now=datetime.utcnow)

# --- Before Request Handlers ---
@app.before_request
def load_logged_in_user():
    """Load user from session into Flask's g context before each request."""
    user_id = session.get('user_id')
    # Use db.session.get for optimized primary key lookup
    g.current_user = db.session.get(User, user_id) if user_id else None

@app.before_request
def make_session_permanent():
    """Ensure sessions are permanent based on config."""
    session.permanent = app.config['SESSION_PERMANENT']
    # No need for session.modified = True on every request unless modifying session

# --- Helper Functions for Responses ---
def handle_error(message, category="error", redirect_url_name='index', is_json=None):
    """Flashes an error message and redirects, or returns JSON."""
    is_json_request = is_json if is_json is not None else request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html
    if is_json_request:
        return jsonify({"status": "error", "message": message}), 400 # Bad Request is common
    else:
        flash(message, category)
        return redirect(url_for(redirect_url_name))

def handle_success(message, redirect_url=None, redirect_url_name='index', is_json=None):
    """Flashes a success message and redirects, or returns JSON."""
    is_json_request = is_json if is_json is not None else request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html
    redirect_target = redirect_url or url_for(redirect_url_name)
    if is_json_request:
        # Include redirect_url in JSON response for JS handling
        return jsonify({"status": "success", "message": message, "redirect_url": redirect_target}), 200 # OK
    else:
        flash(message, "success")
        return redirect(redirect_target)

##############
def update_leaderboards():

    # query scores table to sum scores for each group

    project_scores = db.session.query(Projects.project_name,
                                      func.sum(Scores.score_given).label('tot')
                                      ).join(Projects).group_by(Projects.project_name).all()
    print(project_scores)

    # sqlalchemy queries return tuples, but redis can only accept dicts, this line casts the data to
    # a format readable by redis
    score_mapping = {project_name: tot for project_name, tot in project_scores}

    # assign name to sorted set
    redis_key_name = 'Scoreboard'

    # iterate through scores dict and upload each team, ZADD() overwrites score value if group name is already inside
    # instead of incrementing it
    for item in score_mapping:
        r.zadd(redis_key_name, score_mapping)
        print('Score uploaded to Redis!')

    # functionality to pull scores back from redis server
    projects_ranked = r.zrevrange(redis_key_name, 0, -1, withscores=True)

    # redis stores info as bytes, need to convert name back to string. bing bang boom
    for project_bytes, score in projects_ranked:
        project_name = project_bytes.decode('utf-8')
        print(f'Project: {project_name}, Score: {score}')

    return


##############

# --- Routes ---

@app.route('/')
def index():
    """Home page route."""
    featured_projects = None
    # Show featured projects only to logged-in judges or admins
    if g.current_user and g.current_user.role in ['judge', 'admin']:
        # Simple example: Show first 3 projects. Refine logic as needed.
        featured_projects = Projects.query.order_by(Projects.project_name).limit(3).all()
    return render_template('index.html', featured_projects=featured_projects)

@app.route('/about')
def about():
    """About Us page."""
    return render_template('about_us.html')

@app.route('/audience')
@login_required # Audience features likely require login
def audience():
    """Audience interaction page (placeholder if JS handles data)."""
    return render_template('audience.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    """Contact Us page with form handling."""
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        message = request.form.get('message')
        # Basic validation
        if not name or not email or not message:
             flash('Please fill out all fields.', 'error')
             return render_template('contact_us.html') # Re-render form with error

        # --- Placeholder for contact logic (e.g., send email) ---
        print(f"Contact form submission: Name={name}, Email={email}, Message={message}")
        # --- End Placeholder ---

        flash('Thank you for your message! We will get back to you soon.', 'success')
        return redirect(url_for('contact')) # Redirect after POST
    # GET request
    return render_template('contact_us.html')

@app.route('/profile')
@login_required
def profile():
    """User profile page."""
    # User object (g.current_user) is already available via context processor
    return render_template('profile.html', user=g.current_user)

# --- Authentication Routes ---

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """User signup route."""
    if g.current_user: # Redirect if already logged in
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Expect JSON for signup POST, based on original structure
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Invalid request format. Expecting JSON."}), 400

        email = data.get('email')
        password = data.get('password')
        confirm_password = data.get('confirm_password')
        name = data.get('name', '').strip()

        # --- Server-Side Validation ---
        errors = []
        if not all([email, password, confirm_password, name]):
            errors.append("All fields (Name, Email, Password, Confirm Password) are required.")
        if password != confirm_password:
            errors.append("Passwords do not match.")

        # Password complexity (mirroring JS if possible, but essential backend check)
        if len(password or '') < 12: errors.append("Password must be at least 12 characters long.")
        if not re.search(r"[A-Z]", password or ''): errors.append("Password must contain at least one uppercase letter.")
        if not re.search(r"[a-z]", password or ''): errors.append("Password must contain at least one lowercase letter.")
        if not re.search(r"[0-9]", password or ''): errors.append("Password must contain at least one number.")
        if not re.search(r"[!@#$%^&*()_+=\-{}\[\]:;\"'|\\<>,.?/~`]", password or ''): errors.append("Password must contain at least one symbol.")

        if errors:
            # Return validation errors as JSON
            return jsonify({"status": "error", "message": " ".join(errors)}), 400
        # --- End Server-Side Validation ---

        # Check if email already exists
        if User.query.filter_by(email=email).first():
            return jsonify({"status": "error", "message": "Email already registered."}), 409 # Conflict

        try:
            # Create user with 'user' role by default.
            new_user = User(email=email, name=name, role='user')
            new_user.set_password(password) # Hash password
            db.session.add(new_user)
            db.session.commit()

            # Return success JSON for AJAX request
            return jsonify({"status": "success", "message": "Account created successfully! Please log in.", "redirect_url": url_for('login')}), 201 # Created

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error during signup for {email}: {e}") # Log the actual error
            return jsonify({"status": "error", "message": "An error occurred during signup. Please try again."}), 500

    # GET request - Render the HTML template
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login route."""
    if g.current_user: # Redirect if already logged in
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Expect JSON for login POST
        data = request.get_json()
        if not data:
             return jsonify({"status": "error", "message": "Invalid request format. Expecting JSON."}), 400

        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            return jsonify({"status": "error", "message": "Email and password are required."}), 400

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            session.clear() # Clear old session data for security
            session['user_id'] = user.id
            session.permanent = True # Make session permanent as configured

            # Determine redirect based on role, checking stored 'next_url' first
            next_url = session.pop('next_url', None) # Get and remove the stored URL
            if next_url:
                 redirect_url = next_url
            elif user.role == 'admin':
                redirect_url = url_for('admin_dashboard')
            elif user.role == 'judge':
                redirect_url = url_for('vote_casting')
            else: # Default 'user' role
                redirect_url = url_for('index')

            return jsonify({"status": "success", "message": "Login successful!", "redirect_url": redirect_url}), 200
        else:
            # Keep error message generic to prevent user enumeration
            return jsonify({"status": "error", "message": "Invalid email or password."}), 401 # Unauthorized

    # GET request
    return render_template('login.html')

@app.route('/logout')
@login_required # Must be logged in to log out
def logout():
    """User logout route."""
    session.clear() # Clear all session data
    flash("You have been successfully logged out.", "success")
    return redirect(url_for('index'))

# --- User Profile Actions ---

@app.route('/update_name', methods=['POST'])
@login_required
def update_name():
    """API endpoint for logged-in user to update their name."""
    if not request.is_json:
        return jsonify({'status': 'error', 'message': 'Request must be JSON.'}), 415

    data = request.get_json()
    new_name = data.get('name', '').strip()

    if not new_name:
        return jsonify({'status': 'error', 'message': 'Name cannot be empty.'}), 400

    user = g.current_user
    try:
        user.name = new_name
        db.session.commit()
        app.logger.info(f"User {user.id} updated name to '{new_name}'")
        return jsonify({'status': 'success', 'message': 'Name updated successfully.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating name for user {user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'An error occurred while updating name.'}), 500

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    """API endpoint for logged-in user to change their password."""
    if not request.is_json:
        return jsonify({'status': 'error', 'message': 'Request must be JSON.'}), 415

    data = request.get_json()
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    confirm_password = data.get('confirm_password')

    user = g.current_user

    if not all([current_password, new_password, confirm_password]):
        return jsonify({'status': 'error', 'message': 'All password fields are required.'}), 400

    if not user.check_password(current_password):
        return jsonify({'status': 'error', 'message': 'Incorrect current password.'}), 401 # Unauthorized

    if new_password != confirm_password:
        return jsonify({'status': 'error', 'message': 'New passwords do not match.'}), 400

    # --- Password Strength Validation ---
    errors = []
    if len(new_password) < 12: errors.append("Password must be at least 12 characters long.")
    if not re.search(r"[A-Z]", new_password): errors.append("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", new_password): errors.append("Password must contain at least one lowercase letter.")
    if not re.search(r"[0-9]", new_password): errors.append("Password must contain at least one number.")
    if not re.search(r"[!@#$%^&*()_+=\-{}\[\]:;\"'|\\<>,.?/~`]", new_password): errors.append("Password must contain at least one symbol.")
    if errors:
        return jsonify({'status': 'error', 'message': "Password validation failed: " + " ".join(errors)}), 400
    # --- End Validation ---

    try:
        user.set_password(new_password) # Hash and set the new password
        db.session.commit()
        app.logger.info(f"User {user.id} successfully changed their password.")
        # Optionally, log the user out after password change for security:
        # session.clear()
        # return jsonify({'status': 'success', 'message': 'Password changed successfully. Please log in again.'}), 200
        return jsonify({'status': 'success', 'message': 'Password changed successfully.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error changing password for user {user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'An error occurred while changing the password.'}), 500

# --- Password Reset Routes ---

# IMPORTANT: Email Sending Simulation - Replace with actual email logic in production!
def send_password_reset_email(user_email, reset_link):
    """Simulates sending a password reset email. Replace with actual email sending."""
    print("="*60)
    print("SIMULATING PASSWORD RESET EMAIL (Replace with actual sending logic)")
    print(f"To: {user_email}")
    print("Subject: Reset Your OwlJudge Password")
    print("\nBody:")
    print(f"Someone (hopefully you) requested a password reset for your OwlJudge account.")
    print(f"Click the link below to set a new password. This link is valid for 1 hour.")
    print(f"\n{reset_link}\n")
    print("If you did not request this, please ignore this email.")
    print("="*60)
    # Example using Flask-Mail (requires setup):
    # from flask_mail import Message
    # from extensions import mail # Assuming mail = Mail(app) is setup
    # try:
    #     msg = Message('Reset Your OwlJudge Password',
    #                   sender=app.config['MAIL_DEFAULT_SENDER'], # Configure in app.config
    #                   recipients=[user_email])
    #     msg.body = f'''To reset your password, visit the following link (valid for 1 hour):
    # {reset_link}
    #
    # If you did not make this request then simply ignore this email and no changes will be made.
    # '''
    #     mail.send(msg)
    #     app.logger.info(f"Password reset email sent to {user_email}")
    # except Exception as e:
    #     app.logger.error(f"Failed to send password reset email to {user_email}: {e}")
    #     # Decide if you want to bubble up the error or just log it

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    """Page for requesting a password reset link."""
    if g.current_user: # Redirect if already logged in
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email')
        if not email:
            flash('Please enter your email address.', 'warning')
            return redirect(url_for('forgot_password'))

        user = User.query.filter_by(email=email).first()

        # SECURITY: Always show the same generic message whether the user exists or not.
        message = 'If an account with that email exists, a password reset link has been sent. Please check your inbox (and spam folder).'

        if user:
            try:
                token = user.generate_reset_token()
                db.session.commit() # Commit token and expiration to DB *before* sending email
                reset_url = url_for('reset_password_with_token', token=token, _external=True) # Generate full URL
                send_password_reset_email(user.email, reset_url) # Send email (simulated)
                app.logger.info(f"Generated password reset token for user {user.id} ({user.email})")
            except Exception as e:
                 db.session.rollback()
                 app.logger.error(f"Error processing password reset request for {email}: {e}")
                 # Still show the generic success message to the user for security.

        flash(message, 'info')
        return redirect(url_for('login')) # Redirect to login page after request

    # GET request
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password_with_token(token):
    """Page for resetting password using a token from email."""
    if g.current_user: # Redirect if already logged in
        return redirect(url_for('index'))

    # Find user by token AND validate it (checks expiration automatically)
    user = User.query.filter_by(reset_token=token).first()

    # Check if user exists and token is valid using the model method
    if not user or not user.is_reset_token_valid(token):
        flash('The password reset link is invalid or has expired. Please request a new one.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not new_password or not confirm_password:
             flash('Both password fields are required.', 'warning')
             return render_template('reset_password.html', token=token) # Re-render with token

        if new_password != confirm_password:
            flash('Passwords do not match.', 'warning')
            return render_template('reset_password.html', token=token)

        # --- Password Strength Validation ---
        errors = []
        if len(new_password) < 12: errors.append("Password must be at least 12 characters long.")
        if not re.search(r"[A-Z]", new_password): errors.append("Password must contain at least one uppercase letter.")
        # ... add other rules (lowercase, number, symbol) ...
        if errors:
            flash("Password validation failed: " + " ".join(errors), 'warning')
            return render_template('reset_password.html', token=token)
        # --- End Validation ---

        try:
            user.set_password(new_password) # Set the new password
            user.invalidate_reset_token() # Crucial: Invalidate the token after successful use
            db.session.commit()
            app.logger.info(f"User {user.id} successfully reset password using token.")
            flash('Your password has been successfully reset! You can now log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error resetting password for user {user.id} with token {token}: {e}")
            flash('An error occurred while resetting your password. Please try again.', 'danger')
            return render_template('reset_password.html', token=token) # Re-render form on error

    # GET request: Show the password reset form
    return render_template('reset_password.html', token=token)


# --- Judge Role Request ---
@app.route('/request_judge_role', methods=['POST'])
@login_required # Must be logged in
def request_judge_role():
    """API endpoint for a user to request promotion to judge role."""
    user = g.current_user

    if user.role != 'user':
        return jsonify({'status': 'info', 'message': f'Your current role ({user.role}) does not require a request.'}), 403 # Forbidden/Info

    if user.judge_request_pending:
        return jsonify({'status': 'info', 'message': 'You have already submitted a request to become a judge.'}), 409 # Conflict/Info

    try:
        user.judge_request_pending = True
        db.session.commit()
        app.logger.info(f"User {user.id} ({user.email}) requested judge role.")
        # In a real system, trigger an email notification to admin here
        return jsonify({'status': 'success', 'message': 'Your request to become a judge has been submitted. An administrator will review it.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error processing judge role request for user {user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'An error occurred while submitting your request. Please try again.'}), 500

# --- Judge Voting Routes ---

@app.route('/vote')
@roles_required(['judge', 'admin']) # Judges and Admins can access vote casting
def vote_casting():
    """Page for judges/admins to view projects and cast/edit votes."""
    projects_with_status = []
    all_projects = Projects.query.order_by(Projects.project_name).all()
    judge_id = g.current_user.id

    for project in all_projects:
        # Efficiently check if any score exists for this judge/project combination
        has_voted = db.session.query(
            Scores.query.filter(
                Scores.project_id == project.project_id,
                Scores.judge_id == judge_id
            ).exists()
        ).scalar()
        projects_with_status.append({
            'project_id': project.project_id,
            'project_name': project.project_name,
            'group_id': project.group_id,
            'description': project.description, # Pass description too
            'has_voted': has_voted
        })

    return render_template('vote_casting.html', projects=projects_with_status)

@app.route('/get_scores/<int:project_id>', methods=['GET'])
@roles_required(['judge', 'admin'])
def get_scores(project_id):
    """API endpoint for a judge/admin to get their previously submitted scores for a project."""
    scores = Scores.query.filter_by(project_id=project_id, judge_id=g.current_user.id).all()
    # Return scores in a simple dictionary format {category: score}
    scores_dict = {score.category: score.score_given for score in scores}
    return jsonify(scores_dict), 200

@app.route('/submit_vote', methods=['POST'])
@roles_required(['judge', 'admin'])
def submit_vote():
    """API endpoint for a judge/admin to submit or update their scores for a project."""
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'Invalid request format. Expecting JSON.'}), 400

    project_id = data.get('project_id')
    scores_data = data.get('scores') # Expecting {'category_name': score_value, ...}

    if not project_id or not scores_data or not isinstance(scores_data, dict):
        return jsonify({'status': 'error', 'message': 'Missing project_id or scores data.'}), 400

    project = db.session.get(Projects, project_id)
    if not project:
        return jsonify({'status': 'error', 'message': 'Project not found.'}), 404

    judge_id = g.current_user.id





    try:
        # Validate all scores first
        validated_scores = {}
        for category, score_value in scores_data.items():
            category = category.strip() # Clean category name
            if not category:
                 return jsonify({'status': 'error', 'message': "Score category cannot be empty."}), 400
            try:
                score = int(score_value)
                # Define score range (e.g., 1 to 100) - make this configurable?
                MIN_SCORE = 1
                MAX_SCORE = 100
                if not MIN_SCORE <= score <= MAX_SCORE:
                     raise ValueError(f"Score for '{category}' must be between {MIN_SCORE} and {MAX_SCORE}.")
                validated_scores[category] = score
            except (ValueError, TypeError):
                 return jsonify({'status': 'error', 'message': f"Invalid score value '{score_value}' for category '{category}'. Must be a whole number between {MIN_SCORE} and {MAX_SCORE}."}), 400


        # Process validated scores (update or insert)
        for category, score in validated_scores.items():
            existing_score = Scores.query.filter_by(
                project_id=project_id,
                judge_id=judge_id,
                category=category
            ).first()

            if existing_score:
                if existing_score.score_given != score: # Only update if changed
                    existing_score.score_given = score
                    existing_score.timestamp = datetime.utcnow()
            else:
                new_score = Scores(
                    project_id=project_id,
                    judge_id=judge_id,
                    category=category,
                    score_given=score
                    # timestamp defaults to utcnow
                )



                db.session.add(new_score)

        db.session.commit()
        app.logger.info(f"Judge {judge_id} submitted/updated votes for project {project_id}")

        ###
        update_leaderboards()
        ###

        return jsonify({'status': 'success', 'message': f'Votes for {project.project_name} submitted successfully.'}), 200

    except ValueError as ve: # Catch specific validation error from score range check
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error submitting vote for project {project_id} by judge {judge_id}: {e}")
        return jsonify({'status': 'error', 'message': 'An internal error occurred while submitting votes.'}), 500



# --- Admin Routes ---

@app.route('/admin/dashboard')
@role_required('admin')
def admin_dashboard():
    """Admin dashboard page showing users, projects, scores, and pending requests."""
    try:
        # Fetch data using efficient queries
        # Use joinedload to pre-load related project/judge data for scores
        users_obj = User.query.order_by(User.name).all()
        projects_obj = Projects.query.order_by(Projects.project_name).all()
        scores_obj = db.session.query(Scores).options(
            db.joinedload(Scores.project),
            db.joinedload(Scores.judge)
        ).order_by(Scores.timestamp.desc()).all()

        # Convert objects to lists of dictionaries suitable for template/JSON
        users_list = [{
            'id': u.id, 'email': u.email, 'name': u.name, 'role': u.role,
            'judge_request_pending': u.judge_request_pending # Crucial for pending table
            } for u in users_obj]

        projects_list = [{
            'project_id': p.project_id, 'project_name': p.project_name, 'group_id': p.group_id,
            'description': p.description
            } for p in projects_obj]

        scores_list = [{
            'score_id': s.score_id, 'category': s.category, 'score_given': s.score_given,
            'project_id': s.project_id, 'judge_id': s.judge_id,
            'timestamp': s.timestamp.isoformat() if s.timestamp else None, # Use ISO format for consistency
            'project_name': s.project.project_name if s.project else 'N/A',
            'judge_name': s.judge.name if s.judge else 'N/A'
            } for s in scores_obj]

        return render_template('admin_dashboard.html',
                               users=users_list,
                               projects=projects_list,
                               scores=scores_list)
    except Exception as e:
        app.logger.error(f"Error loading admin dashboard: {e}")
        flash("Error loading dashboard data. Please try again.", "error")
        return redirect(url_for('index')) # Redirect on error


@app.route('/admin/approve_judge/<int:user_id>', methods=['POST'])
@role_required('admin')
def approve_judge_role(user_id):
    """API endpoint for admin to approve a user's request to become a judge."""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found.'}), 404

    if not user.judge_request_pending:
        return jsonify({'status': 'info', 'message': 'User does not have a pending request.'}), 400

    if user.role != 'user': # Safety check: Only promote 'user' role
         user.judge_request_pending = False # Clear flag if they are already judge/admin
         db.session.commit()
         return jsonify({'status': 'info', 'message': f'User is already a {user.role}. Request flag cleared.'}), 200

    try:
        user.role = 'judge'
        user.judge_request_pending = False # Clear the flag
        db.session.commit()
        app.logger.info(f"Admin {g.current_user.id} approved judge role for user {user.id}")
        # Return updated user data for potential UI update
        updated_user_data = { 'id': user.id, 'email': user.email, 'name': user.name, 'role': user.role, 'judge_request_pending': user.judge_request_pending }
        return jsonify({ 'status': 'success', 'message': f'"{user.name}" has been promoted to Judge.', 'user': updated_user_data }), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error approving judge role for user {user_id}: {e}")
        return jsonify({'status': 'error', 'message': 'Internal server error occurred while approving the role.'}), 500

# --- Admin CRUD Operations (Users) ---

@app.route('/admin/users', methods=['POST'])
@role_required('admin')
def add_user():
    """API endpoint for admin to add a new user."""
    data = request.get_json()
    required = ['name', 'email', 'password', 'role']
    if not data or not all(k in data for k in required):
        return jsonify({'status': 'error', 'message': 'Missing required fields: name, email, password, role.'}), 400

    role = data.get('role', 'user').lower() # Default to user, ensure lowercase
    if role not in ['admin', 'judge', 'user']:
        return jsonify({'status': 'error', 'message': 'Invalid role specified. Must be admin, judge, or user.'}), 400

    if User.query.filter_by(email=data['email']).first():
        return jsonify({'status': 'error', 'message': 'Email already registered.'}), 409 # Conflict

    try:
        new_user = User(email=data['email'], name=data['name'], role=role)
        new_user.set_password(data['password']) # Hashes password
        # judge_request_pending defaults to False in model
        db.session.add(new_user)
        db.session.commit()
        app.logger.info(f"Admin {g.current_user.id} added user {new_user.id} ({new_user.email})")
        # Return the newly created user data
        user_data = {'id': new_user.id, 'email': new_user.email, 'name': new_user.name, 'role': new_user.role, 'judge_request_pending': new_user.judge_request_pending}
        return jsonify({'status': 'success', 'message': 'User added successfully.', 'user': user_data}), 201 # Created
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error adding user via admin: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to add user due to an internal error.'}), 500

@app.route('/admin/users/<int:user_id>', methods=['PUT'])
@role_required('admin')
def update_user(user_id):
    """API endpoint for admin to update an existing user."""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found.'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided for update.'}), 400

    try:
        updated = False
        # Update email if provided and different, checking for uniqueness
        if 'email' in data and data['email'] != user.email:
            if User.query.filter(User.email == data['email'], User.id != user_id).first():
                return jsonify({'status': 'error', 'message': 'Email address is already in use by another user.'}), 409
            user.email = data['email']
            updated = True

        # Update name if provided
        if 'name' in data and data['name'] != user.name:
            user.name = data['name']
            updated = True

        # Update role if provided and valid
        if 'role' in data and data['role'] != user.role:
            new_role = data['role'].lower()
            if new_role not in ['admin', 'judge', 'user']:
                return jsonify({'status': 'error', 'message': 'Invalid role specified.'}), 400
            user.role = new_role
            # If role changes, maybe clear pending flag? Optional logic.
            # user.judge_request_pending = False
            updated = True

        # Update password if provided (non-empty)
        if 'password' in data and data['password']:
            user.set_password(data['password'])
            updated = True

        # Admin should generally NOT manually change 'judge_request_pending' via this PUT.
        # It's managed by the user request and the admin approval route.

        if updated:
            db.session.commit()
            app.logger.info(f"Admin {g.current_user.id} updated user {user_id}")
            # Return the updated user data
            user_data = {'id': user.id, 'email': user.email, 'name': user.name, 'role': user.role, 'judge_request_pending': user.judge_request_pending}
            return jsonify({'status': 'success', 'message': 'User updated successfully.', 'user': user_data}), 200
        else:
             return jsonify({'status': 'info', 'message': 'No changes detected or applied.'}), 200 # Or 304 Not Modified

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating user {user_id} by admin {g.current_user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to update user due to an internal error.'}), 500

@app.route('/admin/users/<int:user_id>', methods=['DELETE'])
@role_required('admin')
def delete_user(user_id):
    """API endpoint for admin to delete a user."""
    # Prevent admin from deleting their own account via this endpoint
    if g.current_user.id == user_id:
        return jsonify({'status': 'error', 'message': 'Cannot delete your own account using this function.'}), 403 # Forbidden

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found.'}), 404

    try:
        # Check for dependencies: Does this user (as a judge) have scores?
        # Using lazy='dynamic' on the relationship makes this efficient
        if user.judge_scores.count() > 0:
             return jsonify({'status': 'error', 'message': 'Cannot delete user: They have existing scores recorded as a judge. Please reassign or delete scores first.'}), 409 # Conflict

        # Add other dependency checks if necessary (e.g., if users could own projects)

        db.session.delete(user)
        db.session.commit()
        app.logger.info(f"Admin {g.current_user.id} deleted user {user_id} ({user.email})")
        return jsonify({'status': 'success', 'message': 'User deleted successfully.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting user {user_id} by admin {g.current_user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to delete user due to an internal error.'}), 500


# --- Admin CRUD Operations (Projects) ---

@app.route('/admin/projects', methods=['POST'])
@role_required('admin')
def add_project():
    """API endpoint for admin to add a new project."""
    data = request.get_json()
    if not data or not data.get('project_name') or data.get('group_id') is None: # Check presence and potentially empty strings/null
        return jsonify({'status': 'error', 'message': 'Missing required fields: project_name, group_id.'}), 400

    try:
        group_id = int(data['group_id']) # Validate group_id is integer
        project_name = data['project_name'].strip()
        if not project_name:
             return jsonify({'status': 'error', 'message': 'Project name cannot be empty.'}), 400

        # Optional: Check for duplicate project name/group ID combo if needed
        # existing = Projects.query.filter_by(project_name=project_name, group_id=group_id).first()
        # if existing: return jsonify({'status': 'error', 'message': 'Project with same name and group ID already exists.'}), 409

        new_project = Projects(
            project_name=project_name,
            group_id=group_id,
            description=data.get('description', '').strip() # Optional description
        )
        db.session.add(new_project)
        db.session.commit()
        app.logger.info(f"Admin {g.current_user.id} added project {new_project.project_id} ('{new_project.project_name}')")
        # Return newly created project data
        project_data = {
            'project_id': new_project.project_id, 'project_name': new_project.project_name,
            'group_id': new_project.group_id, 'description': new_project.description
        }
        return jsonify({'status': 'success', 'message': 'Project added successfully.', 'project': project_data}), 201 # Created
    except ValueError:
         return jsonify({'status': 'error', 'message': 'Group ID must be a whole number.'}), 400
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error adding project via admin: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to add project due to an internal error.'}), 500

@app.route('/admin/projects/<int:project_id>', methods=['PUT'])
@role_required('admin')
def update_project(project_id):
    """API endpoint for admin to update an existing project."""
    project = db.session.get(Projects, project_id)
    if not project:
        return jsonify({'status': 'error', 'message': 'Project not found.'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided for update.'}), 400

    try:
        updated = False
        if 'project_name' in data:
            new_name = data['project_name'].strip()
            if not new_name: return jsonify({'status': 'error', 'message': 'Project name cannot be empty.'}), 400
            if new_name != project.project_name:
                 project.project_name = new_name
                 updated = True
        if 'group_id' in data:
            try:
                new_group_id = int(data['group_id'])
                if new_group_id != project.group_id:
                     project.group_id = new_group_id
                     updated = True
            except ValueError:
                return jsonify({'status': 'error', 'message': 'Group ID must be a whole number.'}), 400
        # Update description (allow empty string to clear it)
        if 'description' in data:
             new_desc = data['description'].strip()
             if new_desc != project.description: # Handle None vs empty string comparison if needed
                 project.description = new_desc if new_desc else None # Store None if empty string? Or empty string? Be consistent.
                 updated = True

        if updated:
            db.session.commit()
            app.logger.info(f"Admin {g.current_user.id} updated project {project_id}")
            project_data = {
                'project_id': project.project_id, 'project_name': project.project_name,
                'group_id': project.group_id, 'description': project.description
            }
            return jsonify({'status': 'success', 'message': 'Project updated successfully.', 'project': project_data}), 200
        else:
            return jsonify({'status': 'info', 'message': 'No changes detected or applied.'}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating project {project_id} by admin {g.current_user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to update project due to an internal error.'}), 500

@app.route('/admin/projects/<int:project_id>', methods=['DELETE'])
@role_required('admin')
def delete_project(project_id):
    """API endpoint for admin to delete a project."""
    project = db.session.get(Projects, project_id)
    if not project:
        return jsonify({'status': 'error', 'message': 'Project not found.'}), 404

    try:
        # Scores associated with this project will be deleted automatically due to:
        # cascade="all, delete-orphan" on the Projects.scores relationship
        # and ondelete='CASCADE' on the Scores.project_id ForeignKey (belt and suspenders)
        project_name = project.project_name # Get name for logging before deletion
        db.session.delete(project)
        db.session.commit()
        app.logger.info(f"Admin {g.current_user.id} deleted project {project_id} ('{project_name}') and its associated scores.")
        return jsonify({'status': 'success', 'message': 'Project and associated scores deleted successfully.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting project {project_id} by admin {g.current_user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to delete project due to an internal error.'}), 500

# --- Admin CRUD Operations (Scores) ---
# Note: Direct score manipulation by admin should be used cautiously (e.g., for corrections).

@app.route('/admin/scores', methods=['POST'])
@role_required('admin')
def add_score():
    """API endpoint for admin to manually add a score (use with caution)."""
    data = request.get_json()
    required = ['category', 'score_given', 'project_id', 'judge_id']
    if not data or not all(k in data for k in required):
        return jsonify({'status': 'error', 'message': 'Missing required fields: category, score_given, project_id, judge_id.'}), 400

    try:
        category = data['category'].strip()
        score_given = int(data['score_given'])
        project_id = int(data['project_id'])
        judge_id = int(data['judge_id'])

        if not category:
            return jsonify({'status': 'error', 'message': 'Score category cannot be empty.'}), 400

        # Validate score range (consistent with submit_vote)
        MIN_SCORE = 1
        MAX_SCORE = 100
        if not MIN_SCORE <= score_given <= MAX_SCORE:
             return jsonify({'status': 'error', 'message': f'Score must be between {MIN_SCORE} and {MAX_SCORE}.'}), 400

        # Check if project and judge exist
        project = db.session.get(Projects, project_id)
        judge = db.session.get(User, judge_id)
        if not project: return jsonify({'status': 'error', 'message': 'Project not found.'}), 404
        if not judge: return jsonify({'status': 'error', 'message': 'Judge (User) not found.'}), 404
        # Ensure the selected user is actually a judge or admin (who can also vote)
        if judge.role not in ['judge', 'admin']:
            return jsonify({'status': 'error', 'message': 'Selected user does not have judge or admin role.'}), 400

        # Check for existing score (unique constraint)
        existing_score = Scores.query.filter_by(category=category, project_id=project_id, judge_id=judge_id).first()
        if existing_score:
            return jsonify({'status': 'error', 'message': 'A score for this category, project, and judge already exists. Use PUT to update if needed.'}), 409 # Conflict

        new_score = Scores(
            category=category, score_given=score_given,
            project_id=project_id, judge_id=judge_id
        )
        db.session.add(new_score)
        db.session.commit()
        app.logger.info(f"Admin {g.current_user.id} manually added score {new_score.score_id} (Proj:{project_id}, Judge:{judge_id}, Cat:{category})")

        # Return the newly created score data including related names
        score_data = {
            'score_id': new_score.score_id, 'category': new_score.category, 'score_given': new_score.score_given,
            'project_id': new_score.project_id, 'judge_id': new_score.judge_id,
            'project_name': project.project_name, 'judge_name': judge.name,
            'timestamp': new_score.timestamp.isoformat()
        }
        return jsonify({'status': 'success', 'message': 'Score added successfully.', 'score': score_data}), 201 # Created

    except ValueError:
        return jsonify({'status': 'error', 'message': 'Score, Project ID, and Judge ID must be valid numbers.'}), 400
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error adding score via admin: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to add score due to an internal error.'}), 500

@app.route('/admin/scores/<int:score_id>', methods=['PUT'])
@role_required('admin')
def update_score(score_id):
    """API endpoint for admin to update an existing score (use with caution)."""
    score = db.session.get(Scores, score_id)
    if not score:
        return jsonify({'status': 'error', 'message': 'Score not found.'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided for update.'}), 400

    try:
        updated = False
        original_tuple = (score.project_id, score.judge_id, score.category) # For unique check later

        # Update fields if provided
        if 'category' in data:
            new_cat = data['category'].strip()
            if not new_cat: return jsonify({'status': 'error', 'message': 'Score category cannot be empty.'}), 400
            if new_cat != score.category:
                score.category = new_cat
                updated = True
        if 'score_given' in data:
            try:
                new_score_val = int(data['score_given'])
                MIN_SCORE = 1
                MAX_SCORE = 100
                if not MIN_SCORE <= new_score_val <= MAX_SCORE:
                     return jsonify({'status': 'error', 'message': f'Score must be between {MIN_SCORE} and {MAX_SCORE}.'}), 400
                if new_score_val != score.score_given:
                    score.score_given = new_score_val
                    updated = True
            except ValueError:
                return jsonify({'status': 'error', 'message': 'Score must be a whole number.'}), 400
        if 'project_id' in data:
             try:
                 new_proj_id = int(data['project_id'])
                 if new_proj_id != score.project_id:
                     # Check if new project exists
                     if not db.session.get(Projects, new_proj_id):
                         return jsonify({'status': 'error', 'message': 'Target Project not found.'}), 404
                     score.project_id = new_proj_id
                     updated = True
             except ValueError:
                 return jsonify({'status': 'error', 'message': 'Project ID must be a number.'}), 400
        if 'judge_id' in data:
            try:
                new_judge_id = int(data['judge_id'])
                if new_judge_id != score.judge_id:
                    # Check if new judge exists and has correct role
                    judge = db.session.get(User, new_judge_id)
                    if not judge: return jsonify({'status': 'error', 'message': 'Target Judge (User) not found.'}), 404
                    if judge.role not in ['judge', 'admin']: return jsonify({'status': 'error', 'message': 'Target user does not have judge or admin role.'}), 400
                    score.judge_id = new_judge_id
                    updated = True
            except ValueError:
                 return jsonify({'status': 'error', 'message': 'Judge ID must be a number.'}), 400

        if updated:
            # Check for potential unique constraint violation BEFORE commit if combination changed
            new_tuple = (score.project_id, score.judge_id, score.category)
            if new_tuple != original_tuple:
                 existing = Scores.query.filter(
                     Scores.project_id == score.project_id,
                     Scores.judge_id == score.judge_id,
                     Scores.category == score.category,
                     Scores.score_id != score_id # Exclude self
                 ).first()
                 if existing:
                     # Revert changes to avoid DB error? Or just report error? Reporting is simpler.
                     return jsonify({'status': 'error', 'message': 'Updating score would create a duplicate entry for this project, judge, and category combination.'}), 409

            score.timestamp = datetime.utcnow() # Update timestamp on any change
            db.session.commit()
            app.logger.info(f"Admin {g.current_user.id} updated score {score_id}")

            # Re-fetch related names after commit, in case project/judge changed
            db.session.refresh(score) # Ensure relationship attributes are updated
            score_data = {
                'score_id': score.score_id, 'category': score.category, 'score_given': score.score_given,
                'project_id': score.project_id, 'judge_id': score.judge_id,
                'project_name': score.project.project_name if score.project else 'N/A',
                'judge_name': score.judge.name if score.judge else 'N/A',
                'timestamp': score.timestamp.isoformat()
            }
            return jsonify({'status': 'success', 'message': 'Score updated successfully.', 'score': score_data}), 200
        else:
            return jsonify({'status': 'info', 'message': 'No changes detected or applied.'}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating score {score_id} by admin {g.current_user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to update score due to an internal error.'}), 500

@app.route('/admin/scores/<int:score_id>', methods=['DELETE'])
@role_required('admin')
def delete_score(score_id):
    """API endpoint for admin to delete a specific score."""
    score = db.session.get(Scores, score_id)
    if not score:
        return jsonify({'status': 'error', 'message': 'Score not found.'}), 404

    try:
        db.session.delete(score)
        db.session.commit()
        app.logger.info(f"Admin {g.current_user.id} deleted score {score_id}")
        return jsonify({'status': 'success', 'message': 'Score deleted successfully.'}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting score {score_id} by admin {g.current_user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to delete score due to an internal error.'}), 500

# --- Admin Data Export/Import ---

# Check if pandas is available for export/import routes
if pd is 1:
    app.logger.warning("Pandas library not found. Excel export/import features will be disabled.")

    # Define dummy routes if pandas is not installed
    @app.route('/admin/export/<path:export_type>')
    @role_required('admin')
    def export_disabled(export_type):
        flash("Excel export functionality requires the 'pandas' library to be installed.", "error")
        return redirect(url_for('admin_dashboard'))

    @app.route('/admin/import/<path:import_type>', methods=['POST'])
    @role_required('admin')
    def import_disabled(import_type):
        return jsonify({'status': 'error', 'message': "Excel import functionality requires the 'pandas' library to be installed."}), 501 # Not Implemented
else:
    # --- Export Routes (Require pandas) ---
    @app.route('/admin/export/users')
    @role_required('admin')
    def export_users():
        try:
            users = User.query.order_by(User.name).all()
            data_to_export = [{
                'id': u.id, 'name': u.name, 'email': u.email, 'role': u.role,
                'judge_request_pending': u.judge_request_pending
            } for u in users]

            if not data_to_export:
                 flash("No users found to export.", "warning")
                 return redirect(url_for('admin_dashboard'))

            df = pd.DataFrame(data_to_export)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                 df.to_excel(writer, index=False, sheet_name='Users')
            output.seek(0)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            return send_file(
                output,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name=f'owljudge_users_{timestamp}.xlsx'
            )
        except Exception as e:
            app.logger.error(f"Error exporting users: {e}")
            flash("An error occurred during user export.", "error")
            return redirect(url_for('admin_dashboard'))

    @app.route('/admin/export/projects')
    @role_required('admin')
    def export_projects():
        try:
            projects = Projects.query.order_by(Projects.project_name).all()
            data_to_export = [{
                'project_id': p.project_id, 'project_name': p.project_name, 'group_id': p.group_id,
                'description': p.description
            } for p in projects]

            if not data_to_export:
                 flash("No projects found to export.", "warning")
                 return redirect(url_for('admin_dashboard'))

            df = pd.DataFrame(data_to_export)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Projects')
            output.seek(0)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            return send_file(
                output,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name=f'owljudge_projects_{timestamp}.xlsx'
            )
        except Exception as e:
            app.logger.error(f"Error exporting projects: {e}")
            flash("An error occurred during project export.", "error")
            return redirect(url_for('admin_dashboard'))

    @app.route('/admin/export/scores')
    @role_required('admin')
    def export_scores():
        try:
            # Use joinedload for efficiency
            scores = db.session.query(Scores).options(
                db.joinedload(Scores.project),
                db.joinedload(Scores.judge)
            ).order_by(Scores.project_id, Scores.judge_id, Scores.category).all()

            data_to_export = [{
                'score_id': s.score_id, 'project_id': s.project_id,
                'project_name': s.project.project_name if s.project else 'N/A',
                'judge_id': s.judge_id,
                'judge_name': s.judge.name if s.judge else 'N/A',
                'category': s.category, 'score_given': s.score_given,
                'timestamp': s.timestamp.strftime('%Y-%m-%d %H:%M:%S') if s.timestamp else None
            } for s in scores]

            if not data_to_export:
                 flash("No scores found to export.", "warning")
                 return redirect(url_for('admin_dashboard'))

            df = pd.DataFrame(data_to_export)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Scores')
            output.seek(0)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            return send_file(
                output,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name=f'owljudge_scores_{timestamp}.xlsx'
            )
        except Exception as e:
            app.logger.error(f"Error exporting scores: {e}")
            flash("An error occurred during score export.", "error")
            return redirect(url_for('admin_dashboard'))

    # --- Import Routes (Require pandas) ---

    @app.route('/admin/import/users', methods=['POST'])
    @role_required('admin')
    def import_users():
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'message': 'No file part in the request.'}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({'status': 'error', 'message': 'No file selected.'}), 400
        if not file.filename.lower().endswith('.xlsx'):
            return jsonify({'status': 'error', 'message': 'Invalid file type. Please upload an XLSX file.'}), 400

        try:
            df = pd.read_excel(file, engine='openpyxl')
            # Expected columns (case-insensitive check)
            required_cols = {'name', 'email', 'role'} # Password required for *new* users only
            actual_cols = {col.lower().strip() for col in df.columns}
            if not required_cols.issubset(actual_cols):
                 missing = required_cols - actual_cols
                 return jsonify({'status': 'error', 'message': f'Missing required columns in Excel file: {", ".join(missing)}'}), 400

            # Convert column names to lower and strip spaces for consistent access
            df.columns = [col.lower().strip() for col in df.columns]

            errors = []
            users_to_add = []
            users_to_update = {} # Store updates by user ID to merge later
            processed_emails = set() # Track emails within the file to prevent duplicates

            for index, row in df.iterrows():
                row_num = index + 2 # Excel row number (1-based + header)
                try:
                    # Read and clean data
                    email = str(row.get('email', '')).strip()
                    name = str(row.get('name', '')).strip()
                    role = str(row.get('role', 'user')).strip().lower()
                    password = str(row.get('password', '')).strip() if 'password' in df.columns else ''
                    user_id = row.get('id') # Optional ID for updates

                    # --- Basic Row Validation ---
                    if not email or not name:
                        errors.append(f"Row {row_num}: Skipping row due to missing required name or email.")
                        continue
                    if not re.match(r"[^@]+@[^@]+\.[^@]+", email): # Simple email format check
                        errors.append(f"Row {row_num}: Skipping row due to invalid email format '{email}'.")
                        continue
                    if role not in ['user', 'judge', 'admin']:
                         errors.append(f"Row {row_num}: Skipping row due to invalid role '{role}'. Must be user, judge, or admin.")
                         continue
                    if email in processed_emails:
                         errors.append(f"Row {row_num}: Skipping row due to duplicate email '{email}' within the import file.")
                         continue
                    processed_emails.add(email)

                    # --- Determine Add vs Update ---
                    existing_user = None
                    user_id_int = None
                    if pd.notna(user_id) and user_id:
                        try:
                            user_id_int = int(user_id)
                            existing_user = db.session.get(User, user_id_int)
                            if not existing_user:
                                errors.append(f"Row {row_num}: User with specified ID {user_id_int} not found. Cannot update. Skipping row.")
                                continue
                        except ValueError:
                            errors.append(f"Row {row_num}: Invalid ID '{user_id}'. Must be a number. Skipping row.")
                            continue
                    else: # No ID provided, try finding by email for potential update or add new
                        existing_user = User.query.filter_by(email=email).first()

                    # --- Process Based on Add/Update ---
                    if existing_user:
                        # Prepare Update
                        update_data = {'name': name, 'role': role}
                        # Check for email change conflict
                        if email != existing_user.email:
                            if User.query.filter(User.email == email, User.id != existing_user.id).first():
                                errors.append(f"Row {row_num}: Cannot update user {existing_user.id}. Email '{email}' is already in use by another user. Skipping update for this row.")
                                continue
                            update_data['email'] = email
                        if password:
                            update_data['password'] = password # Store password to be hashed later

                        # Store update keyed by user ID
                        if existing_user.id not in users_to_update:
                            users_to_update[existing_user.id] = {'data': update_data, 'row_num': row_num}
                        else:
                            errors.append(f"Row {row_num}: Multiple updates specified for user ID {existing_user.id} in the file. Using first encountered update only.")

                    else:
                        # Prepare Add New User
                        if not password:
                             errors.append(f"Row {row_num}: Password is required for new user '{email}'. Skipping row.")
                             continue
                        # Check email uniqueness in DB again (though filter_by above should catch it)
                        if User.query.filter_by(email=email).first():
                             errors.append(f"Row {row_num}: Email '{email}' already exists in the database. Skipping row.")
                             continue

                        new_user_data = {'email': email, 'name': name, 'role': role, 'password': password, 'row_num': row_num}
                        users_to_add.append(new_user_data)

                except Exception as e:
                    errors.append(f"Row {row_num}: Unexpected error processing row - {e}. Skipping row.")

            # --- Perform Database Operations (Commit Once) ---
            added_count = 0
            updated_count = 0
            if not users_to_add and not users_to_update:
                 message = "User import finished. No valid users found to add or update."
                 return jsonify({'status': 'warning' if errors else 'info', 'message': message, 'errors': errors}), 200

            try:
                # Process additions
                for data in users_to_add:
                    try:
                        new_user = User(email=data['email'], name=data['name'], role=data['role'])
                        new_user.set_password(data['password'])
                        db.session.add(new_user)
                        added_count += 1
                    except Exception as e:
                        errors.append(f"Row {data['row_num']}: Error adding user '{data['email']}' - {e}")
                        db.session.rollback() # Rollback immediately on add error? Or let final commit fail? Let final fail for atomicity.
                        raise # Re-raise to abort commit

                # Process updates
                for user_id, update_info in users_to_update.items():
                    try:
                        user_to_update = db.session.get(User, user_id) # Get user within this session context
                        if not user_to_update: # Should not happen if validation above worked, but safety check
                             errors.append(f"Row {update_info['row_num']}: User ID {user_id} disappeared before update. Skipping.")
                             continue

                        data = update_info['data']
                        user_to_update.name = data['name']
                        user_to_update.role = data['role']
                        if 'email' in data: user_to_update.email = data['email']
                        if 'password' in data: user_to_update.set_password(data['password'])
                        # Merge might be safer if dealing with detached objects, but direct assignment should work here.
                        updated_count += 1
                    except Exception as e:
                        errors.append(f"Row {update_info['row_num']}: Error updating user ID {user_id} - {e}")
                        db.session.rollback()
                        raise # Re-raise to abort commit

                # Attempt final commit
                db.session.commit()
                app.logger.info(f"Admin {g.current_user.id} imported users. Added: {added_count}, Updated: {updated_count}, Errors: {len(errors)}")
                message = f"User import finished. Added: {added_count}, Updated: {updated_count}, Errors/Skipped: {len(errors)}."
                return jsonify({'status': 'success' if not errors else 'warning', 'message': message, 'errors': errors}), 200

            except Exception as e:
                 db.session.rollback() # Rollback the entire transaction if any error occurred during add/update
                 app.logger.error(f"Database error during user import commit: {e}")
                 # Add a general error message, keeping specific row errors if collected
                 errors.append(f"Database error during final commit: {e}. No changes were saved.")
                 message = f"User import failed during database operation. Added: 0, Updated: 0, Errors/Skipped: {len(errors)}."
                 return jsonify({'status': 'error', 'message': message, 'errors': errors}), 500

        except pd.errors.EmptyDataError:
            return jsonify({'status': 'error', 'message': 'The uploaded Excel file is empty.'}), 400
        except Exception as e:
            db.session.rollback() # Rollback just in case
            app.logger.error(f"Error processing user import file: {e}")
            return jsonify({'status': 'error', 'message': f'Failed to process Excel file: {e}'}), 500

    @app.route('/admin/import/projects', methods=['POST'])
    @role_required('admin')
    def import_projects():
        if 'file' not in request.files: return jsonify({'status': 'error', 'message': 'No file part.'}), 400
        file = request.files['file']
        if file.filename == '': return jsonify({'status': 'error', 'message': 'No file selected.'}), 400
        if not file.filename.lower().endswith('.xlsx'): return jsonify({'status': 'error', 'message': 'Invalid file type (XLSX only).'}), 400

        try:
            df = pd.read_excel(file, engine='openpyxl')
            required_cols = {'project_name', 'group_id'} # Description optional
            actual_cols = {col.lower().strip() for col in df.columns}
            if not required_cols.issubset(actual_cols):
                 missing = required_cols - actual_cols
                 return jsonify({'status': 'error', 'message': f'Missing required columns: {", ".join(missing)}'}), 400

            df.columns = [col.lower().strip() for col in df.columns]

            errors = []
            projects_to_add = []
            projects_to_update = {} # Keyed by project_id

            for index, row in df.iterrows():
                row_num = index + 2
                try:
                    project_name = str(row.get('project_name', '')).strip()
                    group_id_str = str(row.get('group_id', '')).strip()
                    description = str(row.get('description', '')).strip() if 'description' in df.columns else None
                    project_id = row.get('project_id') # Optional ID for updates

                    # --- Basic Row Validation ---
                    if not project_name or not group_id_str:
                        errors.append(f"Row {row_num}: Skipping row due to missing project_name or group_id.")
                        continue
                    try:
                        group_id = int(group_id_str)
                    except ValueError:
                        errors.append(f"Row {row_num}: Invalid group_id '{group_id_str}'. Must be number. Skipping row.")
                        continue

                    # --- Determine Add vs Update ---
                    existing_project = None
                    project_id_int = None
                    if pd.notna(project_id) and project_id:
                        try:
                            project_id_int = int(project_id)
                            existing_project = db.session.get(Projects, project_id_int)
                            if not existing_project:
                                errors.append(f"Row {row_num}: Project ID {project_id_int} not found. Cannot update. Skipping row.")
                                continue
                        except ValueError:
                            errors.append(f"Row {row_num}: Invalid project_id '{project_id}'. Skipping row.")
                            continue
                    else:
                        # If no ID, should we try finding by name/group? Risk of duplicates.
                        # Safest approach: Only update if ID provided, otherwise add.
                        # Check if project with same name/group already exists before adding? Optional.
                        pass # If existing_project is None, will proceed to add.

                    # --- Process ---
                    if existing_project:
                        # Prepare Update
                        update_data = {'project_name': project_name, 'group_id': group_id}
                        if description is not None: update_data['description'] = description

                        if project_id_int not in projects_to_update:
                             projects_to_update[project_id_int] = {'data': update_data, 'row_num': row_num}
                        else:
                             errors.append(f"Row {row_num}: Multiple updates for project ID {project_id_int}. Using first.")
                    else:
                        # Prepare Add
                        # Optional: Check for existing name/group combo before adding
                        # if Projects.query.filter_by(project_name=project_name, group_id=group_id).first():
                        #     errors.append(f"Row {row_num}: Project '{project_name}' with group ID {group_id} already exists. Skipping.")
                        #     continue

                        new_project_data = {
                            'project_name': project_name, 'group_id': group_id,
                            'description': description, 'row_num': row_num
                        }
                        projects_to_add.append(new_project_data)

                except Exception as e:
                    errors.append(f"Row {row_num}: Unexpected error processing row - {e}. Skipping.")

            # --- Perform Database Operations ---
            added_count = 0
            updated_count = 0
            if not projects_to_add and not projects_to_update:
                message = "Project import finished. No valid projects found to add or update."
                return jsonify({'status': 'warning' if errors else 'info', 'message': message, 'errors': errors}), 200

            try:
                # Process additions
                for data in projects_to_add:
                    try:
                        new_project = Projects(project_name=data['project_name'], group_id=data['group_id'], description=data['description'])
                        db.session.add(new_project)
                        added_count += 1
                    except Exception as e:
                        errors.append(f"Row {data['row_num']}: Error adding project '{data['project_name']}' - {e}")
                        raise # Abort commit

                # Process updates
                for proj_id, update_info in projects_to_update.items():
                    try:
                        project_to_update = db.session.get(Projects, proj_id)
                        if not project_to_update: continue # Should be caught earlier

                        data = update_info['data']
                        project_to_update.project_name = data['project_name']
                        project_to_update.group_id = data['group_id']
                        if 'description' in data: project_to_update.description = data['description']
                        updated_count += 1
                    except Exception as e:
                        errors.append(f"Row {update_info['row_num']}: Error updating project ID {proj_id} - {e}")
                        raise # Abort commit

                # Final commit
                db.session.commit()
                app.logger.info(f"Admin {g.current_user.id} imported projects. Added: {added_count}, Updated: {updated_count}, Errors: {len(errors)}")
                message = f"Project import finished. Added: {added_count}, Updated: {updated_count}, Errors/Skipped: {len(errors)}."
                return jsonify({'status': 'success' if not errors else 'warning', 'message': message, 'errors': errors}), 200

            except Exception as e:
                 db.session.rollback()
                 app.logger.error(f"Database error during project import commit: {e}")
                 errors.append(f"Database error during final commit: {e}. No changes were saved.")
                 message = f"Project import failed during database operation. Added: 0, Updated: 0, Errors/Skipped: {len(errors)}."
                 return jsonify({'status': 'error', 'message': message, 'errors': errors}), 500

        except pd.errors.EmptyDataError:
            return jsonify({'status': 'error', 'message': 'The uploaded Excel file is empty.'}), 400
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error processing project import file: {e}")
            return jsonify({'status': 'error', 'message': f'Failed to process Excel file: {e}'}), 500


# --- Utility and Error Handling ---

@app.route('/debug-session') # Example debug route - REMOVE IN PRODUCTION
def debug_session():
    """Debug route to inspect session and g.current_user. DISABLE IN PRODUCTION."""
    if not app.debug:
        return "Debug endpoint disabled", 403
    return jsonify({
        'session': dict(session),
        'g.current_user_id': g.current_user.id if g.current_user else None,
        'g.current_user_role': g.current_user.role if g.current_user else None,
    })

@app.errorhandler(404)
def page_not_found(e):
    """Custom 404 error handler."""
    # Return JSON if client primarily accepts JSON
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify(error="Not Found", message=str(e)), 404
    # Otherwise, render HTML template
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    """Custom 500 error handler."""
    app.logger.error(f"Internal Server Error: {e}", exc_info=True) # Log the full error
    db.session.rollback() # Rollback potentially broken transactions
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return jsonify(error="Internal Server Error", message="An unexpected error occurred."), 500
    return render_template('500.html'), 500 # Assuming you have a 500.html template

# --- Initialization and Test Data ---
def create_test_data():
    """Function to populate database with initial test data."""
    with app.app_context():
        print("Checking/Creating test data...")
        changes_made = False

        # Admin User
        if not User.query.filter_by(email='admin@example.com').first():
            try:
                admin = User(email='admin@example.com', name='admin', role='admin')
                admin.set_password('adminpass') # Use a strong password!
                db.session.add(admin)
                print(" -> Created test admin: admin@example.com / adminpass")
                changes_made = True
            except Exception as e:
                print(f"Error creating admin: {e}")
                db.session.rollback()

        # Judge User
        if not User.query.filter_by(email='judge@example.com').first():
            try:
                judge = User(email='judge@example.com', name='Judge User', role='judge')
                judge.set_password('judgepass') # Use a strong password!
                db.session.add(judge)
                print(" -> Created test judge: judge@example.com / judgepass")
                changes_made = True
            except Exception as e:
                print(f"Error creating judge: {e}")
                db.session.rollback()

        # Regular User
        if not User.query.filter_by(email='user@example.com').first():
            try:
                user = User(email='user@example.com', name='Regular User', role='user')
                user.set_password('userpass') # Use a strong password!
                db.session.add(user)
                print(" -> Created test user: user@example.com / userpass")
                changes_made = True
            except Exception as e:
                print(f"Error creating user: {e}")
                db.session.rollback()

        # User requesting judge role
        if not User.query.filter_by(email='request@example.com').first():
            try:
                req_user = User(email='request@example.com', name='Requesting User', role='user', judge_request_pending=True)
                req_user.set_password('requestpass') # Use a strong password!
                db.session.add(req_user)
                print(" -> Created test user requesting judge role: request@example.com / requestpass")
                changes_made = True
            except Exception as e:
                print(f"Error creating requesting user: {e}")
                db.session.rollback()


        # Test Projects
        if Projects.query.count() < 3:
            projects_to_add = [
                {"project_name": "Project Alpha", "group_id": 101, "description": "Innovative project using AI."},
                {"project_name": "Project Beta", "group_id": 102, "description": "Engaging web application for social good."},
                {"project_name": "Project Gamma", "group_id": 103, "description": "Technical hardware project with IoT integration."}
            ]
            for p_data in projects_to_add:
                 if not Projects.query.filter_by(project_name=p_data["project_name"]).first():
                      try:
                          project = Projects(**p_data)
                          db.session.add(project)
                          print(f" -> Created test project: {p_data['project_name']}")
                          changes_made = True
                      except Exception as e:
                          print(f"Error creating project {p_data['project_name']}: {e}")
                          db.session.rollback()

        if changes_made:
            try:
                db.session.commit()
                print("Test data changes committed.")
            except Exception as e:
                 db.session.rollback()
                 print(f"Error committing test data: {e}")
        else:
            print("No new test data needed.")
        print("-" * 20)
@app.route('/admin/students/<int:student_id>', methods=['PUT'])
@role_required('admin')
def update_student(student_id):
    """API endpoint for admin to update an existing student."""
    student = db.session.get(Student, student_id)
    if not student:
        return jsonify({'status': 'error', 'message': 'Student not found.'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided for update.'}), 400

    try:
        updated = False
        if 'student_name' in data:
            new_name = data['student_name'].strip()
            if not new_name: return jsonify({'status': 'error', 'message': 'Student name cannot be empty.'}), 400
            if new_name != student.student_name:
                student.student_name = new_name
                updated = True

        if 'group_id' in data:
            new_group_id_str = data.get('group_id') # Allow empty string/null to clear group
            new_group_id = None
            if new_group_id_str: # If a value is provided
                 try:
                     new_group_id = int(new_group_id_str)
                     # Check if group exists
                     if not db.session.get(Group, new_group_id):
                         return jsonify({'status': 'error', 'message': f'Group with ID {new_group_id} not found.'}), 404
                 except ValueError:
                     return jsonify({'status': 'error', 'message': 'Group ID must be a number or empty.'}), 400

            if new_group_id != student.group_id:
                 student.group_id = new_group_id
                 updated = True

        if updated:
            db.session.commit()
            app.logger.info(f"Admin {g.current_user.id} updated student {student_id}")
            student_data = {
                'student_id': student.student_id, 'student_name': student.student_name,
                'group_id': student.group_id
            }
            return jsonify({'status': 'success', 'message': 'Student updated successfully.', 'student': student_data}), 200
        else:
            return jsonify({'status': 'info', 'message': 'No changes detected or applied.'}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating student {student_id} by admin {g.current_user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to update student due to an internal error.'}), 500

# --- Admin CRUD Operations (Groups) ---

@app.route('/admin/groups/<int:group_id>', methods=['PUT'])
@role_required('admin')
def update_group(group_id):
    """API endpoint for admin to update an existing group."""
    group = db.session.get(Group, group_id)
    if not group:
        return jsonify({'status': 'error', 'message': 'Group not found.'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided for update.'}), 400

    try:
        updated = False
        # Group name is optional
        if 'group_name' in data:
             new_name = data['group_name'].strip()
             # Allow empty string to clear name? Or store NULL? Assume NULL if empty.
             new_name_val = new_name if new_name else None
             if new_name_val != group.group_name:
                 group.group_name = new_name_val
                 updated = True

        if 'project_id' in data:
            new_project_id_str = data.get('project_id') # Allow empty/null to clear project link
            new_project_id = None
            if new_project_id_str:
                 try:
                     new_project_id = int(new_project_id_str)
                     # Check if project exists
                     if not db.session.get(Projects, new_project_id):
                         return jsonify({'status': 'error', 'message': f'Project with ID {new_project_id} not found.'}), 404
                 except ValueError:
                     return jsonify({'status': 'error', 'message': 'Project ID must be a number or empty.'}), 400

            if new_project_id != group.project_id:
                 group.project_id = new_project_id
                 updated = True

        if updated:
            db.session.commit()
            app.logger.info(f"Admin {g.current_user.id} updated group {group_id}")
            group_data = {
                'group_id': group.group_id, 'group_name': group.group_name,
                'project_id': group.project_id
            }
            return jsonify({'status': 'success', 'message': 'Group updated successfully.', 'group': group_data}), 200
        else:
            return jsonify({'status': 'info', 'message': 'No changes detected or applied.'}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating group {group_id} by admin {g.current_user.id}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to update group due to an internal error.'}), 500

if __name__ == '__main__':
    with app.app_context():
        print("Initializing database...")
        # Create tables if they don't exist (including new columns)
        db.create_all()
        print("Database tables created/verified.")
        # Populate with test data if needed
        create_test_data()

    ## verification that app has successfully connected to redis server
    try:
        r.ping()
        print("Successfully connected to Redis!")
    except redis.exceptions.ConnectionError as e:
        print(f"Could not connect to Redis: {e}")

    # Run the Flask development server
    # Use host='0.0.0.0' to make it accessible on the network (use with caution)
    # Use debug=False in production!
    app.run(debug=True, host='127.0.0.1', port=5000)

# --- END OF CORRECTED app.py ---