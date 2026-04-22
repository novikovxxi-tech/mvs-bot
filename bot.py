"""
МВС СТ АУК №1 — бот для MAX/VK
Платформа: aiogram 3.x (совместима с VK/MAX через Bot API-совместимый шлюз)
"""

import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery

import database as db
import keyboards as kb
from config import (
    BOT_TOKEN, INITIAL_ADMIN_IDS,
    TECH_LIST, MAT_LIST, RESP_LIST,
    CHIEF_NAME, CHIEF_PHONE,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Инициализация ─────────────────────────────────────────────────────────────

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


# ── FSM: состояния формы заявки ───────────────────────────────────────────────

class RequestForm(StatesGroup):
    mat_name    = State()   # выбор / ввод материала
    mat_qty     = State()   # количество
    mat_unit    = State()   # единица (если "другое")
    mat_site    = State()   # адрес объекта
    resp_name   = State()   # ответственный
    resp_phone  = State()   # телефон (если вручную)
    tech_pick   = State()   # выбор техники (мульти)
    confirm     = State()   # подтверждение

class AdminStates(StatesGroup):
    change_status_comment = State()  # комментарий при смене статуса
    find_user             = State()  # поиск пользователя


# ── Утилиты ───────────────────────────────────────────────────────────────────

def today_str() -> str:
    return datetime.now().strftime("%-d %B %Y г.").replace(
        "January","января").replace("February","февраля").replace("March","марта")\
        .replace("April","апреля").replace("May","мая").replace("June","июня")\
        .replace("July","июля").replace("August","августа").replace("September","сентября")\
        .replace("October","октября").replace("November","ноября").replace("December","декабря")


STATUS_EMOJI = {
    "new":         "🔵 Новая",
    "in_progress": "🟡 В работе",
    "issued":      "🟢 Выдано",
    "rejected":    "🔴 Отклонено",
    "withdrawn":   "⚫ Отозвана",
}


def fmt_request_card(r: dict) -> str:
    date = r["created_at"][:10] if r.get("created_at") else "—"
    tech = r.get("tech_list", "") or "не выбрана"
    return (
        f"📄 <b>Заявка № {r['request_number']}</b>\n\n"
        f"👤 <b>Заявитель:</b> {r['applicant_name']}\n"
        f"📦 <b>Материал:</b> {r['material_name']}\n"
        f"📏 <b>Количество:</b> {r['quantity']} {r['unit']}\n"
        f"📍 <b>Объект:</b> {r['object_or_task']}\n"
        f"🚜 <b>Техника:</b> {tech}\n\n"
        f"👷 <b>Ответственный:</b> {r['resp_name']} · {r['resp_phone']}\n"
        f"──────────────────\n"
        f"👤 {CHIEF_NAME} · {CHIEF_PHONE}\n\n"
        f"<b>Статус:</b> {STATUS_EMOJI.get(r['status'], r['status'])}\n"
        f"<b>Подана:</b> {date}\n"
        + (f"<b>Комментарий:</b> {r['status_comment']}\n" if r.get("status_comment") else "")
    )


def fmt_request_success(r: dict) -> str:
    tech = r.get("tech_list", "") or "не выбрана"
    return (
        f"✅ <b>Заявка принята!</b>\n\n"
        f"<b>Заявка от {today_str()}</b>\n"
        f"<b>№ {r['request_number']}</b>  ·  {STATUS_EMOJI['new']}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📦 <b>МАТЕРИАЛ</b>\n"
        f"{r['material_name']}\n"
        f"{r['quantity']} {r['unit']}\n\n"
        f"📍 <b>АДРЕС</b>\n"
        f"{r['object_or_task']}\n\n"
        f"🚜 <b>ТЕХНИКА</b>\n"
        f"{tech}\n\n"
        f"👷 <b>ОТВЕТСТВЕННЫЙ</b>\n"
        f"{r['resp_name']} · {r['resp_phone']}\n"
        f"──────────────────\n"
        f"{CHIEF_NAME} · {CHIEF_PHONE}\n"
    )


async def notify_admins(text: str, req_id: int = None):
    admins = db.get_all_admins()
    for admin in admins:
        try:
            markup = None
            if req_id:
                from aiogram.utils.keyboard import InlineKeyboardBuilder
                b = InlineKeyboardBuilder()
                b.button(text="📄 Открыть заявку", callback_data=f"req_{req_id}")
                b.button(text="🟡 В работе",       callback_data=f"setstatus_{req_id}_in_progress")
                b.button(text="🔴 Отклонить",      callback_data=f"setstatus_{req_id}_rejected")
                b.adjust(1, 2)
                markup = b.as_markup()
            await bot.send_message(admin["max_user_id"], text, reply_markup=markup)
        except Exception as e:
            logger.warning(f"Не удалось уведомить администратора {admin['max_user_id']}: {e}")


# ── /start, /menu ─────────────────────────────────────────────────────────────

@dp.message(CommandStart())
@dp.message(Command("menu"))
@dp.message(F.text == "🏠 Главное меню")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = db.ensure_user(
        message.from_user.id,
        message.from_user.full_name or "Пользователь"
    )
    # Добавляем начальных админов из конфига
    if message.from_user.id in INITIAL_ADMIN_IDS and user["role"] != "admin":
        db.set_role(message.from_user.id, "admin")

    is_new = user.get("created_at") == user.get("last_active_at")
    if is_new:
        text = (
            f"Привет, {message.from_user.first_name}! 👋\n\n"
            f"Я бот <b>«МВС СТ АУК №1»</b> — помогу с техникой и материалами на объектах.\n\n"
            f"Здесь ты можешь:\n"
            f"• подать заявку на материал\n"
            f"• посмотреть список техники\n"
            f"• отследить статус заявки\n\n"
            f"Выбери раздел:"
        )
    else:
        text = "Главное меню. Выбери раздел:"

    await message.answer(text, reply_markup=kb.kb_main())


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📋 <b>Справка — бот «МВС СТ АУК №1»</b>\n\n"
        "📦 <b>МАТЕРИАЛ</b>\n"
        "— Подача заявки на материал с выбором техники\n"
        "— Просмотр своих заявок и их статусов\n\n"
        "🚜 <b>ТЕХНИКА</b>\n"
        "— Список всей техники\n\n"
        "📌 <b>Команды:</b>\n"
        "/menu — главное меню\n"
        "/мои_заявки — мои заявки\n"
        "/заявка — новая заявка\n"
        "/cancel — отменить действие\n"
        "/id — мой ID\n"
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Действие отменено.\nВсе введённые данные не сохранены.",
        reply_markup=kb.kb_main()
    )


@dp.message(Command("id"))
async def cmd_id(message: Message):
    await message.answer(f"Твой MAX ID: <code>{message.from_user.id}</code>")


# ── Раздел Техника ────────────────────────────────────────────────────────────

@dp.message(F.text == "🚜 Техника")
@dp.message(Command("техника"))
async def section_tech(message: Message, state: FSMContext):
    await state.clear()
    lines = "\n".join(f"{i+1}. {name}" for i, name in enumerate(TECH_LIST))
    await message.answer(
        f"🚜 <b>Список техники</b>\n\n{lines}",
        reply_markup=kb.kb_main()
    )


# ── Раздел Материал ───────────────────────────────────────────────────────────

@dp.message(F.text == "📦 Материал")
@dp.message(Command("материал"))
async def section_material(message: Message, state: FSMContext):
    await state.clear()
    admin = db.is_admin(message.from_user.id)
    await message.answer(
        "📦 <b>Раздел «Материал»</b>\n\nЧто хочешь сделать?",
        reply_markup=kb.kb_material(is_admin=admin)
    )


# ── Мои заявки ────────────────────────────────────────────────────────────────

@dp.message(F.text == "📋 Мои заявки")
@dp.message(Command("мои_заявки"))
@dp.callback_query(F.data == "my_requests")
async def my_requests(event, state: FSMContext = None):
    if state:
        await state.clear()
    uid = event.from_user.id
    requests = db.get_my_requests(uid)
    send = event.message.answer if isinstance(event, CallbackQuery) else event.answer

    if not requests:
        await send(
            "У тебя пока нет заявок.\n\nПодать первую?",
            reply_markup=kb.kb_after_request()
        )
        return

    lines = []
    for r in requests[:10]:
        lines.append(
            f"<b>№ {r['request_number']}</b> | {r['material_name'][:30]}\n"
            f"Статус: {STATUS_EMOJI.get(r['status'],'?')} | {r['created_at'][:10]}"
        )
    text = "📋 <b>Мои заявки</b>\n\n" + "\n\n".join(lines)
    await send(text, reply_markup=kb.kb_my_requests(requests))

    if isinstance(event, CallbackQuery):
        await event.answer()


# ── Новая заявка: Шаг 1 — материал ───────────────────────────────────────────

@dp.message(F.text == "📝 Подать заявку")
@dp.message(Command("заявка"))
@dp.callback_query(F.data == "new_request")
async def new_request_start(event, state: FSMContext):
    await state.clear()
    await state.set_state(RequestForm.mat_name)
    send = event.message.answer if isinstance(event, CallbackQuery) else event.answer

    text = (
        f"📝 <b>Заявка от {today_str()}</b>\n\n"
        f"<b>Шаг 1 — Материал</b>\n\nВыбери из списка или введи вручную:"
    )
    await send(text, reply_markup=kb.kb_mat_list())
    if isinstance(event, CallbackQuery):
        await event.answer()


# Выбор материала из списка
@dp.callback_query(StateFilter(RequestForm.mat_name), F.data.startswith("mat_"))
async def pick_mat(call: CallbackQuery, state: FSMContext):
    idx = int(call.data.split("_")[1])
    name = MAT_LIST[idx]
    await state.update_data(material_name=name)
    await state.set_state(RequestForm.mat_qty)
    await call.message.answer(
        f"✅ Выбран: <b>{name}</b>\n\n<b>Шаг 2 — Количество</b>\n\nВведи количество (цифрой):"
    )
    await call.answer()


# Ввод материала вручную
@dp.callback_query(StateFilter(RequestForm.mat_name), F.data == "mat_manual")
async def mat_manual_prompt(call: CallbackQuery, state: FSMContext):
    await call.message.answer("✏️ Введи наименование материала:")
    await call.answer()


@dp.message(StateFilter(RequestForm.mat_name))
async def mat_manual_input(message: Message, state: FSMContext):
    await state.update_data(material_name=message.text.strip())
    await state.set_state(RequestForm.mat_qty)
    await message.answer(
        f"✅ Материал: <b>{message.text.strip()}</b>\n\n<b>Шаг 2 — Количество</b>\n\nВведи количество (цифрой):"
    )


# ── Шаг 2 — количество ────────────────────────────────────────────────────────

@dp.message(StateFilter(RequestForm.mat_qty))
async def input_qty(message: Message, state: FSMContext):
    try:
        qty = float(message.text.strip().replace(",", "."))
        if qty <= 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Введи корректное число (например: 50, 1.5, 0.25).\n\nПопробуй ещё раз:")
        return
    await state.update_data(quantity=qty)
    await state.set_state(RequestForm.mat_unit)
    await message.answer("<b>Шаг 3 — Единица измерения</b>\n\nВыбери:", reply_markup=kb.kb_units())


# ── Шаг 3 — единица ───────────────────────────────────────────────────────────

@dp.callback_query(StateFilter(RequestForm.mat_unit), F.data.startswith("unit_"))
async def pick_unit(call: CallbackQuery, state: FSMContext):
    unit = call.data[5:]
    if unit == "other":
        await call.message.answer("✏️ Введи единицу измерения:")
        await call.answer()
        return
    await state.update_data(unit=unit)
    await state.set_state(RequestForm.mat_site)
    await call.message.answer(
        f"✅ Единица: <b>{unit}</b>\n\n<b>Шаг 4 — Адрес объекта</b>\n\nВведи адрес:"
    )
    await call.answer()


@dp.message(StateFilter(RequestForm.mat_unit))
async def unit_manual(message: Message, state: FSMContext):
    await state.update_data(unit=message.text.strip())
    await state.set_state(RequestForm.mat_site)
    await message.answer(
        f"✅ Единица: <b>{message.text.strip()}</b>\n\n<b>Шаг 4 — Адрес объекта</b>\n\nВведи адрес:"
    )


# ── Шаг 4 — адрес ────────────────────────────────────────────────────────────

@dp.message(StateFilter(RequestForm.mat_site))
async def input_site(message: Message, state: FSMContext):
    await state.update_data(object_or_task=message.text.strip())
    await state.set_state(RequestForm.resp_name)
    await message.answer(
        f"✅ Адрес: <b>{message.text.strip()}</b>\n\n"
        f"<b>Шаг 5 — Ответственный</b>\n\nВыбери из списка или введи вручную:",
        reply_markup=kb.kb_resp_list()
    )


# ── Шаг 5 — ответственный ─────────────────────────────────────────────────────

@dp.callback_query(StateFilter(RequestForm.resp_name), F.data.startswith("resp_"))
async def pick_resp(call: CallbackQuery, state: FSMContext):
    idx = int(call.data.split("_")[1])
    r = RESP_LIST[idx]
    await state.update_data(resp_name=r["name"], resp_phone=r["phone"])
    await state.set_state(RequestForm.tech_pick)
    await state.update_data(tech_selected={})
    await call.message.answer(
        f"✅ Ответственный: <b>{r['name']}</b>\n{r['phone']}\n\n"
        f"<b>Шаг 6 — Техника</b>\n\nВыбери нужную технику (нажимай — можно несколько).\n"
        f"Повторный нажатие снимает выбор.",
        reply_markup=kb.kb_tech_pick_simple({})
    )
    await call.answer()


@dp.callback_query(StateFilter(RequestForm.resp_name), F.data == "resp_manual")
async def resp_manual_prompt(call: CallbackQuery):
    await call.message.answer("✏️ Введи ФИО ответственного:")
    await call.answer()


@dp.message(StateFilter(RequestForm.resp_name))
async def resp_manual_input(message: Message, state: FSMContext):
    await state.update_data(resp_name=message.text.strip())
    await state.set_state(RequestForm.resp_phone)
    await message.answer("Введи телефон ответственного:")


@dp.message(StateFilter(RequestForm.resp_phone))
async def resp_phone_input(message: Message, state: FSMContext):
    await state.update_data(resp_phone=message.text.strip())
    await state.set_state(RequestForm.tech_pick)
    await state.update_data(tech_selected={})
    await message.answer(
        f"<b>Шаг 6 — Техника</b>\n\nВыбери нужную технику (нажимай — можно несколько).\n"
        f"Повторный нажатие снимает выбор.",
        reply_markup=kb.kb_tech_pick_simple({})
    )


# ── Шаг 6 — выбор техники ────────────────────────────────────────────────────

@dp.callback_query(StateFilter(RequestForm.tech_pick), F.data.startswith("pick_"))
async def toggle_tech(call: CallbackQuery, state: FSMContext):
    idx = int(call.data.split("_")[1])
    data = await state.get_data()
    selected: dict = dict(data.get("tech_selected") or {})

    # Ключи хранятся как строки из-за JSON сериализации FSM
    key = str(idx)
    if key in selected:
        del selected[key]
    else:
        selected[key] = 1

    await state.update_data(tech_selected=selected)

    # Преобразуем в int-ключи для клавиатуры
    int_selected = {int(k): v for k, v in selected.items()}
    await call.message.edit_reply_markup(reply_markup=kb.kb_tech_pick_simple(int_selected))
    await call.answer()


@dp.callback_query(StateFilter(RequestForm.tech_pick), F.data == "pick_back")
async def tech_back(call: CallbackQuery, state: FSMContext):
    await state.set_state(RequestForm.resp_name)
    await call.message.answer(
        "Выбери ответственного из списка или введи вручную:",
        reply_markup=kb.kb_resp_list()
    )
    await call.answer()


@dp.callback_query(StateFilter(RequestForm.tech_pick), F.data.in_({"pick_done", "pick_skip"}))
async def tech_done(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    if call.data == "pick_skip":
        tech_list_str = ""
    else:
        selected: dict = data.get("tech_selected") or {}
        if selected:
            lines = []
            for k, qty in selected.items():
                name = TECH_LIST[int(k)]
                lines.append(f"• {name} — {qty} ед.")
            tech_list_str = "\n".join(lines)
        else:
            tech_list_str = ""

    await state.update_data(tech_list=tech_list_str)
    await state.set_state(RequestForm.confirm)

    # Формируем превью
    d = await state.get_data()
    tech_preview = d.get("tech_list") or "не выбрана"
    preview = (
        f"<b>Проверь заявку перед отправкой:</b>\n\n"
        f"📦 <b>Материал:</b> {d.get('material_name')}\n"
        f"📏 <b>Количество:</b> {d.get('quantity')} {d.get('unit')}\n"
        f"📍 <b>Адрес:</b> {d.get('object_or_task')}\n"
        f"🚜 <b>Техника:</b>\n{tech_preview}\n\n"
        f"👷 <b>Ответственный:</b> {d.get('resp_name')} · {d.get('resp_phone')}\n"
        f"──────────────────\n"
        f"👤 {CHIEF_NAME} · {CHIEF_PHONE}"
    )
    await call.message.answer(preview, reply_markup=kb.kb_confirm())
    await call.answer()


# ── Подтверждение и отправка ─────────────────────────────────────────────────

@dp.callback_query(StateFilter(RequestForm.confirm), F.data == "confirm_yes")
async def submit_request(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    req = db.create_request({
        "user_id":        call.from_user.id,
        "applicant_name": data.get("resp_name", call.from_user.full_name),
        "material_name":  data.get("material_name", ""),
        "quantity":       data.get("quantity", 0),
        "unit":           data.get("unit", "шт"),
        "object_or_task": data.get("object_or_task", ""),
        "resp_name":      data.get("resp_name", ""),
        "resp_phone":     data.get("resp_phone", ""),
        "tech_list":      data.get("tech_list", ""),
    })

    await call.message.answer(fmt_request_success(req), reply_markup=kb.kb_after_request())
    await call.answer("✅ Заявка отправлена!")

    # Уведомляем администраторов
    notif = (
        f"🔔 <b>Новая заявка на материал</b>\n\n"
        f"№ {req['request_number']}\n"
        f"От: {data.get('resp_name')}\n"
        f"Материал: {data.get('material_name')} — {data.get('quantity')} {data.get('unit')}\n"
        f"Объект: {data.get('object_or_task')}\n"
        f"Техника: {data.get('tech_list') or 'не выбрана'}\n"
        f"Подана: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    await notify_admins(notif, req_id=req["id"])


@dp.callback_query(StateFilter(RequestForm.confirm), F.data == "confirm_edit")
async def confirm_edit(call: CallbackQuery, state: FSMContext):
    await state.set_state(RequestForm.mat_name)
    await call.message.answer(
        "Хорошо, начнём сначала. Выбери материал:",
        reply_markup=kb.kb_mat_list()
    )
    await call.answer()


# ── Карточка заявки ───────────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("req_"))
async def show_request(call: CallbackQuery):
    req_id = int(call.data.split("_")[1])
    req = db.get_request_by_id(req_id)
    if not req:
        await call.answer("Заявка не найдена.", show_alert=True)
        return
    admin = db.is_admin(call.from_user.id)
    await call.message.answer(fmt_request_card(req), reply_markup=kb.kb_request_card(req, is_admin=admin))
    await call.answer()


# ── Отзыв заявки ─────────────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("withdraw_"))
async def withdraw_request(call: CallbackQuery):
    req_id = int(call.data.split("_")[1])
    req = db.get_request_by_id(req_id)
    if not req or req["user_id"] != call.from_user.id or req["status"] != "new":
        await call.answer("Нельзя отозвать эту заявку.", show_alert=True)
        return
    db.update_request_status(req_id, "withdrawn", admin_id=call.from_user.id)
    await call.message.answer(f"✅ Заявка <b>№ {req['request_number']}</b> отозвана.")
    await call.answer()


# ── Смена статуса (admin) ─────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("chstatus_"))
async def change_status_menu(call: CallbackQuery):
    if not db.is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа.", show_alert=True)
        return
    req_id = int(call.data.split("_")[1])
    req = db.get_request_by_id(req_id)
    await call.message.answer(
        f"🔄 <b>Смена статуса заявки № {req['request_number']}</b>\n"
        f"Текущий: {STATUS_EMOJI.get(req['status'])}\n\nВыбери новый статус:",
        reply_markup=kb.kb_change_status(req_id)
    )
    await call.answer()


@dp.callback_query(F.data.startswith("setstatus_"))
async def set_status(call: CallbackQuery, state: FSMContext):
    if not db.is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа.", show_alert=True)
        return
    parts = call.data.split("_")
    req_id = int(parts[1])
    new_status = parts[2]

    req = db.get_request_by_id(req_id)
    if not req:
        await call.answer("Заявка не найдена.", show_alert=True)
        return

    if new_status == "rejected":
        await state.update_data(pending_req_id=req_id, pending_status=new_status)
        await state.set_state(AdminStates.change_status_comment)
        await call.message.answer("Укажи причину отказа (обязательно):")
        await call.answer()
        return

    # Для остальных — комментарий необязателен, сразу меняем
    comment = ""
    if new_status == "in_progress":
        comment = "Заявка принята в работу"
    elif new_status == "issued":
        comment = "Материал выдан"

    db.update_request_status(req_id, new_status, comment=comment, admin_id=call.from_user.id)

    await call.message.answer(
        f"✅ Статус заявки обновлён.\n\n"
        f"№ {req['request_number']} → {STATUS_EMOJI.get(new_status)}\n"
        f"Заявитель уведомлён."
    )

    # Уведомляем заявителя
    notif_map = {
        "in_progress": (
            f"🔔 <b>Статус заявки изменён</b>\n\n"
            f"№ {req['request_number']} — {req['material_name']}, {req['quantity']} {req['unit']}\n"
            f"Новый статус: {STATUS_EMOJI['in_progress']}\n"
            f"Комментарий: {comment}"
        ),
        "issued": (
            f"🔔 <b>Материал выдан!</b>\n\n"
            f"№ {req['request_number']} — {req['material_name']}, {req['quantity']} {req['unit']}\n"
            f"Статус: {STATUS_EMOJI['issued']}\n\n"
            f"Пожалуйста, получи материал на складе."
        ),
    }
    if new_status in notif_map:
        try:
            await bot.send_message(req["user_id"], notif_map[new_status])
        except Exception as e:
            logger.warning(f"Не удалось уведомить пользователя: {e}")

    await call.answer()


@dp.message(StateFilter(AdminStates.change_status_comment))
async def status_comment_input(message: Message, state: FSMContext):
    data = await state.get_data()
    req_id = data["pending_req_id"]
    new_status = data["pending_status"]
    comment = message.text.strip()
    await state.clear()

    req = db.get_request_by_id(req_id)
    db.update_request_status(req_id, new_status, comment=comment, admin_id=message.from_user.id)
    await message.answer(
        f"✅ Статус обновлён.\n\n"
        f"№ {req['request_number']} → {STATUS_EMOJI.get(new_status)}\n"
        f"Причина: {comment}"
    )

    try:
        await bot.send_message(
            req["user_id"],
            f"🔔 <b>Заявка отклонена</b>\n\n"
            f"№ {req['request_number']} — {req['material_name']}, {req['quantity']} {req['unit']}\n"
            f"Статус: {STATUS_EMOJI['rejected']}\n"
            f"Причина: {comment}"
        )
    except Exception as e:
        logger.warning(f"Не удалось уведомить пользователя: {e}")


# ── Все заявки (admin) ────────────────────────────────────────────────────────

@dp.message(F.text == "📂 Все заявки")
@dp.callback_query(F.data == "all_requests")
async def all_requests(event):
    uid = event.from_user.id
    if not db.is_admin(uid):
        send = event.answer if isinstance(event, Message) else event.message.answer
        await send("⛔ Нет доступа.")
        return
    send = event.answer if isinstance(event, Message) else event.message.answer
    await send("📂 <b>Все заявки</b>\n\nФильтр по статусу:", reply_markup=kb.kb_all_requests_filter())
    if isinstance(event, CallbackQuery):
        await event.answer()


@dp.callback_query(F.data.startswith("allreq_"))
async def all_requests_filter(call: CallbackQuery):
    if not db.is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа.", show_alert=True)
        return
    status = call.data[7:]
    reqs = db.get_all_requests(None if status == "all" else status)
    if not reqs:
        await call.message.answer("Заявок не найдено.", reply_markup=kb.kb_all_requests_filter())
        await call.answer()
        return
    await call.message.answer(
        f"📂 Заявок: {len(reqs)}",
        reply_markup=kb.kb_all_requests_list(reqs)
    )
    await call.answer()


# ── Навигация ─────────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "back_main")
async def cb_back_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("Главное меню:", reply_markup=kb.kb_main())
    await call.answer()


@dp.callback_query(F.data == "back_material")
async def cb_back_material(call: CallbackQuery):
    admin = db.is_admin(call.from_user.id)
    await call.message.answer(
        "📦 <b>Раздел «Материал»</b>\n\nЧто хочешь сделать?",
        reply_markup=kb.kb_material(is_admin=admin)
    )
    await call.answer()


@dp.callback_query(F.data == "cancel_form")
async def cb_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("❌ Действие отменено.", reply_markup=kb.kb_main())
    await call.answer()


@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("Главное меню:", reply_markup=kb.kb_main())
    await call.answer()


# ── Нераспознанный ввод ────────────────────────────────────────────────────────

@dp.message()
async def unknown(message: Message):
    await message.answer(
        "Не понял команду.\n\nВоспользуйся кнопками или введи /menu для возврата в главное меню."
    )


# ── Запуск ────────────────────────────────────────────────────────────────────

async def main():
    db.init_db(initial_admin_ids=INITIAL_ADMIN_IDS)
    logger.info("База данных инициализирована")
    logger.info("Бот запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
