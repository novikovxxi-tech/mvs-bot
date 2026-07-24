from flask import Flask, request, jsonify
from flask_cors import CORS
import secrets
import hashlib
import psycopg2, psycopg2.extras, os
import boto3
from botocore.client import Config

app = Flask(__name__)
CORS(app)

DATABASE_URL = os.environ.get('DATABASE_URL', '')

# Yandex Object Storage config
S3 = boto3.client(
    's3',
    endpoint_url='https://storage.yandexcloud.net',
    aws_access_key_id=os.environ.get('YC_ACCESS_KEY', ''),
    aws_secret_access_key=os.environ.get('YC_SECRET_KEY', ''),
    config=Config(signature_version='s3v4'),
    region_name='ru-central1'
)
S3_BUCKET = 'mvs-upd'

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

    # ── ЭТАП 0: РОЛИ И ОТДЕЛЫ (хотелка №1) ──
    # Справочник отделов: МТО, ПТО, бухгалтерия, НУ, руководитель.
    cur.execute('''
        CREATE TABLE IF NOT EXISTS departments (
            id SERIAL PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL
        );
    ''')
    for code, dname in [('MTO','МТО'),('PTO','ПТО'),('BUH','Бухгалтерия'),
                        ('NU','Начальник участка'),('RUK','Руководитель')]:
        cur.execute('INSERT INTO departments (code, name) VALUES (%s,%s) ON CONFLICT (code) DO NOTHING', (code, dname))
    # Добавляем роль и отдел к пользователям (обратно совместимо).
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'executor';")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS department_code TEXT DEFAULT '';")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT DEFAULT '';")

    # ── ЭТАП 0: ПЛАН/ФАКТ И СТАТУСЫ в entries (хотелки №2 и №6) ──
    # Ключевой принцип AVTOBAN: план задаётся сверху, факт вводит исполнитель,
    # отклонение = факт − план считается автоматически.
    cur.execute("ALTER TABLE entries ADD COLUMN IF NOT EXISTS vol_plan REAL DEFAULT 0;")
    cur.execute("ALTER TABLE entries ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'draft';")
    # deviation — вычисляемое поле (факт vol − план vol_plan).
    cur.execute('''
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='entries' AND column_name='deviation') THEN
                ALTER TABLE entries ADD COLUMN deviation REAL GENERATED ALWAYS AS (vol - vol_plan) STORED;
            END IF;
        END $$;
    ''')

    # ── ЭТАП 0: ФОТОФИКСАЦИЯ ──
    # Привязка фото к любой сущности (entry / machine / repair). Файлы — в Yandex S3.
    cur.execute('''
        CREATE TABLE IF NOT EXISTS photos (
            id SERIAL PRIMARY KEY,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            s3_key TEXT NOT NULL,
            file_name TEXT NOT NULL,
            uploaded_by TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')

    # ── ЭТАП 0: ЗАЯВКИ НА РЕМОНТ ТЕХНИКИ (хотелка №4) ──
    cur.execute('''
        CREATE TABLE IF NOT EXISTS repair_requests (
            id SERIAL PRIMARY KEY,
            machine_name TEXT NOT NULL,
            gov_number TEXT DEFAULT '',
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'created',
            created_by TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP
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
    # Таблица УПД файлов
    cur.execute('''
        CREATE TABLE IF NOT EXISTS upd_files (
            id SERIAL PRIMARY KEY,
            entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
            file_url TEXT NOT NULL,
            file_name TEXT NOT NULL,
            public_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

# ВАЖНО (этап 0, безопасность): пароль администратора больше не хранится в коде.
# Задайте переменную окружения ADMIN_PASSWORD на хостинге (Amvera).
# PWD_SALT — секретная соль для хеширования паролей пользователей.
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')
PWD_SALT = os.environ.get('PWD_SALT', 'mvs-legacy-salt-change-me')

def hash_pw(pw):
    # Соль защищает от подбора по радужным таблицам. Старые (несолёные) хеши
    # проверяются через hash_pw_legacy для обратной совместимости.
    return hashlib.sha256((PWD_SALT + pw).encode()).hexdigest()

def hash_pw_legacy(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def check_admin(req):
    # Единая проверка админ-доступа. Если ADMIN_PASSWORD не задан на сервере —
    # доступ закрыт (безопасное поведение по умолчанию).
    return bool(ADMIN_PASSWORD) and req.headers.get('X-Admin-Password') == ADMIN_PASSWORD

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
    # Поддерживаем новый (солёный) и старый формат хеша — чтобы существующие пользователи не потеряли доступ.
    cur.execute('SELECT id, name, is_active, password_hash FROM users WHERE login=%s', (login,))
    row = cur.fetchone()
    if not row or row[3] not in (hash_pw(password), hash_pw_legacy(password)):
        cur.close(); conn.close()
        return jsonify({'ok': False, 'error': 'Неверный логин или пароль'}), 401
    if not row[2]:
        cur.close(); conn.close()
        return jsonify({'ok': False, 'error': 'Доступ заблокирован'}), 403
    # Мягкая миграция: если хеш старого формата — пересчитываем на солёный при входе.
    if row[3] == hash_pw_legacy(password):
        cur.execute('UPDATE users SET password_hash=%s WHERE id=%s', (hash_pw(password), row[0]))
        conn.commit()
    cur.close()
    conn.close()
    return jsonify({'ok': True, 'name': row[1], 'login': login})

@app.route('/api/auth/users', methods=['GET'])
def auth_users():
    if not check_admin(request):
        return jsonify({'error': 'Forbidden'}), 403
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT id, name, login, is_active, created_at, role, department_code, phone FROM users ORDER BY id')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{'id': r[0], 'name': r[1], 'login': r[2], 'is_active': r[3], 'created_at': str(r[4]),
                     'role': r[5], 'department_code': r[6], 'phone': r[7]} for r in rows])

@app.route('/api/auth/users', methods=['POST'])
def auth_create_user():
    if not check_admin(request):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json or {}
    name = data.get('name', '').strip()
    login = data.get('login', '').strip().lower()
    if not name or not login:
        return jsonify({'error': 'name and login required'}), 400
    role = data.get('role', 'executor').strip() or 'executor'
    department_code = data.get('department_code', '').strip()
    phone = data.get('phone', '').strip()
    password = gen_password()
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO users (name, login, password_hash, role, department_code, phone) VALUES (%s, %s, %s, %s, %s, %s)',
                    (name, login, hash_pw(password), role, department_code, phone))
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
    if not check_admin(request):
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
    if not check_admin(request):
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

# ── УПД файлы ─────────────────────────────────────

@app.route('/api/upd/<int:entry_id>', methods=['GET'])
def get_upd(entry_id):
    conn = get_db()
    cur = conn.cursor(psycopg2.extras.RealDictCursor)
    cur.execute('SELECT id, file_url, file_name, public_id, created_at FROM upd_files WHERE entry_id=%s ORDER BY created_at', (entry_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d['file_url'] = S3.generate_presigned_url('get_object', Params={'Bucket': S3_BUCKET, 'Key': d['public_id']}, ExpiresIn=86400)
        except Exception:
            pass
        result.append(d)
    return jsonify(result)

@app.route('/api/upd/<int:entry_id>', methods=['POST'])
def upload_upd(entry_id):
    if 'file' not in request.files:
        return jsonify({'error': 'no file'}), 400
    f = request.files['file']
    import uuid
    ext = f.filename.rsplit('.', 1)[-1] if '.' in f.filename else 'bin'
    key = f'mvs_upd/{entry_id}/{uuid.uuid4().hex}.{ext}'
    try:
        S3.upload_fileobj(f, S3_BUCKET, key, ExtraArgs={'ContentType': f.content_type or 'application/octet-stream'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    # Генерируем подписанную URL на 24 часа
    url = S3.generate_presigned_url('get_object', Params={'Bucket': S3_BUCKET, 'Key': key}, ExpiresIn=86400)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO upd_files (entry_id, file_url, file_name, public_id) VALUES (%s, %s, %s, %s) RETURNING id',
        (entry_id, key, f.filename, key)
    )
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'id': new_id, 'file_url': url, 'file_name': f.filename}), 201

@app.route('/api/upd/file/<int:file_id>', methods=['DELETE'])
def delete_upd(file_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT public_id FROM upd_files WHERE id=%s', (file_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return jsonify({'error': 'not found'}), 404
    try:
        S3.delete_object(Bucket=S3_BUCKET, Key=row[0])
    except Exception:
        pass
    cur.execute('DELETE FROM upd_files WHERE id=%s', (file_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'ok': True})

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
        'INSERT INTO entries (date, street, type, vol, shift, note, responsible, worktype, vol_plan, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
        (d['date'], d['street'], d['type'], float(d['vol']),
         d.get('shift', 'День'), d.get('note', ''), d.get('responsible', ''), d.get('worktype', ''),
         float(d.get('vol_plan', 0) or 0), d.get('status', 'draft'))
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
        'UPDATE entries SET date=%s, vol=%s, type=%s, shift=%s, note=%s, responsible=%s, worktype=%s, vol_plan=%s, status=%s WHERE id=%s',
        (d['date'], float(d['vol']), d.get('type', 'МЗВ'),
         d.get('shift', 'День'), d.get('note', ''), d.get('responsible', ''), d.get('worktype', ''),
         float(d.get('vol_plan', 0) or 0), d.get('status', 'draft'), entry_id)
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

# ── ЭТАП 0: Отделы ──────────────────────────────

@app.route('/api/departments', methods=['GET'])
def get_departments():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT code, name FROM departments ORDER BY id')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{'code': r[0], 'name': r[1]} for r in rows])

# ── ЭТАП 0: Заявки на ремонт техники (хотелка №4) ──

@app.route('/api/repair-requests', methods=['GET'])
def get_repair_requests():
    status = request.args.get('status')
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if status:
        cur.execute('SELECT * FROM repair_requests WHERE status=%s ORDER BY id DESC', (status,))
    else:
        cur.execute('SELECT * FROM repair_requests ORDER BY id DESC')
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(rows)

@app.route('/api/repair-requests', methods=['POST'])
def add_repair_request():
    d = request.json or {}
    if not d.get('machine_name'):
        return jsonify({'error': 'machine_name required'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO repair_requests (machine_name, gov_number, description, status, created_by) VALUES (%s,%s,%s,%s,%s) RETURNING id',
        (d['machine_name'], d.get('gov_number', ''), d.get('description', ''),
         d.get('status', 'created'), d.get('created_by', ''))
    )
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'ok': True, 'id': new_id}), 201

@app.route('/api/repair-requests/<int:rid>', methods=['PATCH'])
def update_repair_request(rid):
    d = request.json or {}
    status = d.get('status')
    if status not in ('created', 'in_progress', 'done'):
        return jsonify({'error': 'bad status'}), 400
    conn = get_db()
    cur = conn.cursor()
    if status == 'done':
        cur.execute("UPDATE repair_requests SET status=%s, closed_at=CURRENT_TIMESTAMP WHERE id=%s", (status, rid))
    else:
        cur.execute("UPDATE repair_requests SET status=%s, closed_at=NULL WHERE id=%s", (status, rid))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'ok': True})

# ── ЭТАП 0: Фотофиксация (универсальная) ──

@app.route('/api/photos/<entity_type>/<int:entity_id>', methods=['GET'])
def get_photos(entity_type, entity_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('SELECT id, s3_key, file_name, uploaded_by, created_at FROM photos WHERE entity_type=%s AND entity_id=%s ORDER BY created_at',
                (entity_type, entity_id))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = []
    for r in rows:
        dd = dict(r)
        try:
            dd['url'] = S3.generate_presigned_url('get_object', Params={'Bucket': S3_BUCKET, 'Key': dd['s3_key']}, ExpiresIn=86400)
        except Exception:
            pass
        result.append(dd)
    return jsonify(result)

@app.route('/api/photos/<entity_type>/<int:entity_id>', methods=['POST'])
def upload_photo(entity_type, entity_id):
    if 'file' not in request.files:
        return jsonify({'error': 'no file'}), 400
    f = request.files['file']
    import uuid
    ext = f.filename.rsplit('.', 1)[-1] if '.' in f.filename else 'jpg'
    key = f'photos/{entity_type}/{entity_id}/{uuid.uuid4().hex}.{ext}'
    try:
        S3.upload_fileobj(f, S3_BUCKET, key, ExtraArgs={'ContentType': f.content_type or 'image/jpeg'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT INTO photos (entity_type, entity_id, s3_key, file_name, uploaded_by) VALUES (%s,%s,%s,%s,%s) RETURNING id',
                (entity_type, entity_id, key, f.filename, (request.form.get('uploaded_by', ''))))
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    url = S3.generate_presigned_url('get_object', Params={'Bucket': S3_BUCKET, 'Key': key}, ExpiresIn=86400)
    return jsonify({'ok': True, 'id': new_id, 'url': url}), 201

# ── ЭТАП 0: Дашборд отклонений (план/факт) ──

@app.route('/api/dashboard', methods=['GET'])
def get_dashboard():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('SELECT street, type, vol, vol_plan, deviation, status FROM entries')
    rows = [dict(r) for r in cur.fetchall()]
    # Открытые заявки на ремонт
    cur.execute("SELECT COUNT(*) FROM repair_requests WHERE status <> 'done'")
    open_repairs = cur.fetchone()['count'] if cur.rowcount else 0
    cur.close()
    conn.close()
    total_plan = round(sum((e['vol_plan'] or 0) for e in rows), 2)
    total_fact = round(sum((e['vol'] or 0) for e in rows), 2)
    total_dev = round(total_fact - total_plan, 2)
    # Экономия (факт < план) / перерасход (факт > план)
    economy = round(sum(-(e['deviation'] or 0) for e in rows if (e['deviation'] or 0) < 0), 2)
    overrun = round(sum((e['deviation'] or 0) for e in rows if (e['deviation'] or 0) > 0), 2)
    return jsonify({
        'total_plan': total_plan,
        'total_fact': total_fact,
        'total_deviation': total_dev,
        'economy': economy,
        'overrun': overrun,
        'open_repairs': open_repairs,
    })

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
