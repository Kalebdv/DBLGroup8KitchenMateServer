from flask import Flask, request, jsonify
import psycopg2
import uuid
import os
import json

app = Flask(__name__)

# The URL to the database is sensitive, so we get it from an environment variable we set in the server host
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/fallback")

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT role, session_token FROM users WHERE email = %s AND password = %s",
            (email, password)
        )
        user = cur.fetchone()

        if not user:
            return jsonify({"message": "Invalid email or password"}), 401

        return jsonify({
            "token": user[1],
            "role": user[0],
            "message": "Login successful"
        }), 200

    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()
















@app.route('/', methods=['GET'])
def health_check():
    # this should show when opening the link in the browser so we can see if the server is running correcrtly
    return "KitchenMate Server is Awake and Running", 200

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
            password TEXT NOT NULL,
            session_token TEXT
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()
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
        "message": "User registered and saved successfully"
    }), 200

@app.route('/api/recipes', methods=['GET'])
def get_recipes():
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT id, name, description, ingredients_json, instructions_json
            FROM recipes
            ORDER BY name ASC
        """)
        rows = cur.fetchall()

        recipes = []
        for row in rows:
            recipes.append({
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "requiredIngredients": json.loads(row[3]),
                "instructions": json.loads(row[4])
            })

        return jsonify(recipes), 200

    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
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
    if not user_id: return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json()
    emoji = data.get('emoji', '📦')
    name = data.get('name')
    amount = float(data.get('amount', 1.0))
    unit = data.get('unit', 'pcs')
    expires = data.get('expires', '')
    
    # A flag from Android telling us to overwrite the unit anyway
    force_update = data.get('force_update', False) 

    if not name: return jsonify({"message": "Item name is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Search for an existing item with the exact same name for this user
        cur.execute(
            "SELECT id, amount, unit FROM inventories WHERE LOWER(name) = LOWER(%s) AND user_id = %s AND expires = %s", 
            (name, user_id, expires)
        )
        existing_item = cur.fetchone()

        if existing_item:
            item_id, existing_amount, existing_unit = existing_item
            
            # If units don't match and the user hasn't explicitly forced it, throw a warning instead of combining
            if existing_unit != unit and not force_update:
                return jsonify({"error": "UNIT_MISMATCH", "message": f"Unit mismatch for {name}."}), 409
            
            # Add the new amount to the old amount
            new_amount = float(existing_amount) + amount
            
            # Overwrite the row with the combined amount, the (potentially new) unit, and the newest expiry date
            cur.execute(
                "UPDATE inventories SET amount = %s, unit = %s, expires = %s, emoji = %s WHERE id = %s",
                (new_amount, unit, expires, emoji, item_id)
            )
            conn.commit()
            return jsonify({"message": f"Combined! You now have {new_amount} {unit} of {name}."}), 200
        else:
            # It's a brand new item, so we just insert it normally
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
                "amount": row[3],
                "unit": row[4],
                "expires": row[5]
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

# This route is pretty much a more elaborate version of the delete route with some extra logic for nice features we wanted 
# specifically to remove only a certain amount of an item from the inventory instead of the whole item
@app.route('/api/inventory/consume/<int:item_id>', methods=['POST'])
def consume_inventory_item(item_id):
    user_id = get_user_id_from_request()
    if not user_id:
        # If the token is invalid or expired, we won't know which user is making the request, so we return an unauthorized error
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json()
    amount_to_remove = float(data.get('amount_to_consume', 0.0))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Look up the current item
        cur.execute("SELECT amount, unit FROM inventories WHERE id = %s AND user_id = %s", (item_id, user_id))
        item = cur.fetchone()

        if not item:
            return jsonify({"message": "Item not found"}), 404

        current_amount = float(item[0])
        current_unit = item[1]

        # Do the math to figure out how much is left after consuming the specified amount
        new_amount = current_amount - amount_to_remove

        # Decide whether to fully delete the item (if it's all consumed) or update it with the new remaining amount
        if new_amount < 0.001: # 0.001 to avoid issues with floating point errors without interfering with unit conversion that happens below
            # All consumed so we delete the row from the database
            cur.execute("DELETE FROM inventories WHERE id = %s", (item_id,))
            conn.commit()
            return jsonify({"message": "Item fully consumed", "action": "deleted"}), 200
        else:
            new_unit = current_unit
            
            # For kg unit we want to update it to grams if it becomes less than 1. Same goes for Liters
            if current_unit == 'kg' and new_amount < 1.0:
                new_amount = new_amount * 1000
                new_unit = 'g'
            elif current_unit == 'L' and new_amount < 1.0:
                new_amount = new_amount * 1000
                new_unit = 'ml'

            # Update the row with the remaining food
            cur.execute("UPDATE inventories SET amount = %s, unit = %s WHERE id = %s", (new_amount, new_unit, item_id))
            conn.commit()
            return jsonify({"message": "Inventory updated", "action": "updated"}), 200

    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

# This route allows the app to update just the expiration date of an item so the user can easily change this
@app.route('/api/inventory/update_expiry/<int:item_id>', methods=['PATCH'])
def update_expiry(item_id):
    user_id = get_user_id_from_request()
    if not user_id: return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json()
    new_expires = data.get('expires', '')

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Update just the expiration date for this specific item
        cur.execute(
            "UPDATE inventories SET expires = %s WHERE id = %s AND user_id = %s",
            (new_expires, item_id, user_id)
        )
        conn.commit()
        
        if cur.rowcount == 0:
            return jsonify({"message": "Item not found"}), 404
            
        return jsonify({"message": "Expiration date updated", "new_date": new_expires}), 200
    except Exception as e:
        return jsonify({"message": "Database error", "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    # Grab the port the server host provides
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', debug=False, port=port)