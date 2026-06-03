from fastapi import FastAPI, WebSocket, Body, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import json, sqlite3, asyncio, socket, hashlib, secrets
from datetime import datetime

app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

DB = 'tunapos.db'

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    # MENU ITEMS — full restaurant menu
    c.execute('''CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, price REAL NOT NULL,
        category TEXT, department TEXT,
        description TEXT, sku TEXT,
        cost REAL DEFAULT 0, active INTEGER DEFAULT 1,
        ai_pick INTEGER DEFAULT 0, surge INTEGER DEFAULT 0,
        emoji TEXT DEFAULT "🍽️"
    )''')

    # ORDERS
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        items TEXT NOT NULL, total REAL NOT NULL,
        subtotal REAL DEFAULT 0, tax REAL DEFAULT 0, tip REAL DEFAULT 0,
        table_num TEXT DEFAULT "T-1",
        server_id INTEGER DEFAULT 1,
        payment_method TEXT DEFAULT "card",
        payment_status TEXT DEFAULT "pending",
        status TEXT DEFAULT "pending",
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        offline_id TEXT
    )''')

    # STAFF & ROLES
    c.execute('''CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        role TEXT DEFAULT "server",
        pin TEXT NOT NULL,
        pin_hash TEXT,
        active INTEGER DEFAULT 1,
        hourly_rate REAL DEFAULT 16.0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')

    # SESSIONS — track who is logged in at terminal
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER,
        token TEXT UNIQUE,
        clock_in DATETIME DEFAULT CURRENT_TIMESTAMP,
        clock_out DATETIME,
        active INTEGER DEFAULT 1
    )''')

    # RECEIPT CONFIG per client
    c.execute('''CREATE TABLE IF NOT EXISTS receipt_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_name TEXT DEFAULT "My Restaurant",
        business_address TEXT,
        business_phone TEXT,
        tax_rate REAL DEFAULT 0.08,
        tip_enabled INTEGER DEFAULT 1,
        logo_url TEXT,
        config_json TEXT
    )''')

    # Seed menu if empty
    c.execute('SELECT COUNT(*) FROM items')
    if c.fetchone()[0] == 0:
        menu = [
            # Kitchen / Steaks
            ("Ribeye 8oz","STK-8","kitchen","Steak",28.00,12.50,"🥩","Prime USDA cut, pan-seared",1,0),
            ("NY Strip 12oz","STK-12","kitchen","Steak",38.00,16.00,"🥩","Slow-roasted, market price",0,1),
            ("Grilled Chicken","MAIN-CHK","kitchen","Kitchen",18.00,4.20,"🍗","Herb-marinated breast",0,0),
            ("Pasta Carbonara","MAIN-PST","kitchen","Kitchen",16.00,2.80,"🍝","Guanciale, pecorino, egg",0,0),
            ("Salmon Filet","MAIN-SAL","kitchen","Kitchen",24.00,9.50,"🐟","Pan-seared, lemon butter",1,0),
            ("Veggie Stir Fry","MAIN-VEG","kitchen","Kitchen",14.00,2.10,"🥦","Seasonal veg, wok",0,0),
            ("Prime Rib 12oz","STK-PR","kitchen","Steak",42.00,18.00,"🥩","Slow-roasted, au jus",0,1),
            ("Grilled Salmon","MAIN-GS","kitchen","Kitchen",26.00,10.00,"🐟","Atlantic salmon, herb butter",0,0),
            # Bar
            ("Old Fashioned","BAR-OF","bar","Bar",12.00,2.20,"🥃","Bourbon, bitters, orange",1,0),
            ("Classic Margarita","BAR-MAR","bar","Bar",11.00,1.80,"🍹","Lime, triple sec, salt rim",0,0),
            ("Mojito","BAR-MOJ","bar","Bar",10.00,1.60,"🌿","Rum, mint, lime, soda",0,0),
            ("Negroni","BAR-NEG","bar","Bar",13.00,2.50,"🍊","Gin, Campari, vermouth",1,0),
            ("Draft Beer","BAR-BEER","bar","Bar",6.00,1.20,"🍺","Local craft on tap",0,1),
            ("House Red Wine","BAR-WINE","bar","Bar",9.00,2.50,"🍷","Glass or carafe",0,0),
            ("Espresso Martini","BAR-EM","bar","Bar",14.00,2.80,"☕","Vodka, espresso, Kahlua",0,1),
            ("Whiskey Sour","BAR-WS","bar","Bar",11.00,2.00,"🥃","Bourbon, lemon, egg white",0,0),
            # Sushi
            ("Spicy Tuna Roll","SUS-SP","sushi","Sushi",11.00,3.80,"🍣","Sushi-grade, spicy mayo",1,0),
            ("California Roll","SUS-CA","sushi","Sushi",9.50,3.20,"🍱","Crab, avocado, cucumber",0,0),
            ("Dragon Roll","SUS-DR","sushi","Sushi",14.00,5.50,"🐉","Shrimp tempura, avocado",0,1),
            ("Salmon Sashimi 5pc","SUS-SAL","sushi","Sushi",16.00,6.50,"🐟","Daily catch",0,0),
            ("Omakase Platter","SUS-OMA","sushi","Sushi",45.00,18.00,"🍱","Chef's choice, premium",1,1),
            # Coffee
            ("Cappuccino","COF-CAP","coffee","Coffee",4.00,0.90,"☕","Double shot, micro foam",1,0),
            ("Cold Brew","COF-CB","coffee","Coffee",5.00,0.80,"🧋","18hr steep, ice",0,0),
            ("Latte","COF-LAT","coffee","Coffee",4.50,0.85,"☕","Espresso, steamed milk",0,0),
            ("Matcha Latte","COF-MAT","coffee","Coffee",6.00,1.20,"🍵","Ceremonial grade, oat milk",0,0),
            ("Affogato","COF-AFF","coffee","Coffee",7.00,1.50,"🍨","Espresso over gelato",1,0),
            # Brunch
            ("Eggs Benedict","BR-EB","brunch","Brunch",16.00,4.50,"🍳","Hollandaise, Canadian bacon",0,0),
            ("Avocado Toast","BR-AVT","brunch","Brunch",12.00,2.40,"🥑","Sourdough, burrata, EVOO",1,0),
            ("Pancake Stack","BR-PAN","brunch","Brunch",11.00,2.00,"🥞","Buttermilk, maple, berry",0,0),
            ("Mimosa","BR-MIM","brunch","Brunch",9.00,1.80,"🥂","Bottomless available",0,0),
        ]
        for name,sku,dept,cat,price,cost,emoji,desc,ai,surge in menu:
            c.execute('INSERT INTO items (name,sku,department,category,price,cost,emoji,description,ai_pick,surge,active) VALUES (?,?,?,?,?,?,?,?,?,?,1)',
                     (name,sku,dept,cat,price,cost,emoji,desc,ai,surge))

    # Seed staff if empty
    c.execute('SELECT COUNT(*) FROM staff')
    if c.fetchone()[0] == 0:
        def hash_pin(pin):
            return hashlib.sha256(pin.encode()).hexdigest()
        staff = [
            ("Owner",       "owner",      "1234", hash_pin("1234")),
            ("Manager",     "manager",    "5678", hash_pin("5678")),
            ("Alex Server", "server",     "1111", hash_pin("1111")),
            ("Maria Server","server",     "2222", hash_pin("2222")),
            ("Diego Bar",   "bartender",  "3333", hash_pin("3333")),
            ("Chef Carlos", "kitchen",    "4444", hash_pin("4444")),
        ]
        for name,role,pin,ph in staff:
            c.execute('INSERT INTO staff (name,role,pin,pin_hash,active) VALUES (?,?,?,?,1)',(name,role,pin,ph))

    conn.commit()
    conn.close()

init_db()

# WebSocket KDS
connected_kds = set()

# ─── MENU ENDPOINTS ───────────────────────────────────────────────
@app.get('/api/items')
async def get_items(department: str = None, category: str = None):
    conn = get_db()
    c = conn.cursor()
    if department:
        c.execute('SELECT * FROM items WHERE active=1 AND department=?', (department,))
    elif category:
        c.execute('SELECT * FROM items WHERE active=1 AND category=?', (category,))
    else:
        c.execute('SELECT * FROM items WHERE active=1 ORDER BY department,name')
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return {'items': rows}

@app.post('/api/items')
async def add_item(item: dict = Body(...)):
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO items (name,sku,department,category,price,cost,emoji,description,ai_pick,surge)
                 VALUES (?,?,?,?,?,?,?,?,?,?)''',
              (item.get('name'), item.get('sku',''), item.get('department','kitchen'),
               item.get('category','Kitchen'), item.get('price',0), item.get('cost',0),
               item.get('emoji','🍽️'), item.get('description',''),
               item.get('ai_pick',0), item.get('surge',0)))
    item_id = c.lastrowid
    conn.commit()
    conn.close()
    return {'id': item_id, 'status': 'created'}

@app.put('/api/items/{item_id}')
async def update_item(item_id: int, item: dict = Body(...)):
    conn = get_db()
    c = conn.cursor()
    c.execute('''UPDATE items SET name=?,price=?,cost=?,description=?,active=?,emoji=?
                 WHERE id=?''',
              (item.get('name'), item.get('price'), item.get('cost'),
               item.get('description'), item.get('active',1), item.get('emoji','🍽️'), item_id))
    conn.commit()
    conn.close()
    return {'status': 'updated'}

@app.delete('/api/items/{item_id}')
async def delete_item(item_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE items SET active=0 WHERE id=?', (item_id,))
    conn.commit()
    conn.close()
    return {'status': 'deleted'}

# ─── STAFF / PIN AUTH ─────────────────────────────────────────────
ROLE_PERMISSIONS = {
    'owner':      {'discount_max':100,'void':True,'comp':True,'reports':True,'backoffice':True,'refund':True,'close_day':True,'edit_menu':True},
    'manager':    {'discount_max':25, 'void':True,'comp':True,'reports':True,'backoffice':True,'refund':True,'close_day':True,'edit_menu':True},
    'shift_lead': {'discount_max':15, 'void':True,'comp':False,'reports':'today','backoffice':False,'refund':False,'close_day':False,'edit_menu':False},
    'server':     {'discount_max':10, 'void':False,'comp':False,'reports':'own','backoffice':False,'refund':False,'close_day':False,'edit_menu':False},
    'bartender':  {'discount_max':10, 'void':False,'comp':False,'reports':'own','backoffice':False,'refund':False,'close_day':False,'edit_menu':False},
    'kitchen':    {'discount_max':0,  'void':False,'comp':False,'reports':False,'backoffice':False,'refund':False,'close_day':False,'edit_menu':False},
    'trainee':    {'discount_max':0,  'void':False,'comp':False,'reports':False,'backoffice':False,'refund':False,'close_day':False,'edit_menu':False},
}

@app.post('/api/staff/pin-login')
async def pin_login(data: dict = Body(...)):
    pin = str(data.get('pin',''))
    pin_hash = hashlib.sha256(pin.encode()).hexdigest()
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM staff WHERE (pin=? OR pin_hash=?) AND active=1', (pin, pin_hash))
    staff = c.fetchone()
    if not staff:
        conn.close()
        raise HTTPException(status_code=401, detail='Invalid PIN')
    staff = dict(staff)
    # Create session token
    token = secrets.token_hex(16)
    c.execute('UPDATE sessions SET active=0 WHERE staff_id=?', (staff['id'],))
    c.execute('INSERT INTO sessions (staff_id,token,active) VALUES (?,?,1)', (staff['id'],token))
    conn.commit()
    conn.close()
    perms = ROLE_PERMISSIONS.get(staff['role'], ROLE_PERMISSIONS['server'])
    return {
        'token': token,
        'staff': {'id':staff['id'],'name':staff['name'],'role':staff['role']},
        'permissions': perms
    }

@app.get('/api/staff')
async def get_staff():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id,name,role,active FROM staff ORDER BY role,name')
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return {'staff': rows}

@app.post('/api/staff')
async def add_staff(data: dict = Body(...)):
    conn = get_db()
    c = conn.cursor()
    pin = str(data.get('pin','0000'))
    pin_hash = hashlib.sha256(pin.encode()).hexdigest()
    c.execute('INSERT INTO staff (name,role,pin,pin_hash,hourly_rate) VALUES (?,?,?,?,?)',
              (data.get('name'),data.get('role','server'),pin,pin_hash,data.get('hourly_rate',16.0)))
    staff_id = c.lastrowid
    conn.commit()
    conn.close()
    return {'id': staff_id, 'status': 'created'}

# ─── ORDERS ───────────────────────────────────────────────────────
@app.post('/api/orders/create')
async def create_order(order_data: dict = Body(...)):
    conn = get_db()
    c = conn.cursor()
    items_json = json.dumps(order_data.get('items', []))
    total = order_data.get('total', 0)
    subtotal = order_data.get('subtotal', total)
    tax = order_data.get('tax', 0)
    tip = order_data.get('tip', 0)
    table_num = order_data.get('table', 'T-1')
    server_id = order_data.get('server_id', 1)
    payment_method = order_data.get('payment_method', 'card')
    offline_id = order_data.get('offline_id', None)

    c.execute('''INSERT INTO orders (items,total,subtotal,tax,tip,table_num,server_id,payment_method,offline_id,status)
                 VALUES (?,?,?,?,?,?,?,?,?,'sent')''',
              (items_json,total,subtotal,tax,tip,table_num,server_id,payment_method,offline_id))
    order_id = c.lastrowid
    conn.commit()
    conn.close()

    # Broadcast to KDS
    order_msg = {
        'type': 'new_order',
        'order_id': order_id,
        'table': table_num,
        'items': order_data.get('items', []),
        'total': total,
        'timestamp': datetime.now().isoformat()
    }
    dead = set()
    for client in connected_kds:
        try:
            await client.send_text(json.dumps(order_msg))
        except:
            dead.add(client)
    connected_kds -= dead

    return {'order_id': order_id, 'status': 'created'}

@app.get('/api/orders')
async def get_orders(limit: int = 50, server_id: int = None):
    conn = get_db()
    c = conn.cursor()
    if server_id:
        c.execute('SELECT * FROM orders WHERE server_id=? ORDER BY timestamp DESC LIMIT ?', (server_id, limit))
    else:
        c.execute('SELECT * FROM orders ORDER BY timestamp DESC LIMIT ?', (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return {'orders': rows}

@app.get('/api/orders/summary')
async def get_summary():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as count, SUM(total) as revenue, SUM(tax) as tax FROM orders WHERE DATE(timestamp)=DATE('now')")
    row = dict(c.fetchone())
    conn.close()
    return row

# ─── PRINT ────────────────────────────────────────────────────────
@app.post('/api/print/vocora')
async def print_vocora(data: dict = Body(...)):
    try:
        items = data.get('items', [])
        total = data.get('total', 0)
        subtotal = data.get('subtotal', total)
        tax = data.get('tax', 0)
        tip = data.get('tip', 0)
        table = data.get('table', 'T-1')
        server = data.get('server', 'Server')
        timestamp = data.get('timestamp', datetime.now().strftime('%m/%d/%Y %I:%M %p'))
        order_id = data.get('order_id', '----')

        receipt = b'\x1b\x40'  # Init
        receipt += b'\x1b\x61\x01'  # Center
        receipt += b'\x1b\x45\x01'  # Bold on
        receipt += b'TUNAPOS\n'
        receipt += b'\x1b\x45\x00'  # Bold off
        receipt += b'Pioneer Enterprise Solutions\n'
        receipt += b'================================\n'
        receipt += f'Table: {table}    Server: {server}\n'.encode()
        receipt += f'Order: #{order_id}\n'.encode()
        receipt += f'{timestamp}\n'.encode()
        receipt += b'================================\n'
        receipt += b'\x1b\x61\x00'  # Left align

        for item in items:
            name = str(item.get('name','Item'))[:22]
            price = item.get('price', 0)
            qty = item.get('qty', 1)
            line = f'{qty}x {name:<20} ${price*qty:>7.2f}\n'
            receipt += line.encode()

        receipt += b'--------------------------------\n'
        receipt += f'{"Subtotal":<24} ${subtotal:>7.2f}\n'.encode()
        if tax: receipt += f'{"Tax (8%)":<24} ${tax:>7.2f}\n'.encode()
        if tip: receipt += f'{"Tip":<24} ${tip:>7.2f}\n'.encode()
        receipt += b'================================\n'
        receipt += b'\x1b\x45\x01'
        receipt += f'{"TOTAL":<24} ${total:>7.2f}\n'.encode()
        receipt += b'\x1b\x45\x00'
        receipt += b'================================\n'
        receipt += b'\x1b\x61\x01'  # Center
        receipt += b'Thank you for dining with us!\n'
        receipt += b'Powered by TunaPOS\n\n\n'
        receipt += b'\x1d\x56\x00'  # Full cut

        sock = socket.socket()
        sock.settimeout(5)
        sock.connect(('10.0.0.2', 9100))
        sock.sendall(receipt)
        sock.close()
        return {'status': 'printed', 'message': 'Receipt sent to Volcora 10.0.0.2:9100'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

# ─── WEBSOCKET KDS ────────────────────────────────────────────────
@app.websocket('/ws/kitchen')
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_kds.add(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(json.dumps({'type':'pong','ts':datetime.now().isoformat()}))
    except:
        connected_kds.discard(websocket)

@app.get('/')
async def root():
    return {'status': 'TunaPOS Backend v2', 'version': '2.0', 'endpoints': ['/api/items','/api/orders','/api/staff','/api/print/vocora']}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8035)
