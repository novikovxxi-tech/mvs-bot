from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3, os

app = Flask(__name__)
CORS(app)

DB = os.path.join(os.path.dirname(__file__), 'data.db')

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS streets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            street TEXT NOT NULL,
            type TEXT NOT NULL,
            vol REAL NOT NULL,
            shift TEXT NOT NULL,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    # Объекты 2026 года
    streets = [
        'Библиотечная ул.',
        'Калитниковский М. пр-д',
        'Машкова ул.',
        'Проезд вдоль Сахаровского центра',
        'Проезд от Новорогожской ул. до Рабочей ул, вл.93',
        'Проезд от улицы Радио до набережной Академика Туполева',
        'Сосинская ул',
        'Стремянный пер.',
        '2-й Варшавский проезд',
        '6-я линия Варшавского шоссе',
        'улица Бехтерева',
        'Железнодорожный проезд',
        'Пр-д от Железнодорожного проезда к д.8а (завод "Стройдеталь")',
        'Колобашкина улица',
        'Корабельная улица',
        'Подольских курсантов ул., д.1 (парковка)',
        'Подъезд к заводу (в границах Ступинской улицы)',
        'Пр-д от Хлебозаводского проезда до проектируемого проезда №3716 (проезд вдоль домов 7 и 7а по Каширскому шоссе)',
        'Варшавское ш., 37',
        'Проезд от Варшавского ш. д.146 до Кировоградской улицы (подъездная дорога к универсаму № 70)',
        'Проектируемый проезд №7024',
        'Ряжская улица',
        'улица Братьев Рябушинских',
        '8-я улица Текстильщиков',
        'Донецкая улица, д.40 (проезд около строения ОАО МОЭК и прилегающая территория к недостроенному гаражному комплексу)',
        'Подъездная дорога к "ул. Кубанская д. 27"',
        'Проезд № 2263',
        'Проезд № 5113',
        'Проезд №1481',
        'Проезд от ул. Перерва до Иловайской ул. (ул. Перерва 1с.1)',
        'проспект 40 лет Октября',
        'Ставропольский проезд',
        'ул. Академика Анохина, д. 36',
        'Варшавское шоссе, д. 126А',
        'ул. Борисовские пруды, д. 36, корп. 2',
        'ул. Михалковская, д. 13А',
        'Дорогобужская ул., д. 13',
        'Мичуринский пр-т. д. 23',
        'Новопеределкинская ул., д. 13, к. 1',
        'Липецкая, 44',
        'Севанская ул., д. 6',
        'Ул. 26-ти Бакинских Комиссаров, д. 4, корп.3',
        'Ул. Ярцевская, д. 31, к. 6',
        'Ул. Приречная, напротив д. 1, 3, 5',
        'Большой Очаковский пруд',
        'Мазиловский пруд',
        'Краснопресненские пруды №1 №2',
        'Битцевский лес',
        'Ижорский проезд (проезд от Коровинского ш. до Лобненской ул.)',
        'Сквер у к-т «Нева»',
        'Благоустройство Березовой рощи в 7-м квартале Кунцева',
        'Лыжероллерная трасса в Ново-Переделкино',
        'река Яуза',
    ]
    for s in streets:
        try:
            conn.execute('INSERT INTO streets (name) VALUES (?)', (s,))
        except:
            pass
    conn.commit()
    conn.close()

init_db()

# ── Улицы ──────────────────────────────────────────

@app.route('/api/streets/reset', methods=['POST'])
def reset_streets():
    conn = get_db()
    conn.execute('DELETE FROM streets')
    conn.commit()
    conn.close()
    init_db()
    return jsonify({'ok': True})

@app.route('/api/streets', methods=['GET'])
def get_streets():
    conn = get_db()
    rows = conn.execute('SELECT name FROM streets ORDER BY id').fetchall()
    conn.close()
    return jsonify([r['name'] for r in rows])

@app.route('/api/streets', methods=['POST'])
def add_street():
    name = (request.json or {}).get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    conn = get_db()
    try:
        conn.execute('INSERT INTO streets (name) VALUES (?)', (name,))
        conn.commit()
        return jsonify({'ok': True, 'name': name}), 201
    except sqlite3.IntegrityError:
        return jsonify({'ok': True, 'name': name})  # уже есть
    finally:
        conn.close()

# ── Записи ─────────────────────────────────────────
@app.route('/api/entries', methods=['GET'])
def get_entries():
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM entries ORDER BY date DESC, created_at DESC'
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/entries', methods=['POST'])
def add_entry():
    d = request.json or {}
    if not all([d.get('date'), d.get('street'), d.get('type'), d.get('vol')]):
        return jsonify({'error': 'missing fields'}), 400
    conn = get_db()
    cur = conn.execute(
        'INSERT INTO entries (date, street, type, vol, shift, note) VALUES (?,?,?,?,?,?)',
        (d['date'], d['street'], d['type'], float(d['vol']),
         d.get('shift', 'День'), d.get('note', ''))
    )
    conn.commit()
    entry_id = cur.lastrowid
    conn.close()
    return jsonify({'ok': True, 'id': entry_id}), 201

@app.route('/api/entries/<int:entry_id>', methods=['DELETE'])
def delete_entry(entry_id):
    conn = get_db()
    conn.execute('DELETE FROM entries WHERE id = ?', (entry_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ── Статистика ─────────────────────────────────────
@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db()
    rows = conn.execute('SELECT * FROM entries').fetchall()
    conn.close()
    entries = [dict(r) for r in rows]

    total = sum(e['vol'] for e in entries)
    days = len(set(e['date'] for e in entries))
    avg = round(total / days, 2) if days else 0

    # По улицам
    by_street = {}
    for e in entries:
        s = e['street']
        if s not in by_street:
            by_street[s] = {'МЗВ': 0, 'ПД': 0, 'МЗБ': 0, 'total': 0}
        t = e['type'] if e['type'] in by_street[s] else 'МЗВ'
        by_street[s][t] = round(by_street[s][t] + e['vol'], 2)
        by_street[s]['total'] = round(by_street[s]['total'] + e['vol'], 2)

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
