from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from config import TECH_LIST, MAT_LIST, RESP_LIST, UNITS


# ── Главное меню ──────────────────────────────────────────────────────────────

def kb_main() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="📦 Материал")
    kb.button(text="🚜 Техника")
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)


# ── Раздел Материал ───────────────────────────────────────────────────────────

def kb_material(is_admin: bool = False) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="📝 Подать заявку")
    kb.button(text="📋 Мои заявки")
    if is_admin:
        kb.button(text="📂 Все заявки")
    kb.button(text="← Главное меню")
    kb.adjust(2, 1)
    return kb.as_markup(resize_keyboard=True)


# ── Раздел Техника ────────────────────────────────────────────────────────────

def kb_tech_list() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, name in enumerate(TECH_LIST):
        builder.button(text=f"{i+1}. {name}", callback_data=f"tech_{i}")
    builder.button(text="← Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


# ── Форма заявки: выбор материала ────────────────────────────────────────────

def kb_mat_list() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, name in enumerate(MAT_LIST):
        short = name[:40] + "…" if len(name) > 40 else name
        builder.button(text=short, callback_data=f"mat_{i}")
    builder.button(text="✏️ Ввести вручную", callback_data="mat_manual")
    builder.button(text="← Отмена", callback_data="cancel_form")
    builder.adjust(1)
    return builder.as_markup()


# ── Форма заявки: выбор единицы измерения ────────────────────────────────────

def kb_units() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for u in UNITS:
        builder.button(text=u, callback_data=f"unit_{u}")
    builder.button(text="✏️ Другое", callback_data="unit_other")
    builder.adjust(4)
    return builder.as_markup()


# ── Форма заявки: выбор ответственного ───────────────────────────────────────

def kb_resp_list() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, r in enumerate(RESP_LIST):
        builder.button(text=r["name"], callback_data=f"resp_{i}")
    builder.button(text="✏️ Ввести вручную", callback_data="resp_manual")
    builder.button(text="← Отмена", callback_data="cancel_form")
    builder.adjust(1)
    return builder.as_markup()


# ── Форма заявки: выбор техники (мульти) ─────────────────────────────────────

def kb_tech_pick(selected: dict[int, int]) -> InlineKeyboardMarkup:
    """selected = {idx: qty}"""
    builder = InlineKeyboardBuilder()
    for i, name in enumerate(TECH_LIST):
        if i in selected:
            label = f"✅ {name} ({selected[i]} ед.)"
        else:
            label = f"☐ {name}"
        builder.button(text=label, callback_data=f"pick_{i}")
    builder.button(text="➖", callback_data="qty_dec")
    builder.button(text="➕", callback_data="qty_inc")
    builder.button(text="✅ Готово", callback_data="pick_done")
    builder.button(text="⏭ Без техники", callback_data="pick_skip")
    builder.button(text="← Назад", callback_data="pick_back")
    builder.adjust(1)
    return builder.as_markup()


def kb_tech_pick_simple(selected: dict[int, int]) -> InlineKeyboardMarkup:
    """Упрощённая версия без qty кнопок — выбор/снятие по клику"""
    builder = InlineKeyboardBuilder()
    for i, name in enumerate(TECH_LIST):
        if i in selected:
            qty = selected[i]
            label = f"✅ {name} — {qty} ед."
        else:
            label = f"   {name}"
        builder.button(text=label, callback_data=f"pick_{i}")
    builder.button(text="✅ Отправить заявку", callback_data="pick_done")
    builder.button(text="⏭ Без техники", callback_data="pick_skip")
    builder.button(text="← Назад", callback_data="pick_back")
    builder.adjust(1)
    return builder.as_markup()


# ── Подтверждение заявки ─────────────────────────────────────────────────────

def kb_confirm() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить", callback_data="confirm_yes")
    builder.button(text="✏️ Изменить", callback_data="confirm_edit")
    builder.button(text="❌ Отмена", callback_data="cancel_form")
    builder.adjust(2, 1)
    return builder.as_markup()


# ── После отправки заявки ─────────────────────────────────────────────────────

def kb_after_request() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Мои заявки", callback_data="my_requests")
    builder.button(text="📝 Ещё заявка", callback_data="new_request")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(2, 1)
    return builder.as_markup()


# ── Список моих заявок ────────────────────────────────────────────────────────

def kb_my_requests(requests: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for r in requests[:10]:
        label = f"{r['request_number']} · {r['material_name'][:20]}"
        builder.button(text=label, callback_data=f"req_{r['id']}")
    builder.button(text="← Назад", callback_data="back_material")
    builder.adjust(1)
    return builder.as_markup()


# ── Карточка заявки (пользователь) ───────────────────────────────────────────

def kb_request_card(req: dict, is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_admin:
        builder.button(text="🔄 Сменить статус", callback_data=f"chstatus_{req['id']}")
    elif req["status"] == "new":
        builder.button(text="❌ Отозвать заявку", callback_data=f"withdraw_{req['id']}")
    builder.button(text="← К списку", callback_data="my_requests")
    builder.adjust(1)
    return builder.as_markup()


# ── Смена статуса заявки (admin) ─────────────────────────────────────────────

def kb_change_status(req_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🟡 В работе",   callback_data=f"setstatus_{req_id}_in_progress")
    builder.button(text="🟢 Выдано",     callback_data=f"setstatus_{req_id}_issued")
    builder.button(text="🔴 Отклонено",  callback_data=f"setstatus_{req_id}_rejected")
    builder.button(text="← Отмена",      callback_data=f"req_{req_id}")
    builder.adjust(1)
    return builder.as_markup()


# ── Все заявки (admin) ────────────────────────────────────────────────────────

def kb_all_requests_filter() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔵 Новые",      callback_data="allreq_new")
    builder.button(text="🟡 В работе",   callback_data="allreq_in_progress")
    builder.button(text="🟢 Выдано",     callback_data="allreq_issued")
    builder.button(text="🔴 Отклонено",  callback_data="allreq_rejected")
    builder.button(text="📋 Все",         callback_data="allreq_all")
    builder.button(text="← Назад",       callback_data="back_material")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def kb_all_requests_list(requests: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for r in requests[:15]:
        label = f"{r['request_number']} · {r['applicant_name'][:15]} · {r['material_name'][:15]}"
        builder.button(text=label, callback_data=f"req_{r['id']}")
    builder.button(text="← Назад", callback_data="all_requests")
    builder.adjust(1)
    return builder.as_markup()


# ── Назад / Отмена ────────────────────────────────────────────────────────────

def kb_back_main() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="🏠 Главное меню")
    return kb.as_markup(resize_keyboard=True)
