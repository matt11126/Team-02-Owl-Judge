# test_app.py
import unittest
import json
import io
import os
from datetime import datetime, timedelta

# Assuming your Flask app instance is named 'app' in 'app.py'
# and your db instance is named 'db'
from app import app, db, User, Projects, Scores # Import necessary components

# --- Configuration ---
# Use an in-memory database for testing to avoid altering the production DB
TEST_DB_URI = 'sqlite:///:memory:'

class BaseTestCase(unittest.TestCase):
    """Base class for tests with setup and teardown."""

    def setUp(self):
        """Set up test environment before each test."""
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = TEST_DB_URI
        app.config['WTF_CSRF_ENABLED'] = False # Disable CSRF forms for testing APIs easily
        app.config['SECRET_KEY'] = 'testing-secret-key' # Use a fixed key for testing
        app.config['SESSION_COOKIE_SAMESITE'] = None # Allow cookies in test client

        self.app = app # Store app instance if needed
        self.client = app.test_client() # Create a test client

        with app.app_context():
            db.create_all() # Create all database tables
            self.create_initial_users() # Helper to create standard users

        # Suppress informational logs during tests unless debugging
        app.logger.setLevel('WARNING')


    def tearDown(self):
        """Clean up after each test."""
        with app.app_context():
            db.session.remove() # Clear session
            db.drop_all() # Drop all tables

        # Restore logging level if changed
        app.logger.setLevel(app.config.get('LOG_LEVEL', 'INFO'))


    def create_initial_users(self):
        """Helper method to create standard test users."""
        with app.app_context():
            # Admin
            admin_user = User(email='admin@test.com', name='Test Admin', role='admin')
            admin_user.set_password('AdminPass123!')
            db.session.add(admin_user)

            # Judge
            judge_user = User(email='judge@test.com', name='Test Judge', role='judge')
            judge_user.set_password('JudgePass123!')
            db.session.add(judge_user)

            # Regular User
            regular_user = User(email='user@test.com', name='Test User', role='user')
            regular_user.set_password('UserPass123!')
            db.session.add(regular_user)

            # User pending judge request
            pending_user = User(email='pending@test.com', name='Pending Judge', role='user', judge_request_pending=True)
            pending_user.set_password('PendingPass123!')
            db.session.add(pending_user)

            db.session.commit()

    def login(self, email, password):
        """Helper method to log in a user."""
        return self.client.post('/login',
                                data=json.dumps({'email': email, 'password': password}),
                                content_type='application/json',
                                follow_redirects=True) # Follow redirects to see final page

    def logout(self):
        """Helper method to log out."""
        return self.client.get('/logout', follow_redirects=True)

    def create_project(self, name="Test Project", group_id=999, description="A test project."):
        """Helper method to create a test project."""
        with app.app_context():
            project = Projects(project_name=name, group_id=group_id, description=description)
            db.session.add(project)
            db.session.commit()
            return project.project_id

    def get_user_by_email(self, email):
        """Helper to get user by email."""
        with app.app_context():
            return User.query.filter(db.func.lower(User.email) == db.func.lower(email)).first()

# --- Test Cases ---

class StaticPageTests(BaseTestCase):
    """Tests for basic static page access."""

    def test_home_page(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'OwlJudge', response.data) # Check for brand name

    def test_about_page(self):
        response = self.client.get('/about')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'About OwlJudge', response.data)

    def test_contact_page_get(self):
        response = self.client.get('/contact')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Contact KSU CCSE', response.data)

    # Add test for POST to contact if needed

    def test_favicon(self):
        response = self.client.get('/favicon.ico')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/vnd.microsoft.icon')

    def test_404_page(self):
        response = self.client.get('/nonexistentpage')
        self.assertEqual(response.status_code, 404)
        self.assertIn(b'Page Not Found', response.data) # Check for content in 404.html

    # Testing 500 is harder without mocking, but ensure the template exists

class AuthTests(BaseTestCase):
    """Tests for authentication flows (signup, login, logout)."""

    def test_signup_get(self):
        response = self.client.get('/signup')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Create Your OwlJudge Account', response.data)

    def test_signup_post_success(self):
        with self.client:
            response = self.client.post('/signup',
                                        data=json.dumps({
                                            'name': 'New Test User',
                                            'email': 'newuser@test.com',
                                            'password': 'NewUserPass123!',
                                            'confirm_password': 'NewUserPass123!'
                                        }),
                                        content_type='application/json')
            self.assertEqual(response.status_code, 201) # Check for 201 Created
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'success')
            self.assertIn('Account created successfully', data['message'])
            self.assertIn('/login', data['redirect_url']) # Check redirect target

            # Verify user exists in DB
            user = self.get_user_by_email('newuser@test.com')
            self.assertIsNotNone(user)
            self.assertEqual(user.name, 'New Test User')
            self.assertEqual(user.role, 'user') # Default role

    def test_signup_post_email_exists(self):
        response = self.client.post('/signup',
                                    data=json.dumps({
                                        'name': 'Duplicate User',
                                        'email': 'user@test.com', # Email from initial setup
                                        'password': 'Password123!',
                                        'confirm_password': 'Password123!'
                                    }),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 409) # Conflict
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('Email address already registered', data['message'])

    def test_signup_post_password_mismatch(self):
        response = self.client.post('/signup',
                                    data=json.dumps({
                                        'name': 'Mismatch User',
                                        'email': 'mismatch@test.com',
                                        'password': 'Password123!',
                                        'confirm_password': 'Password456!' # Mismatch
                                    }),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 400) # Bad Request
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('Passwords do not match', data['message'])

    def test_signup_post_weak_password(self):
        response = self.client.post('/signup',
                                    data=json.dumps({
                                        'name': 'Weak User',
                                        'email': 'weak@test.com',
                                        'password': 'weak', # Too short, lacks complexity
                                        'confirm_password': 'weak'
                                    }),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('Password validation failed', data['message'])
        self.assertIn('at least 12 characters', data['message'])

    def test_login_get(self):
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Welcome Back!', response.data)

    def test_login_post_success_user(self):
        with self.client: # Use context manager to handle session
            response = self.login('user@test.com', 'UserPass123!')
            self.assertEqual(response.status_code, 200) # Should end up on redirected page
            self.assertIn(b'Welcome, Test User!', response.data) # Check header welcome message
            # Check session
            self.assertIn('user_id', session)
            user = self.get_user_by_email('user@test.com')
            self.assertEqual(session['user_id'], user.id)

    def test_login_post_success_judge(self):
        with self.client:
            response = self.login('judge@test.com', 'JudgePass123!')
            self.assertEqual(response.status_code, 200)
            # Check if redirected to vote casting page (default for judge)
            self.assertIn(b'Projects to Judge', response.data) # Content from vote_casting.html
            self.assertIn('user_id', session)
            user = self.get_user_by_email('judge@test.com')
            self.assertEqual(session['user_id'], user.id)

    def test_login_post_success_admin(self):
         with self.client:
            response = self.login('admin@test.com', 'AdminPass123!')
            self.assertEqual(response.status_code, 200)
            # Check if redirected to admin dashboard
            self.assertIn(b'Admin Dashboard', response.data) # Content from admin_dashboard.html
            self.assertIn('user_id', session)
            user = self.get_user_by_email('admin@test.com')
            self.assertEqual(session['user_id'], user.id)

    def test_login_post_wrong_password(self):
        response = self.client.post('/login',
                                    data=json.dumps({'email': 'user@test.com', 'password': 'WrongPassword'}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 401) # Unauthorized
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('Invalid email or password', data['message'])
        self.assertNotIn('user_id', session)

    def test_login_post_wrong_email(self):
        response = self.client.post('/login',
                                    data=json.dumps({'email': 'nonexistent@test.com', 'password': 'UserPass123!'}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 401)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('Invalid email or password', data['message'])
        self.assertNotIn('user_id', session)

    def test_logout(self):
        with self.client:
            self.login('user@test.com', 'UserPass123!')
            self.assertIn('user_id', session)
            response = self.logout()
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('user_id', session)
            self.assertIn(b'You have been successfully logged out.', response.data) # Check flashed message

    def test_redirect_if_logged_in(self):
        with self.client:
            self.login('user@test.com', 'UserPass123!')
            # Try accessing login page again
            response = self.client.get('/login', follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'You are already logged in.', response.data) # Check flashed message
            self.assertNotIn(b'Welcome Back!', response.data) # Shouldn't see login form
            # Try accessing signup page again
            response = self.client.get('/signup', follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'You are already logged in.', response.data)
            self.assertNotIn(b'Create Your OwlJudge Account', response.data)

class ProfileTests(BaseTestCase):
    """Tests for user profile management."""

    def test_profile_access_logged_out(self):
        response = self.client.get('/profile', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Please log in to access this page.', response.data) # Check flash message
        self.assertIn(b'Welcome Back!', response.data) # Should be on login page

    def test_profile_access_logged_in(self):
        with self.client:
            self.login('user@test.com', 'UserPass123!')
            response = self.client.get('/profile')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Your OwlJudge Profile', response.data)
            self.assertIn(b'Test User', response.data)
            self.assertIn(b'user@test.com', response.data)
            self.assertIn(b'role-badge user', response.data) # Check role display

    def test_update_name_success(self):
        with self.client:
            self.login('user@test.com', 'UserPass123!')
            response = self.client.post('/update_name',
                                        data=json.dumps({'name': 'Updated Test User'}),
                                        content_type='application/json')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'success')
            self.assertIn('Name updated successfully', data['message'])

            # Verify name in DB
            user = self.get_user_by_email('user@test.com')
            self.assertEqual(user.name, 'Updated Test User')

    def test_update_name_empty(self):
        with self.client:
            self.login('user@test.com', 'UserPass123!')
            response = self.client.post('/update_name',
                                        data=json.dumps({'name': ''}),
                                        content_type='application/json')
            self.assertEqual(response.status_code, 400)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'error')
            self.assertIn('Name cannot be empty', data['message'])

    def test_change_password_success(self):
        with self.client:
            self.login('user@test.com', 'UserPass123!')
            response = self.client.post('/change_password',
                                        data=json.dumps({
                                            'current_password': 'UserPass123!',
                                            'new_password': 'NewSecureP@ss1!',
                                            'confirm_password': 'NewSecureP@ss1!'
                                        }),
                                        content_type='application/json')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'success')
            self.assertIn('Password changed successfully', data['message'])

            # Verify password works for login (logout first)
            self.logout()
            response = self.login('user@test.com', 'NewSecureP@ss1!')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Welcome, Test User!', response.data)

    def test_change_password_wrong_current(self):
        with self.client:
            self.login('user@test.com', 'UserPass123!')
            response = self.client.post('/change_password',
                                        data=json.dumps({
                                            'current_password': 'WrongCurrentPass',
                                            'new_password': 'NewSecureP@ss1!',
                                            'confirm_password': 'NewSecureP@ss1!'
                                        }),
                                        content_type='application/json')
            self.assertEqual(response.status_code, 401) # Unauthorized
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'error')
            self.assertIn('Incorrect current password', data['message'])

    def test_change_password_mismatch_new(self):
         with self.client:
            self.login('user@test.com', 'UserPass123!')
            response = self.client.post('/change_password',
                                        data=json.dumps({
                                            'current_password': 'UserPass123!',
                                            'new_password': 'NewSecureP@ss1!',
                                            'confirm_password': 'DifferentP@ss1!' # Mismatch
                                        }),
                                        content_type='application/json')
            self.assertEqual(response.status_code, 400)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'error')
            self.assertIn('New passwords do not match', data['message'])

    def test_change_password_weak_new(self):
        with self.client:
            self.login('user@test.com', 'UserPass123!')
            response = self.client.post('/change_password',
                                        data=json.dumps({
                                            'current_password': 'UserPass123!',
                                            'new_password': 'weak',
                                            'confirm_password': 'weak'
                                        }),
                                        content_type='application/json')
            self.assertEqual(response.status_code, 400)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'error')
            self.assertIn('Password validation failed', data['message'])

    def test_request_judge_role_success(self):
         with self.client:
            self.login('user@test.com', 'UserPass123!')
            response = self.client.post('/request_judge_role', content_type='application/json') # No body needed
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'success')
            self.assertIn('request to become a judge has been submitted', data['message'])
            # Verify flag in DB
            user = self.get_user_by_email('user@test.com')
            self.assertTrue(user.judge_request_pending)

    def test_request_judge_role_already_pending(self):
        with self.client:
            self.login('pending@test.com', 'PendingPass123!') # Login as the user already pending
            response = self.client.post('/request_judge_role', content_type='application/json')
            self.assertEqual(response.status_code, 409) # Conflict/Info
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'info')
            self.assertIn('already submitted a request', data['message'])

    def test_request_judge_role_already_judge(self):
        with self.client:
            self.login('judge@test.com', 'JudgePass123!')
            response = self.client.post('/request_judge_role', content_type='application/json')
            self.assertEqual(response.status_code, 409) # Conflict/Info
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'info')
            self.assertIn('already a judge', data['message'])

class PasswordResetTests(BaseTestCase):
    """Tests for the password reset flow."""

    def test_forgot_password_get(self):
        response = self.client.get('/forgot_password')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Forgot Your Password?', response.data)

    def test_forgot_password_post_user_exists(self):
        with app.app_context():
            user = self.get_user_by_email('user@test.com')
            initial_token = user.reset_token
            initial_expiry = user.reset_token_expiration

        response = self.client.post('/forgot_password', data={'email': 'user@test.com'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200) # Ends on login page
        self.assertIn(b'If an account with that email exists', response.data) # Check flash message

        # Check DB for token generation
        with app.app_context():
            user = self.get_user_by_email('user@test.com')
            self.assertIsNotNone(user.reset_token)
            self.assertIsNotNone(user.reset_token_expiration)
            self.assertNotEqual(user.reset_token, initial_token)
            # Verify token expiry is in the future (approx 1 hour)
            self.assertGreater(user.reset_token_expiration, datetime.utcnow() + timedelta(minutes=55))
            self.assertLess(user.reset_token_expiration, datetime.utcnow() + timedelta(minutes=65))

    def test_forgot_password_post_user_does_not_exist(self):
        # Should show the *same* message for security
        response = self.client.post('/forgot_password', data={'email': 'nonexistent@test.com'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'If an account with that email exists', response.data)

    def test_reset_password_get_valid_token(self):
        token = None
        with app.app_context():
            user = self.get_user_by_email('user@test.com')
            token = user.generate_reset_token()
            db.session.commit()

        self.assertIsNotNone(token)
        response = self.client.get(f'/reset_password/{token}')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Set a New Password', response.data)

    def test_reset_password_get_invalid_token(self):
        response = self.client.get('/reset_password/invalid-token-string', follow_redirects=True)
        self.assertEqual(response.status_code, 200) # Ends on forgot password page
        self.assertIn(b'The password reset link is invalid or has expired', response.data)
        self.assertIn(b'Forgot Your Password?', response.data) # Check it redirected correctly

    def test_reset_password_get_expired_token(self):
        token = None
        with app.app_context():
            user = self.get_user_by_email('user@test.com')
            token = user.generate_reset_token()
            # Manually set expiration to the past
            user.reset_token_expiration = datetime.utcnow() - timedelta(minutes=1)
            db.session.commit()

        self.assertIsNotNone(token)
        response = self.client.get(f'/reset_password/{token}', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'The password reset link is invalid or has expired', response.data)
        self.assertIn(b'Forgot Your Password?', response.data)

    def test_reset_password_post_success(self):
        token = None
        with app.app_context():
            user = self.get_user_by_email('user@test.com')
            token = user.generate_reset_token()
            db.session.commit()

        self.assertIsNotNone(token)
        response = self.client.post(f'/reset_password/{token}',
                                    data={'new_password': 'ResetP@ssw0rd!', 'confirm_password': 'ResetP@ssw0rd!'},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200) # Ends on login page
        self.assertIn(b'Your password has been successfully reset!', response.data)
        self.assertIn(b'Welcome Back!', response.data) # Check on login page

        # Verify token is invalidated and password works
        with app.app_context():
            user = self.get_user_by_email('user@test.com')
            self.assertIsNone(user.reset_token)
            self.assertIsNone(user.reset_token_expiration)
            self.assertTrue(user.check_password('ResetP@ssw0rd!'))

    def test_reset_password_post_mismatch(self):
        token = None
        with app.app_context():
            user = self.get_user_by_email('user@test.com')
            token = user.generate_reset_token()
            db.session.commit()

        self.assertIsNotNone(token)
        response = self.client.post(f'/reset_password/{token}',
                                    data={'new_password': 'ResetP@ssw0rd!', 'confirm_password': 'DifferentPass!'},
                                    follow_redirects=True) # Follow redirects is false here to check flash on same page
        self.assertEqual(response.status_code, 200) # Stays on reset page
        self.assertIn(b'Passwords do not match.', response.data)
        self.assertIn(b'Set a New Password', response.data) # Verify still on reset page

        # Verify token is still valid
        with app.app_context():
             user = self.get_user_by_email('user@test.com')
             self.assertTrue(user.is_reset_token_valid(token))

    def test_reset_password_post_weak(self):
        token = None
        with app.app_context():
            user = self.get_user_by_email('user@test.com')
            token = user.generate_reset_token()
            db.session.commit()

        self.assertIsNotNone(token)
        response = self.client.post(f'/reset_password/{token}',
                                    data={'new_password': 'weak', 'confirm_password': 'weak'},
                                    follow_redirects=False)
        self.assertEqual(response.status_code, 200) # Stays on reset page
        self.assertIn(b'Password validation failed', response.data)
        self.assertIn(b'Set a New Password', response.data) # Verify still on reset page


class VotingTests(BaseTestCase):
    """Tests for judge voting functionality."""

    def setUp(self):
        super().setUp()
        # Create a project for voting
        self.project_id = self.create_project(name="Voting Project", group_id=101)

    def test_vote_casting_page_access_judge(self):
        with self.client:
            self.login('judge@test.com', 'JudgePass123!')
            response = self.client.get('/vote')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Projects to Judge', response.data)
            self.assertIn(b'Voting Project', response.data) # Check project is listed

    def test_vote_casting_page_access_admin(self):
        with self.client:
            self.login('admin@test.com', 'AdminPass123!')
            response = self.client.get('/vote')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Projects to Judge', response.data)
            self.assertIn(b'Voting Project', response.data)

    def test_vote_casting_page_access_user(self):
        with self.client:
            self.login('user@test.com', 'UserPass123!')
            response = self.client.get('/vote', follow_redirects=True)
            self.assertEqual(response.status_code, 200) # Ends on index page
            self.assertIn(b'You must have one of the following roles', response.data) # Check flash message
            self.assertNotIn(b'Projects to Judge', response.data) # Should not see voting content

    def test_submit_vote_success_new(self):
        with self.client:
            self.login('judge@test.com', 'JudgePass123!')
            response = self.client.post('/submit_vote',
                                        data=json.dumps({
                                            'project_id': self.project_id,
                                            'scores': {
                                                'innovation': 8,
                                                'presentation': 7,
                                                'technical_merit': 9
                                            }
                                        }),
                                        content_type='application/json')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'success')
            self.assertIn('Votes for Voting Project submitted successfully', data['message'])

            # Verify scores in DB
            with app.app_context():
                judge = self.get_user_by_email('judge@test.com')
                scores = Scores.query.filter_by(project_id=self.project_id, judge_id=judge.id).all()
                self.assertEqual(len(scores), 3)
                scores_dict = {s.category: s.score_given for s in scores}
                self.assertEqual(scores_dict.get('innovation'), 8)
                self.assertEqual(scores_dict.get('presentation'), 7)
                self.assertEqual(scores_dict.get('technical_merit'), 9)

    def test_submit_vote_success_update(self):
        judge_id = None
        with self.client:
            self.login('judge@test.com', 'JudgePass123!')
            judge_id = session['user_id']
            # Submit initial vote
            self.client.post('/submit_vote', data=json.dumps({'project_id': self.project_id, 'scores': {'innovation': 5, 'presentation': 6}}), content_type='application/json')

            # Submit updated vote
            response = self.client.post('/submit_vote',
                                        data=json.dumps({
                                            'project_id': self.project_id,
                                            'scores': {
                                                'innovation': 9, # Updated
                                                'presentation': 6, # Same
                                                'technical_merit': 7 # Added
                                            }
                                        }),
                                        content_type='application/json')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'success')
            self.assertIn('Votes for Voting Project updated successfully', data['message'])

            # Verify updated scores in DB
            with app.app_context():
                scores = Scores.query.filter_by(project_id=self.project_id, judge_id=judge_id).all()
                self.assertEqual(len(scores), 3) # Now has 3 categories
                scores_dict = {s.category: s.score_given for s in scores}
                self.assertEqual(scores_dict.get('innovation'), 9)
                self.assertEqual(scores_dict.get('presentation'), 6)
                self.assertEqual(scores_dict.get('technical_merit'), 7)

    def test_submit_vote_invalid_score_range(self):
        with self.client:
            self.login('judge@test.com', 'JudgePass123!')
            response = self.client.post('/submit_vote',
                                        data=json.dumps({
                                            'project_id': self.project_id,
                                            'scores': {
                                                'innovation': 11, # Out of range
                                                'presentation': 5
                                            }
                                        }),
                                        content_type='application/json')
            self.assertEqual(response.status_code, 400) # Bad Request
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'error')
            self.assertIn('must be between 1 and 10', data['message'])

    def test_submit_vote_missing_project_id(self):
        with self.client:
            self.login('judge@test.com', 'JudgePass123!')
            response = self.client.post('/submit_vote',
                                        data=json.dumps({
                                            # Missing project_id
                                            'scores': {'innovation': 8}
                                        }),
                                        content_type='application/json')
            self.assertEqual(response.status_code, 400)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'error')
            self.assertIn('Missing project_id field', data['message'])

    def test_submit_vote_invalid_project_id(self):
        with self.client:
            self.login('judge@test.com', 'JudgePass123!')
            response = self.client.post('/submit_vote',
                                        data=json.dumps({
                                            'project_id': 9999, # Non-existent ID
                                            'scores': {'innovation': 8}
                                        }),
                                        content_type='application/json')
            self.assertEqual(response.status_code, 404) # Not Found
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'error')
            self.assertIn('Project with ID 9999 not found', data['message'])

    def test_get_scores_success(self):
         with self.client:
            self.login('judge@test.com', 'JudgePass123!')
            # First, submit some scores
            self.client.post('/submit_vote', data=json.dumps({'project_id': self.project_id, 'scores': {'innovation': 8, 'presentation': 7}}), content_type='application/json')
            # Now, get the scores
            response = self.client.get(f'/get_scores/{self.project_id}')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data)
            self.assertEqual(data.get('innovation'), 8)
            self.assertEqual(data.get('presentation'), 7)
            self.assertIsNone(data.get('technical_merit')) # Shouldn't exist yet

    def test_get_scores_no_scores_yet(self):
        with self.client:
            self.login('judge@test.com', 'JudgePass123!')
            response = self.client.get(f'/get_scores/{self.project_id}')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data)
            self.assertEqual(data, {}) # Should return empty object

    def test_get_scores_invalid_project(self):
        with self.client:
            self.login('judge@test.com', 'JudgePass123!')
            response = self.client.get('/get_scores/9999')
            self.assertEqual(response.status_code, 404)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'error')
            self.assertIn('Project not found', data['message'])


# Add Audience Tests (basic access, maybe API call if endpoint exists)
class AudienceTests(BaseTestCase):

    def test_audience_page_access_logged_in(self):
        with self.client:
            self.login('user@test.com', 'UserPass123!')
            response = self.client.get('/audience')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Project Leaderboard', response.data) # Assuming this title exists

    def test_audience_page_access_logged_out(self):
        response = self.client.get('/audience', follow_redirects=True)
        self.assertEqual(response.status_code, 200) # Redirects to login
        self.assertIn(b'Please log in to access this page.', response.data)
        self.assertIn(b'Welcome Back!', response.data) # On login page

    # Add test for /api/leaderboard if it exists
    # def test_leaderboard_api(self):
    #     # Need to create projects and scores first
    #     # ... setup ...
    #     response = self.client.get('/api/leaderboard')
    #     self.assertEqual(response.status_code, 200)
    #     data = json.loads(response.data)
    #     self.assertIsInstance(data, list)
    #     # Add more assertions based on expected data structure

# Placeholder for Admin tests - These will be extensive
class AdminDashboardTests(BaseTestCase):
    """Tests for Admin Dashboard functionality."""

    # --- Access Control ---
    def test_admin_dashboard_access_admin(self):
        with self.client:
            self.login('admin@test.com', 'AdminPass123!')
            response = self.client.get('/admin/dashboard')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Admin Dashboard', response.data)
            # Check for presence of key sections/tables
            self.assertIn(b'All Users', response.data)
            self.assertIn(b'Projects', response.data)
            self.assertIn(b'Scores by Category', response.data)

    def test_admin_dashboard_access_denied_judge(self):
        with self.client:
            self.login('judge@test.com', 'JudgePass123!')
            response = self.client.get('/admin/dashboard', follow_redirects=True)
            self.assertEqual(response.status_code, 200) # Redirects to index
            self.assertIn(b'You must be an admin to access this page', response.data)
            self.assertNotIn(b'Admin Dashboard', response.data)

    def test_admin_dashboard_access_denied_user(self):
        with self.client:
            self.login('user@test.com', 'UserPass123!')
            response = self.client.get('/admin/dashboard', follow_redirects=True)
            self.assertEqual(response.status_code, 200) # Redirects to index
            self.assertIn(b'You must be an admin to access this page', response.data)
            self.assertNotIn(b'Admin Dashboard', response.data)

    # --- User Management APIs ---
    def test_admin_add_user_success(self):
        with self.client:
            self.login('admin@test.com', 'AdminPass123!')
            response = self.client.post('/admin/users',
                                        data=json.dumps({
                                            'name': 'Admin Added User',
                                            'email': 'added@test.com',
                                            'password': 'AddedUserP@ss1!',
                                            'role': 'judge' # Add as judge
                                        }),
                                        content_type='application/json')
            self.assertEqual(response.status_code, 201)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'success')
            self.assertIn('user', data)
            self.assertEqual(data['user']['email'], 'added@test.com')
            self.assertEqual(data['user']['role'], 'judge')
            # Verify in DB
            user = self.get_user_by_email('added@test.com')
            self.assertIsNotNone(user)
            self.assertEqual(user.role, 'judge')

    def test_admin_add_user_email_exists(self):
        with self.client:
            self.login('admin@test.com', 'AdminPass123!')
            response = self.client.post('/admin/users',
                                        data=json.dumps({
                                            'name': 'Exists User',
                                            'email': 'user@test.com', # Existing user
                                            'password': 'Password123!',
                                            'role': 'user'
                                        }),
                                        content_type='application/json')
            self.assertEqual(response.status_code, 409) # Conflict
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'error')
            self.assertIn('Email address already registered', data['message'])

    def test_admin_update_user_success(self):
        with self.client:
            self.login('admin@test.com', 'AdminPass123!')
            user_to_update = self.get_user_by_email('user@test.com')
            response = self.client.put(f'/admin/users/{user_to_update.id}',
                                       data=json.dumps({
                                           'name': 'User Updated Name',
                                           'role': 'judge', # Promote to judge
                                           'email': 'user_updated@test.com' # Change email
                                       }),
                                       content_type='application/json')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'success')
            self.assertIn('user', data)
            self.assertEqual(data['user']['name'], 'User Updated Name')
            self.assertEqual(data['user']['role'], 'judge')
            self.assertEqual(data['user']['email'], 'user_updated@test.com')
            # Verify in DB
            db.session.refresh(user_to_update) # Refresh object state
            self.assertEqual(user_to_update.name, 'User Updated Name')
            self.assertEqual(user_to_update.role, 'judge')
            self.assertEqual(user_to_update.email, 'user_updated@test.com')

    def test_admin_delete_user_success(self):
        with self.client:
            self.login('admin@test.com', 'AdminPass123!')
            user_to_delete = self.get_user_by_email('user@test.com')
            user_id = user_to_delete.id
            response = self.client.delete(f'/admin/users/{user_id}')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'success')
            # Verify deleted from DB
            deleted_user = db.session.get(User, user_id)
            self.assertIsNone(deleted_user)

    def test_admin_delete_self_fail(self):
        with self.client:
            self.login('admin@test.com', 'AdminPass123!')
            admin_user = self.get_user_by_email('admin@test.com')
            response = self.client.delete(f'/admin/users/{admin_user.id}')
            self.assertEqual(response.status_code, 403) # Forbidden
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'error')
            self.assertIn('Cannot delete your own account', data['message'])

    def test_admin_approve_judge_success(self):
         with self.client:
            self.login('admin@test.com', 'AdminPass123!')
            pending_user = self.get_user_by_email('pending@test.com')
            self.assertTrue(pending_user.judge_request_pending) # Verify initially pending
            self.assertEqual(pending_user.role, 'user')

            response = self.client.post(f'/admin/approve_judge/{pending_user.id}')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'success')
            self.assertIn('promoted to Judge', data['message'])
            self.assertEqual(data['user']['role'], 'judge')
            self.assertFalse(data['user']['judge_request_pending'])

            # Verify in DB
            db.session.refresh(pending_user)
            self.assertEqual(pending_user.role, 'judge')
            self.assertFalse(pending_user.judge_request_pending)

    # --- Project Management APIs ---
    def test_admin_add_project_success(self):
         with self.client:
            self.login('admin@test.com', 'AdminPass123!')
            response = self.client.post('/admin/projects',
                                        data=json.dumps({
                                            'project_name': 'New Admin Project',
                                            'group_id': 505,
                                            'description': 'Desc for new project'
                                        }),
                                        content_type='application/json')
            self.assertEqual(response.status_code, 201)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'success')
            self.assertIn('project', data)
            self.assertEqual(data['project']['project_name'], 'New Admin Project')
            # Verify in DB
            proj = Projects.query.filter_by(project_name='New Admin Project').first()
            self.assertIsNotNone(proj)
            self.assertEqual(proj.group_id, 505)

    def test_admin_update_project_success(self):
        proj_id = self.create_project(name="Update Me", group_id=111)
        with self.client:
            self.login('admin@test.com', 'AdminPass123!')
            response = self.client.put(f'/admin/projects/{proj_id}',
                                       data=json.dumps({
                                           'project_name': 'Successfully Updated',
                                           'group_id': 222,
                                           'description': 'New desc.'
                                       }),
                                       content_type='application/json')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'success')
            self.assertEqual(data['project']['project_name'], 'Successfully Updated')
            # Verify in DB
            proj = db.session.get(Projects, proj_id)
            self.assertEqual(proj.project_name, 'Successfully Updated')
            self.assertEqual(proj.group_id, 222)
            self.assertEqual(proj.description, 'New desc.')

    def test_admin_delete_project_success(self):
        proj_id = self.create_project(name="Delete Me", group_id=333)
        with self.client:
            self.login('admin@test.com', 'AdminPass123!')
            response = self.client.delete(f'/admin/projects/{proj_id}')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'success')
            # Verify deleted from DB
            proj = db.session.get(Projects, proj_id)
            self.assertIsNone(proj)

    # --- Score Management APIs ---
    # Add tests for POST, PUT, DELETE on /admin/scores/<id> similarly

    # --- Import/Export (Basic Checks) ---
    @unittest.skipIf(not app.config.get('IMPORT_EXPORT_ENABLED', True), "pandas/openpyxl not installed")
    def test_export_routes_exist_admin_only(self):
        with self.client:
            # Deny non-admin
            self.login('judge@test.com', 'JudgePass123!')
            res_users = self.client.get('/admin/export/users')
            res_projects = self.client.get('/admin/export/projects')
            res_scores = self.client.get('/admin/export/scores')
            self.assertEqual(res_users.status_code, 302) # Redirect
            self.assertEqual(res_projects.status_code, 302)
            self.assertEqual(res_scores.status_code, 302)
            self.logout()

            # Allow admin
            self.login('admin@test.com', 'AdminPass123!')
            res_users = self.client.get('/admin/export/users')
            res_projects = self.client.get('/admin/export/projects')
            res_scores = self.client.get('/admin/export/scores')
            # We expect a file download, check content type and disposition
            self.assertEqual(res_users.status_code, 200)
            self.assertEqual(res_projects.status_code, 200)
            self.assertEqual(res_scores.status_code, 200)
            self.assertIn('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', res_users.content_type)
            self.assertIn('attachment; filename=owljudge_users_', res_users.headers['Content-Disposition'])

    @unittest.skipIf(not app.config.get('IMPORT_EXPORT_ENABLED', True), "pandas/openpyxl not installed")
    def test_import_routes_exist_admin_only(self):
         with self.client:
            # Deny non-admin
            self.login('judge@test.com', 'JudgePass123!')
            res_users = self.client.post('/admin/import/users')
            res_projects = self.client.post('/admin/import/projects')
            self.assertEqual(res_users.status_code, 302) # Redirect
            self.assertEqual(res_projects.status_code, 302)
            self.logout()

            # Allow admin - Test basic response without file
            self.login('admin@test.com', 'AdminPass123!')
            res_users = self.client.post('/admin/import/users') # No file sent
            res_projects = self.client.post('/admin/import/projects') # No file sent
            self.assertEqual(res_users.status_code, 400)
            self.assertEqual(res_projects.status_code, 400)
            self.assertIn(b'No file part', res_users.data)
            self.assertIn(b'No file part', res_projects.data)
        # Note: Fully testing import requires creating mock Excel files


    # --- Judge Assignment (Placeholder - requires routes in app.py) ---
    # def test_admin_assign_judges(self):
    #     proj_id = self.create_project()
    #     judge = self.get_user_by_email('judge@test.com')
    #     admin = self.get_user_by_email('admin@test.com')
    #     with self.client:
    #         self.login('admin@test.com', 'AdminPass123!')
    #         # Test assigning judges
    #         response = self.client.put(f'/admin/projects/{proj_id}/judges',
    #                                    data=json.dumps({'judge_ids': [judge.id, admin.id]}), # Assign judge and admin
    #                                    content_type='application/json')
    #         # self.assertEqual(response.status_code, 200)
    #         # data = json.loads(response.data)
    #         # self.assertEqual(data['status'], 'success')
    #         # Verify assignments in DB (requires JudgeProjectAssociation table or similar)
    #         # ...
    #
    #         # Test getting assigned judges
    #         response = self.client.get(f'/admin/projects/{proj_id}/judges')
    #         # self.assertEqual(response.status_code, 200)
    #         # data = json.loads(response.data)
    #         # self.assertIn('judges', data)
    #         # self.assertEqual(len(data['judges']), 2)
    #         # Assert specific judge IDs are present

if __name__ == '__main__':
    unittest.main()