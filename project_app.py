from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
import sqlite3
from models import init_db, haversine
from datetime import datetime
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'homeserve-secret-key!'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Initialize database
init_db()

# In-memory storage for active sessions
active_users = {}
active_mechanics = {}

@app.route('/api/register/user', methods=['POST'])
def register_user():
    data = request.json
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (name, phone, email, lat, lng) VALUES (?, ?, ?, ?, ?)",
                 (data['name'], data['phone'], data.get('email'), 0, 0))
        user_id = c.lastrowid
        conn.commit()
        return jsonify({'success': True, 'user_id': user_id, 'message': 'User registered'})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'Phone already registered'}), 400
    finally:
        conn.close()

@app.route('/api/register/mechanic', methods=['POST'])
def register_mechanic():
    data = request.json
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO mechanics (name, phone, skills, lat, lng, status) VALUES (?, ?, ?, ?, ?, ?)",
                 (data['name'], data['phone'], data['skills'], 0, 0, 'offline'))
        mechanic_id = c.lastrowid
        conn.commit()
        return jsonify({'success': True, 'mechanic_id': mechanic_id, 'message': 'Mechanic registered'})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'Phone already registered'}), 400
    finally:
        conn.close()

@app.route('/api/update/location/<phone>', methods=['POST'])
def update_location(phone):
    data = request.json
    role = data['role']  # 'user' or 'mechanic'
    lat, lng = data['lat'], data['lng']
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    if role == 'user':
        c.execute("UPDATE users SET lat=?, lng=? WHERE phone=?", (lat, lng, phone))
        active_users[phone] = {'lat': lat, 'lng': lng}
    else:
        c.execute("UPDATE mechanics SET lat=?, lng=?, status='online' WHERE phone=?", (lat, lng, phone))
        active_mechanics[phone] = {'lat': lat, 'lng': lng}
    
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/request/service', methods=['POST'])
def request_service():
    data = request.json
    user_phone = data['user_phone']
    service_type = data['service_type']
    
    # Get user location
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT lat, lng FROM users WHERE phone=?", (user_phone,))
    user_row = c.fetchone()
    if not user_row:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    
    user_lat, user_lng = user_row
    
    # Save request
    c.execute("INSERT INTO requests (user_id, service_type, user_lat, user_lng) VALUES ((SELECT id FROM users WHERE phone=?), ?, ?, ?)",
             (user_phone, service_type, user_lat, user_lng))
    request_id = c.lastrowid
    conn.commit()
    
    # Find nearest mechanics
    c.execute("""
        SELECT id, name, phone, lat, lng, skills, rating 
        FROM mechanics 
        WHERE status='online' AND skills LIKE ? 
        ORDER BY 
            CASE 
                WHEN lat IS NULL THEN 999999
                ELSE (
                    6371 * acos(cos(radians(?)) * cos(radians(lat)) * 
                    cos(radians(lng) - radians(?)) + 
                    sin(radians(?)) * sin(radians(lat)))
                )
            END
        LIMIT 5
    """, (f"%{service_type}%", user_lat, user_lng, user_lat))
    
    mechanics = c.fetchall()
    conn.close()
    
    # Emit to nearest mechanics via Socket.IO
    request_data = {
        'request_id': request_id,
        'user_phone': user_phone,
        'service_type': service_type,
        'user_lat': user_lat,
        'user_lng': user_lng
    }
    
    for mech in mechanics:
        mech_phone = mech[2]
        socketio.emit('new_request', request_data, room=f'mechanic_{mech_phone}')
    
    return jsonify({
        'success': True, 
        'request_id': request_id,
        'message': f'Notified {len(mechanics)} nearest mechanics'
    })

@app.route('/api/accept/request/<int:request_id>', methods=['POST'])
def accept_request(request_id):
    data = request.json
    mechanic_phone = data['mechanic_phone']
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # Update request status
    c.execute("UPDATE requests SET mechanic_id=(SELECT id FROM mechanics WHERE phone=?), status='accepted' WHERE id=?",
             (mechanic_phone, request_id))
    
    # Get mechanic details
    c.execute("SELECT name, phone, rating FROM mechanics WHERE phone=?", (mechanic_phone,))
    mechanic = c.fetchone()
    
    # Get user phone for notification
    c.execute("SELECT u.phone FROM users u JOIN requests r ON u.id=r.user_id WHERE r.id=?", (request_id,))
    user_phone = c.fetchone()[0]
    
    conn.commit()
    conn.close()
    
    # Notify user
    socketio.emit('request_accepted', {
        'mechanic_name': mechanic[0],
        'mechanic_phone': mechanic[1],
        'rating': mechanic[2]
    }, room=f'user_{user_phone}')
    
    # Notify other mechanics to stop showing this request
    socketio.emit('request_taken', {'request_id': request_id})
    
    return jsonify({'success': True})

@app.route('/api/get/nearby/mechanics/<user_phone>', methods=['GET'])
def get_nearby_mechanics(user_phone):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT lat, lng FROM users WHERE phone=?", (user_phone,))
    user_row = c.fetchone()
    
    if not user_row:
        conn.close()
        return jsonify({'mechanics': []})
    
    user_lat, user_lng = user_row
    
    c.execute("""
        SELECT name, phone, skills, lat, lng, rating,
               (6371 * acos(cos(radians(?)) * cos(radians(lat)) * 
               cos(radians(lng) - radians(?)) + 
               sin(radians(?)) * sin(radians(lat)))) * 1000 as distance
        FROM mechanics 
        WHERE status='online'
        ORDER BY distance
        LIMIT 10
    """, (user_lat, user_lng, user_lat))
    
    mechanics = []
    for row in c.fetchall():
        mechanics.append({
            'name': row[0],
            'phone': row[1],
            'skills': row[2],
            'rating': row[5],
            'distance': round(row[6], 2)
        })
    
    conn.close()
    return jsonify({'mechanics': mechanics})

# Socket.IO Events
@socketio.on('connect_user')
def handle_connect_user(data):
    phone = data['phone']
    join_room(f'user_{phone}')
    emit('connected', {'message': 'Connected to server'})

@socketio.on('connect_mechanic')
def handle_connect_mechanic(data):
    phone = data['phone']
    join_room(f'mechanic_{phone}')
    emit('connected', {'message': 'Connected to server'})

@socketio.on('mechanic_status')
def handle_mechanic_status(data):
    phone = data['phone']
    status = data['status']
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("UPDATE mechanics SET status=? WHERE phone=?", (status, phone))
    conn.commit()
    conn.close()

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)