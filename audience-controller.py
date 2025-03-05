from flask import Blueprint, render_template, jsonify, request
from services.redis_service import RedisService
from models.project import Project
from models.criteria import Criteria
from models.team import Team

# Create blueprint
audience_bp = Blueprint('audience', __name__)

@audience_bp.route('/')
def display():
    """Display the audience view showing the current project being judged"""
    # Get the active project
    active_project_id = RedisService.get_active_project()
    
    if not active_project_id:
        # No active project, show standby screen
        return render_template('audience/standby.html')
    
    # Get project details
    project = Project.query.get(active_project_id)
    
    if not project:
        return render_template('audience/standby.html', 
                              error="Project not found")
    
    # Get teams for this project
    teams = Team.query.filter_by(project_id=active_project_id).all()
    
    # Get criteria for display
    criteria = Criteria.query.filter_by(active=True).all()
    
    # Get current score
    current_score = RedisService.redis_client.get(f"project:{active_project_id}:current_score")
    score = float(current_score.decode('utf-8')) if current_score else 0
    
    return render_template('audience/display.html',
                          project=project,
                          teams=teams,
                          criteria=criteria,
                          current_score=score)

@audience_bp.route('/api/current-project')
def get_current_project():
    """API endpoint to get current project info for real-time updates"""
    active_project_id = RedisService.get_active_project()
    
    if not active_project_id:
        return jsonify({
            'active': False,
            'message': 'No active project'
        })
    
    # Get project details
    project = Project.query.get(active_project_id)
    
    if not project:
        return jsonify({
            'active': False,
            'message': 'Project not found'
        })
    
    # Get current score
    current_score = RedisService.redis_client.get(f"project:{active_project_id}:current_score")
    score = float(current_score.decode('utf-8')) if current_score else 0
    
    # Get vote details
    votes = RedisService.get_project_votes(active_project_id)
    
    # Get teams
    teams = Team.query.filter_by(project_id=active_project_id).all()
    teams_data = [{'id': t.id, 'name': t.name} for t in teams]
    
    return jsonify({
        'active': True,
        'project': {
            'id': project.id,
            'name': project.name,
            'description': project.description
        },
        'teams': teams_data,
        'current_score': score,
        'votes': votes
    })

@audience_bp.route('/leaderboard')
def leaderboard():
    """Display a leaderboard of all projects and their scores"""
    # Get all projects
    projects = Project.query.all()
    project_scores = []
    
    for project in projects:
        # Get final score from database or current score from Redis
        score_key = f"project:{project.id}:current_score"
        current_score = RedisService.redis_client.get(score_key)
        score = float(current_score.decode('utf-8')) if current_score else 0
        
        project_scores.append({
            'id': project.id,
            'name': project.name,
            'score': score,
            'teams': [t.name for t in project.teams]
        })
    
    # Sort by score, descending
    project_scores.sort(key=lambda x: x['score'], reverse=True)
    
    return render_template('audience/leaderboard.html',
                          projects=project_scores)
