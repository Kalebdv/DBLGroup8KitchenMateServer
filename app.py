from flask import Flask, request, jsonify
import psycopg2
import uuid
import os

app = Flask(__name__)

# The URL to the database is sensitive, so we get it from an environment variable we set in the server host
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/fallback")

@app.route('/', methods=['GET'])
def health_check():
    # this should show when opening the link in the browser so we can see if the server is running correcrtly
    return "🟢 KitchenMate Server is Awake and Running!", 200

def get_db_connection():
    # Returns a connection to the cloud database
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

# Run database setup on startup
# init_db() only necessary if the table doesn't exist yet

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    role = data.get('role')
    password = data.get('password') 
    
    # Generate a session token to send back to Android
    session_token = f"kitchenmate_token_{uuid.uuid4().hex}"

    # Open the database connection using our helper function
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Save the sent values to the cloud database
        cur.execute(
            "INSERT INTO users (name, email, role, password, session_token) VALUES (%s, %s, %s, %s, %s)", 
            (name, email, role, password, session_token)
        )
        conn.commit()
        print(f"Success: Saved {name} to the cloud database")
    except Exception as e:
        # Since the email should be unique, this will catch attempts to register with an email that's already in use
        return jsonify({"message": "Error saving user", "error": str(e)}), 400
    finally:
        cur.close()
        conn.close()

    return jsonify({
        "token": session_token,
        "role": role,
        "message": "User registered and saved successfully!"
    }), 200

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    # Open the database connection
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Search for the user by email
        cur.execute("SELECT id, name, role, password FROM users WHERE email = %s", (email,))
        user = cur.fetchone() # Fetches the first matching row, or none if it doesn't exist

        # Check if the user exists and the password matches
        # user[3] is the password column from our SELECT statement above
        if user and user[3] == password:
            session_token = f"kitchenmate_token_{uuid.uuid4().hex}"
            
            # Update the user's row with their current session token
            cur.execute("UPDATE users SET session_token = %s WHERE id = %s", (session_token, user[0]))
            conn.commit()
            
            return jsonify({
                "token": session_token, 
                "role": user[2],
                "message": f"Welcome back, {user[1]}!" 
            }), 200
        else:
            # Fail: wrong email or password
            return jsonify({"message": "Invalid email or password"}), 401
            
    except Exception as e:
        return jsonify({"message": "Server error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

# From here we're mainly dealing with inventory management instead of authentication

# Helper function to extract the user_id from the request's Authorization header, which contains the session token
def get_user_id_from_request():
    # Android will send the token in the headers as "Bearer kitchenmate_token_123..."
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    
    token = auth_header.split(' ')[1] # Extracts just the token part
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE session_token = %s", (token,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    return user[0] if user else None # Returns the user_id, or None if the token is expired or shouldn't exist exist

# Route to send new inventory items fron the app to the database
@app.route('/api/inventory/add', methods=['POST'])
def add_inventory_item():
    user_id = get_user_id_from_request()
    if not user_id:
        return jsonify({"message": "Unauthorized. Please log in again."}), 401

    data = request.get_json()
    
    # Extract data sent from the android app and add default values to some fields
    emoji = data.get('emoji', '📦') # Default to a box emoji if not provided
    name = data.get('name')
    amount = data.get('amount', '1') # Default to an amount of 1 if not provided
    unit = data.get('unit', 'pcs') # Default to "pcs" (pieces) if no unit is provided
    expires = data.get('expires', '') 

    if not name:
        return jsonify({"message": "Item name is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO inventories (user_id, emoji, name, amount, unit, expires) VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, emoji, name, amount, unit, expires)
        )
        conn.commit()
        return jsonify({"message": f"Added {name} to your inventory!"}), 201
    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

# Route to fetch all inventory items belonging to the requesting user
@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    user_id = get_user_id_from_request()
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Fetch all inventory items for the user, ordered by creation time (newest first)
        cur.execute(
            "SELECT id, emoji, name, amount, unit, expires FROM inventories WHERE user_id = %s ORDER BY created_at DESC", 
            (user_id,)
        )
        rows = cur.fetchall()
        
        # Package the data EXACTLY how Kotlin expects it
        inventory_list = []
        for row in rows:
            inventory_list.append({
                "id": row[0],
                "emoji": row[1],
                "name": row[2],
                "quantity": row[3],
                "expires": row[4]
            })
            
        return jsonify(inventory_list), 200
    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/inventory/delete/<int:item_id>', methods=['DELETE'])
def delete_inventory_item(item_id):
    user_id = get_user_id_from_request()
    if not user_id:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Delete the item ONLY if it belongs to this user
        cur.execute("DELETE FROM inventories WHERE id = %s AND user_id = %s", (item_id, user_id))
        conn.commit()
        
        if cur.rowcount == 0:
            return jsonify({"message": "Item not found"}), 404
            
        return jsonify({"message": "Item deleted"}), 200
    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)