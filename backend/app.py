from flask import Flask, request, jsonify
from flask_cors import CORS
import secrets
import hashlib
import psycopg2, psycopg2.extras, os

app = Flask(__name__)
CORS(app)

DATABASE_URL = os.environ.get('DATABASE_URL', '')

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS streets (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        );
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS entries (
            id SERIAL PRIMARY KEY,
            date TEXT NOT NULL,
            street TEXT NOT NULL,
            type TEXT NOT NULL,
            vol REAL NOT NULL,
            shift TEXT NOT NULL,
            note TEXT,
            responsible TEXT DEFAULT '',
            worktype TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        ALTER TABLE entries ADD COLUMN IF NOT EXISTS responsible TEXT DEFAULT '';
        ALTER TABLE entries ADD COLUMN IF NOT EXISTS worktype TEXT DEFAULT '';
    ''')
    # Объекты из файла ulitsy_i_proezdy_po_okrugam.xlsx
    streets = [
        'Библиотечная ул.',
        'Калитниковский М. пр-д',
        'Машкова ул.',
        'Проезд вдоль Сахаровского центра',
        'Проезд от Новорогожской ул. до Рабочей ул, вл.93',
        'Проезд от улицы Радио до набережной Академика Туполева',
        'Стремянный пер.',
        'Сосинская ул',
        '2-й Варшавский проезд',
        '6-я линия Варшавского шоссе',
        'Варшавское ш., 37',
        'Колобашкина улица',
        'Корабельная улица',
        'Подольских курсантов ул., д.1 (парковка)',
        'Подъезд к заводу (в границах Ступинской улицы)',
        "Пр-д от Железнодорожного проезда к д.8а (завод 'Стройдеталь')",
        'Пр-д от Хлебозаводского проезда до проектируемого проезда №3716 (проезд вдоль домов 7 и 7а по Каширскому шоссе)',
        'Проезд от Варшавского ш. д.146 до Кировоградской улицы (подъездная дорога к универсаму № 70)',
        'Проезды Варшавского шоссе',
        'Проектируемый проезд №7024',
        'Ряжская улица',
        'улица Бехтерева',
        'улица Братьев Рябушинских',
        '8-я улица Текстильщиков',
        'Донецкая улица, д.40',
        "Подъездная дорога к 'ул. Кубанская д. 27'",
        'Проезд от ул. Перерва до Иловайской ул. (ул. Перерва 1с.1)',
        'Проезд № 2263',
        'Проезд № 5113',
        'Проезд №1481',
        'Ставропольский проезд',
        'проспект 40 лет Октября',
        'Железнодорожный проезд',
    ]
    for s in streets:
        try:
            cur.execute('INSERT INTO streets (name) VALUES (%s) ON CONFLICT (name) DO NOTHING', (s,))
        except Exception:
            pass

    # Таблица пользователей
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            login TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        );
    ''')

    # Таблица адресов заявок
    cur.execute('''
        CREATE TABLE IF NOT EXISTS order_sites (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        );
    ''')
    # Таблица материалов заявок
    cur.execute('''
        CREATE TABLE IF NOT EXISTS order_materials (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        );
    ''')
    # Таблица техники заявок
    cur.execute('''
        CREATE TABLE IF NOT EXISTS order_tech (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        );
    ''')
    conn.commit()
    cur.close()
    conn.close()

init_db()

# ── Улицы ──────────────────────────────────────────

@app.route('/api/streets/reset', methods=['POST'])
def reset_streets():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM streets')
    conn.commit()
    cur.close()
    conn.close()
    init_db()
    return jsonify({'ok': True})

@app.route('/api/streets', methods=['GET'])
def get_streets():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT name FROM streets ORDER BY id')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([r[0] for r in rows])

@app.route('/api/streets', methods=['POST'])
def add_street():
    name = (request.json or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT INTO streets (name) VALUES (%s) ON CONFLICT (name) DO NOTHING', (name,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'ok': True, 'name': name}), 201

# ── Авторизация ────────────────────────────────────

ADMIN_PASSWORD = 'z3d4xi2s'

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def gen_password():
    return secrets.token_urlsafe(6)

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data = request.json or {}
    login = data.get('login', '').strip().lower()
    password = data.get('password', '').strip()
    if not login or not password:
        return jsonify({'ok': False, 'error': 'Заполните все поля'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT id, name, is_active FROM users WHERE login=%s AND password_hash=%s', (login, hash_pw(password)))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return jsonify({'ok': False, 'error': 'Неверный логин или пароль'}), 401
    if not row[2]:
        return jsonify({'ok': False, 'error': 'Доступ заблокирован'}), 403
    return jsonify({'ok': True, 'name': row[1], 'login': login})

@app.route('/api/auth/users', methods=['GET'])
def auth_users():
    if request.headers.get('X-Admin-Password') != ADMIN_PASSWORD:
        return jsonify({'error': 'Forbidden'}), 403
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT id, name, login, is_active, created_at FROM users ORDER BY id')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{'id': r[0], 'name': r[1], 'login': r[2], 'is_active': r[3], 'created_at': str(r[4])} for r in rows])

@app.route('/api/auth/users', methods=['POST'])
def auth_create_user():
    if request.headers.get('X-Admin-Password') != ADMIN_PASSWORD:
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json or {}
    name = data.get('name', '').strip()
    login = data.get('login', '').strip().lower()
    if not name or not login:
        return jsonify({'error': 'name and login required'}), 400
    password = gen_password()
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO users (name, login, password_hash) VALUES (%s, %s, %s)',
                    (name, login, hash_pw(password)))
        conn.commit()
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({'error': 'Логин уже занят'}), 409
    cur.close()
    conn.close()
    return jsonify({'ok': True, 'name': name, 'login': login, 'password': password}), 201

@app.route('/api/auth/users/<int:uid>', methods=['DELETE'])
def auth_delete_user(uid):
    if request.headers.get('X-Admin-Password') != ADMIN_PASSWORD:
        return jsonify({'error': 'Forbidden'}), 403
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM users WHERE id=%s', (uid,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/auth/users/<int:uid>/toggle', methods=['POST'])
def auth_toggle_user(uid):
    if request.headers.get('X-Admin-Password') != ADMIN_PASSWORD:
        return jsonify({'error': 'Forbidden'}), 403
    conn = get_db()
    cur = conn.cursor()
    cur.execute('UPDATE users SET is_active = NOT is_active WHERE id=%s RETURNING is_active', (uid,))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'ok': True, 'is_active': row[0] if row else None})

# ── Адреса заявок ─────────────────────────────────

@app.route('/api/order-sites', methods=['GET'])
def get_order_sites():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT name FROM order_sites ORDER BY id')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([r[0] for r in rows])

@app.route('/api/order-sites', methods=['POST'])
def add_order_site():
    name = (request.json or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT INTO order_sites (name) VALUES (%s) ON CONFLICT (name) DO NOTHING', (name,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'ok': True, 'name': name}), 201

# ── Материалы заявок ───────────────────────────────

@app.route('/api/order-materials', methods=['GET'])
def get_order_materials():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT name FROM order_materials ORDER BY id')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([r[0] for r in rows])

@app.route('/api/order-materials', methods=['POST'])
def add_order_material():
    name = (request.json or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT INTO order_materials (name) VALUES (%s) ON CONFLICT (name) DO NOTHING', (name,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'ok': True, 'name': name}), 201

# ── Техника заявок ────────────────────────────────

@app.route('/api/order-tech', methods=['GET'])
def get_order_tech():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT name FROM order_tech ORDER BY id')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([r[0] for r in rows])

@app.route('/api/order-tech', methods=['POST'])
def add_order_tech():
    name = (request.json or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT INTO order_tech (name) VALUES (%s) ON CONFLICT (name) DO NOTHING', (name,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'ok': True, 'name': name}), 201

# ── Записи ─────────────────────────────────────────

@app.route('/api/entries', methods=['GET'])
def get_entries():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('SELECT * FROM entries ORDER BY date DESC, created_at DESC')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/entries', methods=['POST'])
def add_entry():
    d = request.json or {}
    if not all([d.get('date'), d.get('street'), d.get('type'), d.get('vol')]):
        return jsonify({'error': 'missing fields'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO entries (date, street, type, vol, shift, note, responsible, worktype) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
        (d['date'], d['street'], d['type'], float(d['vol']),
         d.get('shift', 'День'), d.get('note', ''), d.get('responsible', ''), d.get('worktype', ''))
    )
    entry_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'ok': True, 'id': entry_id}), 201

@app.route('/api/entries/<int:entry_id>', methods=['PUT'])
def update_entry(entry_id):
    d = request.json or {}
    if not all([d.get('date'), d.get('vol')]):
        return jsonify({'error': 'missing fields'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        'UPDATE entries SET date=%s, vol=%s, type=%s, shift=%s, note=%s, responsible=%s, worktype=%s WHERE id=%s',
        (d['date'], float(d['vol']), d.get('type', 'МЗВ'),
         d.get('shift', 'День'), d.get('note', ''), d.get('responsible', ''), d.get('worktype', ''), entry_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/entries/<int:entry_id>', methods=['DELETE'])
def delete_entry(entry_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM entries WHERE id = %s', (entry_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'ok': True})

# ── Статистика ─────────────────────────────────────

@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('SELECT * FROM entries')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    entries = [dict(r) for r in rows]

    total = sum(e['vol'] for e in entries)
    days = len(set(e['date'] for e in entries))
    avg = round(total / days, 2) if days else 0

    by_street = {}
    for e in entries:
        s = e['street']
        if s not in by_street:
            by_street[s] = {}
        t = e['type']
        by_street[s][t] = round(by_street[s].get(t, 0) + e['vol'], 2)

    return jsonify({
        'total': round(total, 2),
        'days': days,
        'avg': avg,
        'objects': len(by_street),
        'by_street': by_street
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
