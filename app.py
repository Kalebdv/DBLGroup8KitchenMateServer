from flask import Flask, request, jsonify
import sqlite3
import uuid

app = Flask(__name__)

# 1. This creates the database file (users.db) and a table if they don't exist
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id TEXT PRIMARY KEY, name TEXT, email TEXT, role TEXT, password TEXT)''')
    conn.commit()
    conn.close()

init_db() # Run database setup on startup

# 2. This is the exact route your Retrofit client is looking for
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    role = data.get('role')
    password = data.get('password') 
    
    # We are NOT doing any security things, just storing passwords as text for now

    # Generate a unique User ID and a session token
    user_id = str(uuid.uuid4())
    session_token = f"kitchenmate_token_{uuid.uuid4().hex}"

    # Open the database and save the user
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (id, name, email, role, password) VALUES (?, ?, ?, ?, ?)",
                  (user_id, name, email, role, password))
        conn.commit()
        print(f"Success: Saved {name} to the database!")
    except Exception as e:
        return jsonify({"message": "Error saving user", "error": str(e)}), 400
    finally:
        conn.close()

    # 4. Send the success message and token back to Android
    return jsonify({
        "token": session_token,
        "message": "User registered and saved successfully!"
    }), 200

# 5. Starts the server
if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)