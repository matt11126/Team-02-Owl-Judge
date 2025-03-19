from flask import Blueprint, render_template, session, redirect, url_for, flash

voting_bp = Blueprint('voting', __name__)


@voting_bp.route('/voting')
def voting():
    # Must be logged in
    if 'user' not in session:
        flash("Please log in first.", "error")
        return redirect(url_for('login'))

    # Must have role FlaskApp or admin
    role = session.get('role')
    if role not in ['FlaskApp', 'admin']:
        flash("You do not have permission to view the voting page.", "error")
        return redirect(url_for('index'))

    # If everything is fine, render the bubble-based voting page
    return render_template('HTML/templates/voting.html')
