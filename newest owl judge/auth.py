from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from models.models import Judge  # Using Judge as the user model
from app import db

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))  # Redirect to home if already logged in

    if request.method == 'POST':
        email = request.form.get('username')  # Using 'username' field for email
        password = request.form.get('password')

        user = Judge.query.filter_by(email=email).first()
        if user and user.check_password(password):  # Assuming Judge has check_password method
            login_user(user)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password.', 'error')

    return render_template('HTML/templates/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    # Ensure user is fully logged out
    logout_user()

    # Clear session completely
    session.clear()

    # Expire session cookie immediately
    response = redirect(url_for('auth.login'))
    response.set_cookie('session', '', expires=0)

    flash('You have been logged out successfully.', 'success')
    return response


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('signupUsername')
        password = request.form.get('signupPassword')
        confirm_password = request.form.get('signupConfirmPassword')

        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('auth.signup'))

        if Judge.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('auth.signup'))

        # Create new judge/user
        new_user = Judge(email=email, name=email.split('@')[0])  # Default name from email
        new_user.set_password(password)  # Assuming set_password hashes the password
        db.session.add(new_user)
        db.session.commit()

        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('HTML/templates/signup.html')