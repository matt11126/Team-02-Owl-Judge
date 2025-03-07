from flask import Flask, render_template, request, session, jsonify, flash, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
# Use a strong secret key (in production, use environment variables)
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key_here')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False

# In-memory user store (for demonstration - use a database in production)
users = {}


@app.route('/')
def index():
    return render_template('HTML/index.html')


@app.route('/about')
def about():
    return render_template('HTML/about_us.html')


@app.route('/audience')
def audience():
    return render_template('HTML/audience.html')


@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('HTML/dashboard.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    # Handle POST request for login
    if request.method == 'POST':
        print("Login attempt received")
        print(f"Form data: {request.form}")

        # Get form data
        email = request.form.get('username')
        password = request.form.get('password')

        # Validate credentials
        login_successful = False
        if email in users and check_password_hash(users[email]['password'], password):
            session['user'] = users[email]['name']
            login_successful = True
            print(f"Login successful for: {email}")
        else:
            print(f"Login failed for: {email}")

        # Handle AJAX requests
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            if login_successful:
                return jsonify({'success': True, 'message': 'Logged in successfully!'})
            else:
                return jsonify({'success': False, 'message': 'Invalid email or password'})

        # Handle regular form submissions
        if login_successful:
            flash("Logged in successfully!", "success")
            return redirect(url_for('index'))
        else:
            flash("Invalid email or password", "error")
            return redirect(url_for('login'))

    # Handle GET request - show login page
    return render_template('HTML/login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    # Handle POST request for signup
    if request.method == 'POST':
        print("Signup attempt received")
        print(f"Form data: {request.form}")

        # Get form data
        email = request.form.get('signupUsername')
        password = request.form.get('signupPassword')

        # Validate data
        if not email or not password:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'Email and password are required'})
            flash("Email and password are required", "error")
            return redirect(url_for('signup'))

        # Check if user exists
        if email in users:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'Email already registered'})
            flash("Email already registered", "error")
            return redirect(url_for('signup'))

        # Create new user
        hashed_password = generate_password_hash(password)
        users[email] = {
            'password': hashed_password,
            'name': email.split('@')[0]
        }

        # Log in the new user
        session['user'] = users[email]['name']
        print(f"New user created: {email}")

        # Handle AJAX requests
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': 'Account created successfully!'})

        # Handle regular form submissions
        flash("Account created successfully!", "success")
        return redirect(url_for('index'))

    # Handle GET request - show signup page
    return render_template('HTML/signup.html')


@app.route('/profile')
def profile():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('HTML/profile.html')


@app.route('/contact')
def contact():
    return render_template('HTML/contact_us.html')


@app.route('/vote_casting')
def vote_casting():
    if 'user' not in session:
        flash("Please log in to cast votes.", "error")
        return redirect(url_for('login'))
    return render_template('HTML/vote_casting.html')


@app.route('/logout')
def logout():
    session.pop('user', None)
    flash("You have been logged out.", "success")
    return redirect(url_for('index'))


# Debug route to check session and users (remove in production)
@app.route('/debug')
def debug():
    if app.debug:
        return jsonify({
            'session': dict(session),
            'users': {k: {'name': v['name']} for k, v in users.items()}  # Don't expose password hashes
        })
    return "Debug endpoint disabled in production", 403


# Register blueprints if available
try:
    from voting_blueprint import voting_bp

    app.register_blueprint(voting_bp)
except ImportError:
    pass

if __name__ == '__main__':
    # Add a test user for development purposes
    test_email = 'test@example.com'
    if test_email not in users:
        users[test_email] = {
            'password': generate_password_hash('password'),
            'name': 'Test User'
        }
        print(f"Created test user: {test_email} with password: password")

    app.run(debug=True)