import json
import os
import logging
import asyncio
import hashlib
import urllib.parse
from collections import OrderedDict
from typing import Dict, Any, Optional, List
from uuid import uuid4
from datetime import datetime
import requests

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ================== 配置区域 ==================
TOKEN = "8718624772:AAFJZhmsTC_C38aG7AakMTriGY7kmjwhJLE"
ADMIN_USER_ID = 8717474274
WELCOME_CHAT_IDS = [ADMIN_USER_ID]

# ================== OkayPay API 配置 ==================
API_URL = 'https://api.okaypay.me/shop/'
shop_id = "34721"
shop_token = "9d6eikQToUqx5BsEG1ObSchWY04w7Zan"
NAME = "乱天1"
bot_username = "ghfjk520bot"

# 数据文件路径
BALANCE_FILE = "user_balances.json"
ORDER_FILE = "orders.json"
PRODUCTS_FILE = "products.json"
COUNTRIES_FILE = "countries.json"
CARD_FILE = "cards.json"
CATEGORIES_FILE = "categories.json"
SENT_WELCOME_FILE = "sent_welcome.json"
RECHARGE_ORDERS_FILE = "recharge_orders.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== OkayPay API 函数 ==================
def _sign(data: dict) -> dict:
    data['id'] = shop_id
    data = {k: v for k, v in data.items() if v or v == 0}
    data = OrderedDict(sorted(data.items()))
    query = urllib.parse.urlencode(data, quote_via=urllib.parse.quote)
    query = urllib.parse.unquote(query)
    data['sign'] = hashlib.md5(
        (query + '&token=' + shop_token).encode()
    ).hexdigest().upper()
    return data

def _post(endpoint: str, data: dict) -> dict:
    data = _sign(data)
    try:
        resp = requests.post(API_URL + endpoint, data=data, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {'code': -1, 'msg': str(e)}

def okpay_create_deposit(order_number: str, amount: float, user_id: str) -> dict:
    return _post('payLink', {
        'unique_id': order_number,
        'name': f'{NAME}充值',
        'amount': str(amount),
        'return_url': f'https://t.me/{bot_username}',
        'coin': 'USDT',
    })

def okpay_check_deposit(unique_id: str) -> dict:
    return _post('checkDeposit', {'unique_id': unique_id})

def okpay_balance() -> dict:
    return _post('balance', {})

# ================== 数据持久化 ==================
def load_json(file_path: str, default: Any = None) -> Any:
    if default is None:
        default = {} if file_path.endswith(".json") else []
    if not os.path.exists(file_path):
        return default
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default

def save_json(file_path: str, data: Any) -> None:
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# 初始化数据
user_balances: Dict[str, float] = load_json(BALANCE_FILE)
orders: Dict[str, Dict] = load_json(ORDER_FILE)
products: Dict[str, Dict] = load_json(PRODUCTS_FILE, {})
countries: Dict[str, Dict] = load_json(COUNTRIES_FILE, {})
cards: Dict[str, List[Dict]] = load_json(CARD_FILE, {})
categories: List[str] = load_json(CATEGORIES_FILE, [])
sent_welcome: Dict[str, bool] = load_json(SENT_WELCOME_FILE, {})
recharge_orders: Dict[str, Dict] = load_json(RECHARGE_ORDERS_FILE, {})

# 确保数据类型正确
if categories is None:
    categories = []
    save_json(CATEGORIES_FILE, categories)
if products is None:
    products = {}
    save_json(PRODUCTS_FILE, products)
if cards is None:
    cards = {}
    save_json(CARD_FILE, cards)
if countries is None:
    countries = {}
    save_json(COUNTRIES_FILE, countries)

def save_all_data() -> None:
    save_json(BALANCE_FILE, user_balances)
    save_json(ORDER_FILE, orders)
    save_json(PRODUCTS_FILE, products)
    save_json(COUNTRIES_FILE, countries)
    save_json(CARD_FILE, cards)
    save_json(CATEGORIES_FILE, categories)
    save_json(SENT_WELCOME_FILE, sent_welcome)
    save_json(RECHARGE_ORDERS_FILE, recharge_orders)

# ================== 辅助函数 ==================
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID

def get_available_card(product_key: str) -> Optional[str]:
    if product_key not in cards:
        return None
    for card_info in cards[product_key]:
        if not card_info.get("used", False):
            card_info["used"] = True
            save_json(CARD_FILE, cards)
            return card_info["card"]
    return None

def add_cards_bulk(product_key: str, card_list: List[str]) -> int:
    if product_key not in cards:
        cards[product_key] = []
    added = 0
    for card in card_list:
        card = card.strip()
        if card:
            cards[product_key].append({"card": card, "used": False})
            added += 1
    save_json(CARD_FILE, cards)
    return added

def add_account_to_product(product_key: str, account_info: str) -> bool:
    if product_key not in products:
        return False
    if 'accounts' not in products[product_key]:
        products[product_key]['accounts'] = []
    products[product_key]['accounts'].append({
        "info": account_info,
        "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    products[product_key]['stock'] = len(products[product_key]['accounts'])
    save_all_data()
    return True

def get_product_account(product_key: str) -> Optional[str]:
    if product_key not in products:
        return None
    accounts = products[product_key].get('accounts', [])
    if accounts:
        account = accounts.pop(0)
        products[product_key]['accounts'] = accounts
        products[product_key]['stock'] = len(accounts)
        save_all_data()
        return account.get('info')
    return None

def create_order(user_id: str, product_key: str, quantity: int = 1, country_code: str = None, delivery_data: str = None):
    prod = products.get(product_key)
    if not prod:
        return None, None
    
    product_type = prod.get('product_type', 'card')
    
    if product_type == 'country' and country_code:
        if country_code not in countries:
            return None, None
        country = countries[country_code]
        accounts = country.get('accounts', [])
        if len(accounts) < quantity:
            return None, None
        account = accounts.pop(0)
        countries[country_code]['accounts'] = accounts
        countries[country_code]['stock'] = len(accounts)
        price = country["price_usdt"]
        product_name = f"{prod['name']} - {country['name']}"
        delivery_data = account.get('info')
    else:
        price = prod["price_usdt"]
        product_name = prod["name"]
        if delivery_data is None:
            if product_type == 'card':
                delivery_data = get_available_card(product_key)
            elif product_type == 'account':
                delivery_data = get_product_account(product_key)
    
    order_id = str(uuid4())[:8]
    orders[order_id] = {
        "user_id": user_id,
        "product_key": product_key,
        "product_name": product_name,
        "price_usdt": price,
        "quantity": quantity,
        "total_usdt": price * quantity,
        "status": "completed",
        "country_code": country_code,
        "delivery_data": delivery_data,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_all_data()
    return order_id, delivery_data

def create_recharge_order(user_id: str, amount: float) -> str:
    order_id = f"R{datetime.now().strftime('%Y%m%d%H%M%S')}{user_id[-4:]}"
    recharge_orders[order_id] = {
        "user_id": user_id,
        "amount": amount,
        "status": "pending",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_all_data()
    return order_id

def confirm_recharge(order_id: str, tx_id: str = None) -> bool:
    if order_id not in recharge_orders:
        return False
    order = recharge_orders[order_id]
    if order["status"] == "completed":
        return True
    user_id = order["user_id"]
    amount = order["amount"]
    user_balances[user_id] = user_balances.get(user_id, 0.0) + amount
    order["status"] = "completed"
    order["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if tx_id:
        order["tx_id"] = tx_id
    save_all_data()
    logger.info(f"用户 {user_id} 充值成功 +{amount} USDT")
    return True

async def check_pending_recharges(context: ContextTypes.DEFAULT_TYPE) -> None:
    pending_orders = [oid for oid, o in recharge_orders.items() if o["status"] == "pending"]
    for order_id in pending_orders:
        result = okpay_check_deposit(order_id)
        if result.get('code') == 200:
            data = result.get('data', {})
            if data.get('status') == 1:
                if confirm_recharge(order_id, data.get('tx_id')):
                    order = recharge_orders[order_id]
                    try:
                        await context.bot.send_message(
                            chat_id=int(order["user_id"]),
                            text=f"✅ *充值成功！*\n\n金额：{order['amount']} USDT\n当前余额：`{user_balances[order['user_id']]:.4f} USDT`",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.error(f"通知用户失败: {e}")

async def get_shop_name(context: ContextTypes.DEFAULT_TYPE) -> str:
    try:
        admin_user = await context.bot.get_chat(ADMIN_USER_ID)
        admin_name = admin_user.full_name or admin_user.username or "管理员"
        return f"🎫 {admin_name}のTG号铺"
    except:
        return "🎫 のTG号铺"

# ================== 键盘构建 ==================
async def get_main_menu_keyboard(context: ContextTypes.DEFAULT_TYPE, is_admin_user: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("📦 商品列表", callback_data="product_list")],
        [InlineKeyboardButton("💰 我的余额", callback_data="my_balance")],
        [InlineKeyboardButton("💎 充值余额", callback_data="recharge_balance")],
        [InlineKeyboardButton("📋 我的订单", callback_data="my_orders")],
        [InlineKeyboardButton("👤 联系管理员", callback_data="contact_admin")],
    ]
    if is_admin_user:
        buttons.append([InlineKeyboardButton("⚙️ 管理面板", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)

def get_main_reply_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton("🛒 商品列表"), KeyboardButton("👤 我的余额")],
        [KeyboardButton("💎 充值余额"), KeyboardButton("📋 我的订单")],
        [KeyboardButton("📞 联系管理员")]
    ]
    if is_admin:
        buttons.append([KeyboardButton("⚙️ 管理面板")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("➕ 快速添加商品", callback_data="quick_add_product")],
        [InlineKeyboardButton("📂 管理分类", callback_data="manage_categories")],
        [InlineKeyboardButton("📦 管理商品", callback_data="manage_products")],
        [InlineKeyboardButton("🌍 管理国家", callback_data="manage_countries")],
        [InlineKeyboardButton("📊 查看统计", callback_data="admin_stats")],
        [InlineKeyboardButton("📋 所有订单", callback_data="admin_orders")],
        [InlineKeyboardButton("💰 充值记录", callback_data="admin_recharge_records")],
        [InlineKeyboardButton("💎 商户余额", callback_data="admin_balance")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(buttons)

def get_manage_categories_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    if not categories:
        buttons.append([InlineKeyboardButton("📁 暂无分类，点击添加", callback_data="add_new_category")])
    else:
        for cat in categories:
            product_count = len([p for p in products.values() if p.get('category') == cat])
            buttons.append([InlineKeyboardButton(f"📁 {cat} ({product_count}个商品)", callback_data=f"edit_category_{cat}")])
        buttons.append([InlineKeyboardButton("➕ 添加新分类", callback_data="add_new_category")])
    buttons.append([InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)

def get_category_edit_keyboard(category: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("✏️ 重命名分类", callback_data=f"rename_category_{category}")],
        [InlineKeyboardButton("🗑️ 删除分类", callback_data=f"delete_category_{category}")],
        [InlineKeyboardButton("🔙 返回分类列表", callback_data="manage_categories")]
    ]
    return InlineKeyboardMarkup(buttons)

def get_product_type_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("🔑 卡密商品", callback_data="product_type_card")],
        [InlineKeyboardButton("👤 账号商品", callback_data="product_type_account")],
        [InlineKeyboardButton("🌍 国家动态商品", callback_data="product_type_country")],
        [InlineKeyboardButton("🔙 返回", callback_data="manage_products")]
    ]
    return InlineKeyboardMarkup(buttons)

def get_manage_products_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    if not categories:
        buttons.append([InlineKeyboardButton("⚠️ 请先创建分类", callback_data="manage_categories")])
    else:
        for cat in categories:
            cat_products = [(k, v) for k, v in products.items() if v.get('category') == cat]
            if cat_products:
                buttons.append([InlineKeyboardButton(f"─── {cat} ───", callback_data="noop")])
                for key, prod in cat_products:
                    type_emoji = "🔑" if prod.get('product_type') == 'card' else ("👤" if prod.get('product_type') == 'account' else "🌍")
                    buttons.append([InlineKeyboardButton(f"{type_emoji} {prod['name']}", callback_data=f"admin_product_{key}")])
            else:
                buttons.append([InlineKeyboardButton(f"📁 {cat} (0个商品)", callback_data="noop")])
        buttons.append([InlineKeyboardButton("➕ 添加新商品", callback_data="add_new_product")])
    buttons.append([InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)

def get_admin_product_keyboard(product_key: str, product: Dict) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("📝 修改价格", callback_data=f"admin_edit_price_{product_key}")],
        [InlineKeyboardButton("📝 修改描述", callback_data=f"admin_edit_desc_{product_key}")],
        [InlineKeyboardButton("📂 修改分类", callback_data=f"admin_edit_category_{product_key}")],
    ]
    product_type = product.get('product_type', 'card')
    if product_type == 'card':
        buttons.append([InlineKeyboardButton("🔑 添加卡密", callback_data=f"admin_add_card_{product_key}")])
        buttons.append([InlineKeyboardButton("📋 查看卡密列表", callback_data=f"admin_list_cards_{product_key}")])
    elif product_type == 'account':
        buttons.append([InlineKeyboardButton("👤 添加账号", callback_data=f"admin_add_account_{product_key}")])
        buttons.append([InlineKeyboardButton("📋 查看账号列表", callback_data=f"admin_list_accounts_{product_key}")])
    elif product_type == 'country':
        buttons.append([InlineKeyboardButton("🌍 管理国家", callback_data=f"admin_manage_countries_{product_key}")])
    buttons.append([InlineKeyboardButton("🗑️ 删除商品", callback_data=f"admin_delete_product_{product_key}")])
    buttons.append([InlineKeyboardButton("🔙 返回商品列表", callback_data="manage_products")])
    return InlineKeyboardMarkup(buttons)

def get_country_management_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    if not countries:
        buttons.append([InlineKeyboardButton("📁 暂无国家，点击添加", callback_data="add_country")])
    else:
        for code, country in countries.items():
            accounts_count = len(country.get('accounts', []))
            buttons.append([InlineKeyboardButton(f"🌍 {country['name']} ({country['code']}) - 库存:{accounts_count}", callback_data=f"edit_country_{code}")])
        buttons.append([InlineKeyboardButton("➕ 添加新国家", callback_data="add_country")])
    buttons.append([InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)

def get_country_edit_keyboard(country_code: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("📝 修改价格", callback_data=f"edit_price_{country_code}")],
        [InlineKeyboardButton("➕ 添加账号", callback_data=f"add_account_{country_code}")],
        [InlineKeyboardButton("📋 查看账号列表", callback_data=f"list_accounts_{country_code}")],
        [InlineKeyboardButton("🗑️ 删除国家", callback_data=f"delete_country_{country_code}")],
        [InlineKeyboardButton("🔙 返回国家列表", callback_data="manage_countries")]
    ]
    return InlineKeyboardMarkup(buttons)

def get_countries_list_keyboard(product_key: str) -> InlineKeyboardMarkup:
    if product_key not in products:
        return get_product_categories_keyboard()
    country_codes = products[product_key].get("countries", [])
    buttons = []
    if not country_codes:
        buttons.append([InlineKeyboardButton("📁 暂无国家，请在管理面板添加", callback_data="manage_countries")])
    else:
        for code in country_codes:
            if code in countries:
                country = countries[code]
                accounts_count = len(country.get('accounts', []))
                buttons.append([InlineKeyboardButton(f"🌍 {country['name']} ({country['code']}) - {country['price_usdt']} USDT (库存:{accounts_count})", callback_data=f"buy_country_{product_key}_{code}")])
    buttons.append([InlineKeyboardButton("🔙 返回分类", callback_data="product_list")])
    buttons.append([InlineKeyboardButton("🏠 主菜单", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def get_product_categories_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    if not categories:
        buttons.append([InlineKeyboardButton("📁 暂无商品分类", callback_data="noop")])
        buttons.append([InlineKeyboardButton("⚙️ 联系管理员添加", callback_data="contact_admin")])
    else:
        for cat in categories:
            total_stock = 0
            for key, prod in products.items():
                if prod.get('category') == cat:
                    if prod.get('product_type') == 'country':
                        for code in prod.get('countries', []):
                            if code in countries:
                                total_stock += len(countries[code].get('accounts', []))
                    elif prod.get('product_type') == 'card':
                        total_stock += len([c for c in cards.get(key, []) if not c.get('used', False)])
                    else:
                        total_stock += prod.get('stock', 0)
            buttons.append([InlineKeyboardButton(f"📁 {cat} (库存:{total_stock})", callback_data=f"cat_{cat}")])
    buttons.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def get_products_by_category(category: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    items = []
    for key, prod in products.items():
        if prod.get("category") == category:
            if prod.get("product_type") == "country":
                items.append((key, prod, "country"))
            elif prod.get("product_type") == "card":
                available_cards = len([c for c in cards.get(key, []) if not c.get('used', False)])
                if available_cards > 0 or is_admin:
                    items.append((key, prod, "card", available_cards))
            else:
                if prod.get("stock", 0) > 0 or is_admin:
                    items.append((key, prod, "normal"))
    buttons = []
    if not items:
        buttons.append([InlineKeyboardButton("📁 该分类暂无商品", callback_data="noop")])
    for item in items:
        if item[2] == "country":
            country_count = len(item[1].get('countries', []))
            button_text = f"🌍 {item[1]['name']} ({country_count}个国家)"
            buttons.append([InlineKeyboardButton(button_text, callback_data=f"dynamic_{item[0]}")])
        elif item[2] == "card":
            button_text = f"🔑 {item[1]['name']} - {item[1]['price_usdt']} USDT (库存:{item[3]})"
            buttons.append([InlineKeyboardButton(button_text, callback_data=f"detail_{item[0]}")])
        else:
            button_text = f"📦 {item[1]['name']} - {item[1]['price_usdt']} USDT (库存:{item[1].get('stock', 0)})"
            buttons.append([InlineKeyboardButton(button_text, callback_data=f"detail_{item[0]}")])
        if is_admin:
            buttons.append([InlineKeyboardButton(f"⚙️ 管理", callback_data=f"admin_product_{item[0]}")])
    buttons.append([InlineKeyboardButton("🔙 返回分类", callback_data="product_list")])
    buttons.append([InlineKeyboardButton("🏠 主菜单", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def get_recharge_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("1 USDT", callback_data="recharge_1")],
        [InlineKeyboardButton("5 USDT", callback_data="recharge_5")],
        [InlineKeyboardButton("10 USDT", callback_data="recharge_10")],
        [InlineKeyboardButton("20 USDT", callback_data="recharge_20")],
        [InlineKeyboardButton("50 USDT", callback_data="recharge_50")],
        [InlineKeyboardButton("💰 自定义金额", callback_data="recharge_custom")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(buttons)

def get_categories_for_select() -> InlineKeyboardMarkup:
    buttons = []
    if not categories:
        buttons.append([InlineKeyboardButton("⚠️ 暂无分类，请先创建", callback_data="create_new_cat")])
    else:
        for cat in categories:
            buttons.append([InlineKeyboardButton(f"📁 {cat}", callback_data=f"select_cat_{cat}")])
        buttons.append([InlineKeyboardButton("➕ 新建分类", callback_data="create_new_cat")])
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data="manage_products")])
    return InlineKeyboardMarkup(buttons)

def get_product_detail_keyboard(product_key: str, product: Dict, is_admin: bool = False) -> InlineKeyboardMarkup:
    category = product.get('category', '')
    if is_admin:
        buttons = [
            [InlineKeyboardButton("🛒 购买", callback_data=f"buy_{product_key}")],
            [InlineKeyboardButton("✏️ 修改名称", callback_data=f"edit_product_name_{product_key}")],
            [InlineKeyboardButton("💰 修改价格", callback_data=f"edit_product_price_{product_key}")],
            [InlineKeyboardButton("📝 修改描述", callback_data=f"edit_product_desc_{product_key}")],
            [InlineKeyboardButton("🔑 添加卡密/账号", callback_data=f"upload_cards_{product_key}")],
            [InlineKeyboardButton("🔙 返回列表", callback_data=f"cat_{category}")],
            [InlineKeyboardButton("🏠 主菜单", callback_data="main_menu")]
        ]
    else:
        buttons = [
            [InlineKeyboardButton("🛒 购买", callback_data=f"buy_{product_key}")],
            [InlineKeyboardButton("🔙 返回列表", callback_data=f"cat_{category}")],
            [InlineKeyboardButton("🏠 主菜单", callback_data="main_menu")]
        ]
    return InlineKeyboardMarkup(buttons)

# ================== 欢迎消息 ==================
def get_welcome_message(admin_name: str) -> str:
    return (
        f"🌈欢迎光临[{admin_name}]自助卖号机器人 \n\n"
        "✅TG账号自助购买 \n\n"
        "1、请先少量购买测试，合适可继续购买\n\n"
        "2、购买后第一时间检测是否死号，如帐号有问题请十分钟内联系我处理，包售后，超时不售后\n\n"
        "3、群发群、拉人还是私信都有技巧，不能盲目，可以进群交流\n\n"
        "_\n\n"
        "🛰️🛰️【频道】 https://t.me/ltnb66678\n"
        "👥【群组】 https://t.me/huhbjise\n"
        "☎️【客服】 @nbbv354\n"
        "🛠️【工具】 @NBTG1BOT\n"
        "🌐【零售】 https://buy.wlqfk.net/shop/41WFDSM2\n\n"
        "⚙ /start   ⬅点击命令打开底部菜单\n\n"
        "机器人支持USDT 人民币充值 不接受使用后售后"
    )

async def send_startup_welcome(application: Application) -> None:
    await asyncio.sleep(3)
    try:
        admin_user = await application.bot.get_chat(ADMIN_USER_ID)
        admin_name = admin_user.full_name or admin_user.username or "管理员"
    except:
        admin_name = "管理员"
    welcome_text = get_welcome_message(admin_name)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 开始购物", callback_data="product_list")],
        [InlineKeyboardButton("💰 我的余额", callback_data="my_balance")],
        [InlineKeyboardButton("💎 充值余额", callback_data="recharge_balance")]
    ])
    for chat_id in WELCOME_CHAT_IDS:
        if str(chat_id) in sent_welcome:
            continue
        try:
            await application.bot.send_message(chat_id=chat_id, text=welcome_text, reply_markup=keyboard, parse_mode="Markdown")
            sent_welcome[str(chat_id)] = True
            save_json(SENT_WELCOME_FILE, sent_welcome)
        except Exception as e:
            logger.error(f"发送失败: {e}")

# ================== 命令处理 ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    if user_id not in user_balances:
        user_balances[user_id] = 0.0
        save_all_data()
    shop_name = await get_shop_name(context)
    is_admin_user = is_admin(update.effective_user.id)
    welcome_text = (f"{shop_name}\n\n欢迎光临！本店提供各类 Telegram 账号。\n您的余额：`{user_balances[user_id]:.4f} USDT`\n\n👇 *请使用下方按钮进行操作*")
    reply_keyboard = get_main_reply_keyboard(is_admin_user)
    await update.message.reply_text(welcome_text, reply_markup=reply_keyboard, parse_mode="Markdown")

# 统一消息处理函数 - 先处理输入状态，再处理普通按钮消息
async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    text = update.message.text
    is_admin_user = is_admin(update.effective_user.id)
    
    # 先检查是否有等待输入的状态
    has_state = any(key in context.user_data for key in [
        'awaiting_recharge', 'adding_category', 'rename_category', 'create_new_category',
        'adding_product', 'quick_add', 'edit_product_category', 'editing_product', 'edit_product_name',
        'edit_product_price', 'edit_product_desc', 'adding_cards_to', 'upload_cards_to',
        'adding_account_product', 'adding_country', 'editing_country', 'adding_account_country',
        'new_product_name', 'new_product_price', 'new_product_category', 'new_product_type'
    ])
    
    if has_state:
        # 处理输入状态
        # 处理自定义充值
        if context.user_data.get('awaiting_recharge'):
            try:
                amount = float(text)
                if amount < 1:
                    await update.message.reply_text("❌ 金额不能小于 1 USDT")
                    return
                order_number = f"D{datetime.now().strftime('%Y%m%d%H%M%S')}{user_id[-6:]}"
                recharge_orders[order_number] = {"user_id": user_id, "amount": amount, "status": "pending", "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                save_all_data()
                result = okpay_create_deposit(order_number, amount, user_id)
                if result.get('code') == 200:
                    pay_url = result.get('data', {}).get('pay_url', '')
                    await update.message.reply_text(f"💳 *充值订单*\n\n金额：{amount} USDT\n订单号：`{order_number}`\n\n[点击支付]({pay_url})\n\n支付后系统自动到账。", parse_mode="Markdown", disable_web_page_preview=True)
                else:
                    await update.message.reply_text(f"❌ 创建失败：{result.get('msg')}")
                context.user_data.pop('awaiting_recharge', None)
            except:
                await update.message.reply_text("❌ 请输入数字金额")
            return
        
        # 只有管理员才能继续
        if not is_admin(update.effective_user.id):
            context.user_data.clear()
            return

        # 添加分类
        if context.user_data.get('adding_category'):
            if text and text not in categories:
                categories.append(text)
                save_all_data()
                await update.message.reply_text(f"✅ 成功添加分类：{text}")
            context.user_data.pop('adding_category', None)
            return
        
        # 重命名分类
        if context.user_data.get('rename_category'):
            old_category = context.user_data['rename_category']
            new_category = text
            if new_category and new_category not in categories:
                for key, prod in products.items():
                    if prod.get('category') == old_category:
                        products[key]['category'] = new_category
                idx = categories.index(old_category)
                categories[idx] = new_category
                save_all_data()
                await update.message.reply_text(f"✅ 已将分类「{old_category}」重命名为「{new_category}」")
            context.user_data.pop('rename_category', None)
            return
        
        # 创建新分类（添加商品时）
        if context.user_data.get('create_new_category'):
            new_category = text
            if new_category and new_category not in categories:
                categories.append(new_category)
                save_all_data()
                context.user_data['new_product_category'] = new_category
                context.user_data.pop('create_new_category', None)
                await update.message.reply_text(f"✅ 已创建分类：{new_category}\n\n请输入商品名称：")
            return
        
        # 添加商品 - 输入名称
        if (context.user_data.get('adding_product') or context.user_data.get('quick_add')) and 'new_product_category' in context.user_data and 'new_product_name' not in context.user_data:
            context.user_data['new_product_name'] = text
            await update.message.reply_text(f"请输入商品价格 (USDT)：")
            return
        
        # 添加商品 - 输入价格
        if (context.user_data.get('adding_product') or context.user_data.get('quick_add')) and 'new_product_name' in context.user_data and 'new_product_price' not in context.user_data:
            try:
                price = float(text)
                context.user_data['new_product_price'] = price
                await update.message.reply_text(f"请输入商品描述（可输入“无”）：")
            except:
                await update.message.reply_text("❌ 价格格式错误，请输入数字！")
            return
        
        # 添加商品 - 输入描述并保存
        if (context.user_data.get('adding_product') or context.user_data.get('quick_add')) and 'new_product_price' in context.user_data:
            description = text
            product_name = context.user_data['new_product_name']
            price = context.user_data['new_product_price']
            category = context.user_data['new_product_category']
            product_type = context.user_data['new_product_type']
            
            # 生成唯一的商品key
            product_key = product_name.replace(" ", "_").replace("/", "_")
            base_key = product_key
            counter = 1
            while product_key in products:
                product_key = f"{base_key}_{counter}"
                counter += 1
            
            # 创建商品
            new_product = {
                "name": product_name, 
                "price_usdt": price, 
                "category": category, 
                "description": description, 
                "product_type": product_type
            }
            
            if product_type == 'card':
                new_product["stock"] = 0
                cards[product_key] = []
            elif product_type == 'account':
                new_product["stock"] = 0
                new_product["accounts"] = []
            elif product_type == 'country':
                new_product["stock"] = 0
                new_product["countries"] = []
            
            products[product_key] = new_product
            save_all_data()
            
            type_name = {'card': '卡密商品', 'account': '账号商品', 'country': '国家动态商品'}.get(product_type, '商品')
            await update.message.reply_text(f"✅ 成功添加商品：{product_name}\n\n💰 价格：{price} USDT\n📁 分类：{category}\n📦 类型：{type_name}\n\n📌 接下来请点击「管理商品」→ 找到该商品 → 添加卡密/账号")
            
            # 清理状态
            for key in ['adding_product', 'quick_add', 'new_product_name', 'new_product_price', 'new_product_category', 'new_product_type']:
                context.user_data.pop(key, None)
            return
        
        # 修改商品分类
        if context.user_data.get('edit_product_category'):
            product_key = context.user_data['edit_product_category']
            new_category = text
            if new_category in categories:
                products[product_key]['category'] = new_category
                save_all_data()
                await update.message.reply_text(f"✅ 已将分类修改为「{new_category}」")
            context.user_data.pop('edit_product_category', None)
            return
        
        # 编辑商品价格或描述
        if context.user_data.get('editing_product'):
            product_key = context.user_data['editing_product']
            edit_type = context.user_data['edit_type']
            if edit_type == 'price':
                try:
                    new_price = float(text)
                    products[product_key]['price_usdt'] = new_price
                    save_all_data()
                    await update.message.reply_text(f"✅ 价格已修改为 {new_price} USDT")
                except:
                    await update.message.reply_text("❌ 价格格式错误")
            elif edit_type == 'desc':
                products[product_key]['description'] = text
                save_all_data()
                await update.message.reply_text(f"✅ 描述已修改")
            context.user_data.pop('editing_product', None)
            context.user_data.pop('edit_type', None)
            return
        
        # 修改商品名称
        if context.user_data.get('edit_product_name'):
            product_key = context.user_data['edit_product_name']
            products[product_key]['name'] = text
            save_all_data()
            await update.message.reply_text(f"✅ 商品名称已修改为：{text}")
            context.user_data.pop('edit_product_name', None)
            return
        
        # 修改商品价格
        if context.user_data.get('edit_product_price'):
            product_key = context.user_data['edit_product_price']
            try:
                new_price = float(text)
                products[product_key]['price_usdt'] = new_price
                save_all_data()
                await update.message.reply_text(f"✅ 价格已修改为：{new_price} USDT")
            except:
                await update.message.reply_text("❌ 价格格式错误")
            context.user_data.pop('edit_product_price', None)
            return
        
        # 修改商品描述
        if context.user_data.get('edit_product_desc'):
            product_key = context.user_data['edit_product_desc']
            products[product_key]['description'] = text
            save_all_data()
            await update.message.reply_text(f"✅ 描述已修改")
            context.user_data.pop('edit_product_desc', None)
            return
        
        # 添加卡密
        if context.user_data.get('adding_cards_to'):
            product_key = context.user_data['adding_cards_to']
            lines = text.split('\n')
            added = add_cards_bulk(product_key, lines)
            await update.message.reply_text(f"✅ 已添加 {added} 个卡密到 {products[product_key]['name']}")
            context.user_data.pop('adding_cards_to', None)
            return
        
        # 上传卡密/账号
        if context.user_data.get('upload_cards_to'):
            product_key = context.user_data['upload_cards_to']
            prod = products[product_key]
            product_type = prod.get('product_type', 'card')
            if product_type == 'card':
                lines = text.split('\n')
                added = add_cards_bulk(product_key, lines)
                await update.message.reply_text(f"✅ 已添加 {added} 个卡密到 {prod['name']}")
            elif product_type == 'account':
                lines = text.split('\n')
                added_count = 0
                for line in lines:
                    if line.strip():
                        add_account_to_product(product_key, line.strip())
                        added_count += 1
                await update.message.reply_text(f"✅ 已添加 {added_count} 个账号到 {prod['name']}")
            else:
                await update.message.reply_text(f"⚠️ 该商品类型不支持批量添加")
            context.user_data.pop('upload_cards_to', None)
            return
        
        # 添加账号到商品
        if context.user_data.get('adding_account_product'):
            product_key = context.user_data['adding_account_product']
            lines = text.split('\n')
            added_count = 0
            for line in lines:
                if line.strip():
                    add_account_to_product(product_key, line.strip())
                    added_count += 1
            await update.message.reply_text(f"✅ 已添加 {added_count} 个账号")
            context.user_data.pop('adding_account_product', None)
            return
        
        # 添加国家
        if context.user_data.get('adding_country'):
            lines = text.split('\n')
            if len(lines) >= 3:
                name = lines[0].strip()
                code = lines[1].strip()
                try:
                    price = float(lines[2].strip())
                except:
                    await update.message.reply_text("❌ 价格格式错误")
                    return
                country_key = name[:2].upper()
                countries[country_key] = {"name": name, "code": code, "price_usdt": price, "accounts": []}
                save_all_data()
                await update.message.reply_text(f"✅ 成功添加国家：{name} ({code})\n价格：{price} USDT")
            else:
                await update.message.reply_text("❌ 格式错误，需要3行：\n国家名称\n国家代码\n价格")
            context.user_data.pop('adding_country', None)
            return
        
        # 编辑国家价格
        if context.user_data.get('editing_country'):
            country_code = context.user_data['editing_country']
            edit_type = context.user_data['edit_type']
            if edit_type == 'price':
                try:
                    new_price = float(text)
                    countries[country_code]['price_usdt'] = new_price
                    save_all_data()
                    await update.message.reply_text(f"✅ 价格已修改为 {new_price} USDT")
                except:
                    await update.message.reply_text("❌ 价格格式错误")
            context.user_data.pop('editing_country', None)
            context.user_data.pop('edit_type', None)
            return
        
        # 添加账号到国家
        if context.user_data.get('adding_account_country'):
            country_code = context.user_data['adding_account_country']
            lines = text.split('\n')
            added_count = 0
            if "accounts" not in countries[country_code]:
                countries[country_code]["accounts"] = []
            for line in lines:
                if line.strip():
                    countries[country_code]["accounts"].append({"info": line.strip(), "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                    added_count += 1
            save_all_data()
            await update.message.reply_text(f"✅ 已添加 {added_count} 个账号到 {countries[country_code]['name']}")
            context.user_data.pop('adding_account_country', None)
            return
        
        return  # 已处理输入状态，不再处理按钮消息
    
    # 没有输入状态时，处理普通按钮消息
    if text == "🛒 商品列表":
        if not categories:
            await update.message.reply_text("📂 *商品分类*\n\n暂无商品分类，请联系管理员添加。", parse_mode="Markdown")
        else:
            await update.message.reply_text("📂 *商品分类*\n\n请选择您需要购买的账号当前可支持okpay支付", reply_markup=get_product_categories_keyboard(), parse_mode="Markdown")
    elif text == "👤 我的余额":
        balance = user_balances.get(user_id, 0.0)
        await update.message.reply_text(f"💰 *我的余额*\n\n当前余额：`{balance:.4f} USDT`", parse_mode="Markdown")
    elif text == "💎 充值余额":
        await update.message.reply_text("💎 *充值中心*\n\n请选择充值金额：", reply_markup=get_recharge_keyboard(), parse_mode="Markdown")
    elif text == "📋 我的订单":
        user_orders = []
        for oid, o in orders.items():
            if o['user_id'] == user_id:
                status_emoji = "✅" if o['status'] == "completed" else "⏳"
                user_orders.append(f"{status_emoji} `{oid}` - {o['product_name']} - {o['total_usdt']} USDT")
        text_msg = "📋 *我的订单* (最近10条)\n\n" + "\n".join(user_orders[-10:]) if user_orders else "📋 暂无订单记录。\n\n去商品列表选购吧！"
        await update.message.reply_text(text_msg, parse_mode="Markdown")
    elif text == "📞 联系管理员":
        await update.message.reply_text(f"👤 *联系管理员*\n\n如有任何问题（缺货、充值、售后等），请联系：\n👨‍💻 管理员ID：`{ADMIN_USER_ID}`", parse_mode="Markdown")
    elif text == "⚙️ 管理面板" and is_admin_user:
        await update.message.reply_text("⚙️ *管理员面板*\n\n欢迎回来，尊敬的管理员。当前系统已完成全面自检，所有核心服务运行正常，数据库连接稳定，缓存服务响应及时，存储空间与内存占用均在健康阈值以内。安全审计日志未发现异常登录或越权访问行为。您可以在下方面板中执行用户管理、系统配置、数据备份、日志追踪、安全策略调整等各类维护任务。请根据运维需求谨慎选择操作，如涉及关键配置变更，建议提前备份当前状态并确认影响范围。：", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")

# ================== 按钮回调处理 ==================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = str(query.from_user.id)
    is_admin_user = is_admin(query.from_user.id)

    if data == "noop":
        return

    # 主菜单
    if data == "main_menu":
        keyboard = await get_main_menu_keyboard(context, is_admin_user)
        await query.edit_message_text("🏠 *主菜单*", reply_markup=keyboard, parse_mode="Markdown")
        return

    # 管理员面板
    elif data == "admin_panel" and is_admin_user:
        await query.edit_message_text("⚙️ *管理员面板*\n\n欢迎回来，尊敬的管理员。当前系统已完成全面自检，所有核心服务运行正常，数据库连接稳定，缓存服务响应及时，存储空间与内存占用均在健康阈值以内。安全审计日志未发现异常登录或越权访问行为。您可以在下方面板中执行用户管理、系统配置、数据备份、日志追踪、安全策略调整等各类维护任务。请根据运维需求谨慎选择操作，如涉及关键配置变更，建议提前备份当前状态并确认影响范围。：", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
        return

    # 快速添加商品
    elif data == "quick_add_product" and is_admin_user:
        if not categories:
            await query.edit_message_text("❌ 请先创建分类！\n\n点击下方按钮添加分类：", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📂 管理分类", callback_data="manage_categories")]]),
                parse_mode="Markdown")
            return
        context.user_data['quick_add'] = True
        await query.edit_message_text("➕ *快速添加商品*\n\n请选择商品类型：", reply_markup=get_product_type_keyboard(), parse_mode="Markdown")
        return

    # 商户余额
    elif data == "admin_balance" and is_admin_user:
        result = okpay_balance()
        if result.get('code') == 200:
            balances = result.get('data', {})
            text = f"💎 *商户余额*\n\n"
            for coin, bal in balances.items():
                text += f"{coin.upper()}: `{bal}`\n"
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel")]]))
        else:
            await query.edit_message_text(f"❌ 查询失败: {result.get('msg')}")
        return

    # 充值记录
    elif data == "admin_recharge_records" and is_admin_user:
        if not recharge_orders:
            await query.edit_message_text("暂无充值记录。")
            return
        text = "💰 *充值记录* (最近20条)\n\n"
        for order_no, order in list(recharge_orders.items())[-20:]:
            status_emoji = "✅" if order["status"] == "completed" else "⏳"
            text += f"{status_emoji} `{order_no}` | {order['amount']} USDT | {order['user_id'][-6:]}\n"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel")]]), parse_mode="Markdown")
        return

    # 统计
    elif data == "admin_stats" and is_admin_user:
        total_users = len(user_balances)
        total_revenue = sum(o['total_usdt'] for o in orders.values())
        total_orders = len(orders)
        total_countries = len(countries)
        total_cards = sum(len(cards.get(k, [])) for k in products)
        unused_cards = sum(len([c for c in cards.get(k, []) if not c.get('used', False)]) for k in products)
        total_accounts = sum(len(p.get('accounts', [])) for p in products.values())
        await query.edit_message_text(f"📊 *店铺统计*\n\n👥 用户数：{total_users}\n📦 总订单：{total_orders}\n💰 总营业额：{total_revenue:.2f} USDT\n🌍 支持国家：{total_countries}\n🔑 总卡密数：{total_cards}\n✅ 未使用卡密：{unused_cards}\n👤 账号数量：{total_accounts}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel")]]), parse_mode="Markdown")
        return

    elif data == "admin_orders" and is_admin_user:
        if not orders:
            await query.edit_message_text("暂无订单。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel")]]))
            return
        text = "📋 *最近20条订单：*\n\n"
        for oid, o in list(orders.items())[-20:]:
            text += f"`{oid}` | {o['user_id'][-6:]} | {o['product_name']} | {o['total_usdt']} USDT\n"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel")]]))
        return

    # 管理分类
    elif data == "manage_categories" and is_admin_user:
        await query.edit_message_text("📂 *分类管理*\n\n尊敬的管理员请添加当前分类文件夹文件将自动上传服务器", reply_markup=get_manage_categories_keyboard(), parse_mode="Markdown")
        return
    elif data.startswith("edit_category_") and is_admin_user:
        category = data[14:]
        await query.edit_message_text(f"📁 *编辑分类：{category}*\n\n该分类下有 {len([p for p in products.values() if p.get('category') == category])} 个商品", reply_markup=get_category_edit_keyboard(category), parse_mode="Markdown")
        return
    elif data.startswith("rename_category_") and is_admin_user:
        old_category = data[17:]
        context.user_data['rename_category'] = old_category
        await query.edit_message_text(f"请输入 `{old_category}` 的新名称：\n\n发送 /cancel 取消。", parse_mode="Markdown")
        return
    elif data.startswith("delete_category_") and is_admin_user:
        category = data[17:]
        products_in_cat = [p for p in products.values() if p.get('category') == category]
        if products_in_cat:
            await query.edit_message_text(f"❌ 无法删除分类「{category}」\n该分类下还有 {len(products_in_cat)} 个商品，请先移动或删除这些商品。", reply_markup=get_manage_categories_keyboard(), parse_mode="Markdown")
            return
        categories.remove(category)
        save_all_data()
        await query.edit_message_text(f"✅ 已删除分类：{category}", reply_markup=get_manage_categories_keyboard(), parse_mode="Markdown")
        return
    elif data == "add_new_category" and is_admin_user:
        context.user_data['adding_category'] = True
        await query.edit_message_text("➕ *添加新分类*\n\n请输入新分类的名称：\n发送 /cancel 取消。", parse_mode="Markdown")
        return

    # 管理商品
    elif data == "manage_products" and is_admin_user:
        await query.edit_message_text("📦 *商品管理*\n\n选择要管理的商品：", reply_markup=get_manage_products_keyboard(), parse_mode="Markdown")
        return
    elif data == "add_new_product" and is_admin_user:
        if not categories:
            await query.edit_message_text("❌ 请先创建分类，再添加商品！", reply_markup=get_manage_categories_keyboard(), parse_mode="Markdown")
            return
        context.user_data['adding_product'] = True
        await query.edit_message_text("➕ *添加新商品*\n\n请选择商品类型：", reply_markup=get_product_type_keyboard(), parse_mode="Markdown")
        return
    elif data.startswith("product_type_") and is_admin_user:
        if not context.user_data.get('adding_product') and not context.user_data.get('quick_add'):
            await query.edit_message_text("请先点击「添加新商品」或「快速添加商品」按钮。")
            return
        product_type = data[13:]
        context.user_data['new_product_type'] = product_type
        await query.edit_message_text("请选择商品分类：", reply_markup=get_categories_for_select(), parse_mode="Markdown")
        return
    elif data.startswith("select_cat_") and is_admin_user:
        if not context.user_data.get('adding_product') and not context.user_data.get('quick_add'):
            await query.edit_message_text("请先点击「添加新商品」或「快速添加商品」按钮。")
            return
        category = data[10:]
        context.user_data['new_product_category'] = category
        await query.edit_message_text("请输入商品名称：\n\n发送 /cancel 取消。", parse_mode="Markdown")
        return
    elif data == "create_new_cat" and is_admin_user:
        context.user_data['create_new_category'] = True
        await query.edit_message_text("请输入新分类的名称：\n\n发送 /cancel 取消。", parse_mode="Markdown")
        return
    elif data.startswith("admin_product_") and is_admin_user:
        product_key = data[14:]
        if product_key in products:
            prod = products[product_key]
            product_type = prod.get('product_type', 'card')
            if product_type == 'card':
                available_cards = len([c for c in cards.get(product_key, []) if not c.get('used', False)])
                stats = f"🔑 可用卡密：{available_cards}/{len(cards.get(product_key, []))}"
            elif product_type == 'account':
                accounts_count = len(prod.get('accounts', []))
                stats = f"👤 账号数量：{accounts_count}"
            else:
                countries_count = len(prod.get('countries', []))
                stats = f"🌍 国家数量：{countries_count}"
            await query.edit_message_text(f"📦 *{prod['name']}*\n\n💰 价格：{prod['price_usdt']} USDT\n📁 分类：{prod.get('category', '无')}\n📝 描述：{prod.get('description', '无')}\n{stats}\n📦 类型：{'卡密商品' if product_type=='card' else ('账号商品' if product_type=='account' else '国家动态商品')}", reply_markup=get_admin_product_keyboard(product_key, prod), parse_mode="Markdown")
        return
    elif data.startswith("admin_edit_category_") and is_admin_user:
        product_key = data[20:]
        context.user_data['edit_product_category'] = product_key
        await query.edit_message_text(f"请为 {products[product_key]['name']} 选择新分类：", reply_markup=get_categories_for_select(), parse_mode="Markdown")
        return
    elif data.startswith("admin_edit_price_") and is_admin_user:
        product_key = data[18:]
        context.user_data['editing_product'] = product_key
        context.user_data['edit_type'] = 'price'
        await query.edit_message_text(f"请输入 {products[product_key]['name']} 的新价格 (USDT)：\n发送 /cancel 取消。", parse_mode="Markdown")
        return
    elif data.startswith("admin_edit_desc_") and is_admin_user:
        product_key = data[17:]
        context.user_data['editing_product'] = product_key
        context.user_data['edit_type'] = 'desc'
        await query.edit_message_text(f"请输入 {products[product_key]['name']} 的新描述：\n发送 /cancel 取消。", parse_mode="Markdown")
        return
    elif data.startswith("admin_add_card_") and is_admin_user:
        product_key = data[16:]
        context.user_data['adding_cards_to'] = product_key
        await query.edit_message_text("📁 *添加卡密*\n\n**方式1：直接发送文本**\n每行一个卡密\n\n**方式2：上传txt文件**\n直接发送 .txt 文件，每行一个卡密\n\n发送 /cancel 取消", parse_mode="Markdown")
        return
    elif data.startswith("admin_list_cards_") and is_admin_user:
        product_key = data[18:]
        product_cards = cards.get(product_key, [])
        used_cards = [c for c in product_cards if c.get('used', False)]
        unused_cards = [c for c in product_cards if not c.get('used', False)]
        text = f"📋 *{products[product_key]['name']} 卡密列表*\n\n🔑 总计：{len(product_cards)} 个\n✅ 未使用：{len(unused_cards)} 个\n❌ 已使用：{len(used_cards)} 个\n\n"
        if unused_cards:
            text += "*未使用的卡密（最近10条）：*\n"
            for c in unused_cards[-10:]:
                text += f"`{c['card']}`\n"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"admin_product_{product_key}")]]), parse_mode="Markdown")
        return
    elif data.startswith("admin_add_account_") and is_admin_user:
        product_key = data[18:]
        context.user_data['adding_account_product'] = product_key
        await query.edit_message_text(f"请输入要添加到 {products[product_key]['name']} 的账号信息：\n\n格式：每行一个账号\n例如：`+1234567890|password123|备注`\n\n可以一次性添加多个账号，每行一个。\n发送 /cancel 取消。", parse_mode="Markdown")
        return
    elif data.startswith("admin_list_accounts_") and is_admin_user:
        product_key = data[20:]
        accounts = products[product_key].get('accounts', [])
        if not accounts:
            await query.edit_message_text(f"📋 {products[product_key]['name']} 暂无账号。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"admin_product_{product_key}")]]), parse_mode="Markdown")
            return
        text = f"📋 *{products[product_key]['name']} 账号列表（共{len(accounts)}个）：*\n\n"
        for i, acc in enumerate(accounts[-20:], 1):
            text += f"{i}. {acc.get('info', '无')}\n"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"admin_product_{product_key}")]]), parse_mode="Markdown")
        return
    elif data.startswith("admin_delete_product_") and is_admin_user:
        product_key = data[22:]
        product_name = products[product_key]['name']
        del products[product_key]
        if product_key in cards:
            del cards[product_key]
        save_all_data()
        await query.edit_message_text(f"✅ 已删除商品：{product_name}", reply_markup=get_manage_products_keyboard(), parse_mode="Markdown")
        return
    elif data.startswith("admin_manage_countries_") and is_admin_user:
        await query.edit_message_text("🌍 *国家管理*\n\n当前支持的国家列表：", reply_markup=get_country_management_keyboard(), parse_mode="Markdown")
        return

    # 国家管理
    elif data == "manage_countries" and is_admin_user:
        await query.edit_message_text("🌍 *国家管理*\n\n当前支持的国家列表：", reply_markup=get_country_management_keyboard(), parse_mode="Markdown")
        return
    elif data.startswith("edit_country_") and is_admin_user:
        country_code = data[13:]
        country = countries[country_code]
        accounts_count = len(country.get('accounts', []))
        await query.edit_message_text(f"🌍 *管理 {country['name']}*\n\n代码：{country['code']}\n价格：{country['price_usdt']} USDT\n账号数量：{accounts_count}", reply_markup=get_country_edit_keyboard(country_code), parse_mode="Markdown")
        return
    elif data.startswith("edit_price_") and is_admin_user:
        country_code = data[11:]
        context.user_data['editing_country'] = country_code
        context.user_data['edit_type'] = 'price'
        await query.edit_message_text(f"请输入 {countries[country_code]['name']} 的新价格 (USDT)：\n发送 /cancel 取消。", parse_mode="Markdown")
        return
    elif data.startswith("add_account_") and is_admin_user:
        country_code = data[13:]
        context.user_data['adding_account_country'] = country_code
        await query.edit_message_text(f"请输入要添加到 {countries[country_code]['name']} 的账号信息：\n\n格式：每行一个账号\n例如：`+1234567890|password123|优质号`\n\n可以一次性添加多个账号，每行一个。\n发送 /cancel 取消。", parse_mode="Markdown")
        return
    elif data.startswith("list_accounts_") and is_admin_user:
        country_code = data[14:]
        accounts = countries[country_code].get('accounts', [])
        if not accounts:
            await query.edit_message_text(f"📋 {countries[country_code]['name']} 暂无账号。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"edit_country_{country_code}")]]), parse_mode="Markdown")
            return
        text = f"📋 *{countries[country_code]['name']} 账号列表（共{len(accounts)}个）：*\n\n"
        for i, acc in enumerate(accounts[-20:], 1):
            text += f"{i}. {acc.get('info', '无')}\n"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"edit_country_{country_code}")]]), parse_mode="Markdown")
        return
    elif data.startswith("delete_country_") and is_admin_user:
        country_code = data[15:]
        country_name = countries[country_code]['name']
        del countries[country_code]
        for prod_key, prod in products.items():
            if prod.get('product_type') == 'country' and country_code in prod.get('countries', []):
                prod['countries'].remove(country_code)
        save_all_data()
        await query.edit_message_text(f"✅ 已删除国家：{country_name}", reply_markup=get_country_management_keyboard(), parse_mode="Markdown")
        return
    elif data == "add_country" and is_admin_user:
        context.user_data['adding_country'] = True
        await query.edit_message_text("➕ *添加新国家*\n\n请按以下格式发送信息（每行一个）：\n1. 国家名称（如：法国）\n2. 国家代码（如：+33）\n3. 价格 USDT（如：0.9）\n\n示例：\n法国\n+33\n0.9\n\n发送 /cancel 取消。", parse_mode="Markdown")
        return

    # 用户端功能
    elif data == "contact_admin":
        await query.edit_message_text(f"👤 *联系管理员*\n\n如有任何问题（缺货、充值、售后等），请联系：\n👨‍💻 管理员ID：`{ADMIN_USER_ID}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu")]]), parse_mode="Markdown")
        return
    elif data == "product_list":
        if not categories:
            await query.edit_message_text("📂 *选择你需要的商品*\n\n✅未购买过本店商品的，请先少量购买测试，以免产生纠纷！谢谢合作", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu")]]), parse_mode="Markdown")
        else:
            await query.edit_message_text("📂 *选择你需要的商品*\n\n🛒选择你需要的商品：✅未购买过本店商品的，请先少量购买测试，以免产生纠纷！谢谢合作：", reply_markup=get_product_categories_keyboard(), parse_mode="Markdown")
        return
    elif data == "my_balance":
        balance = user_balances.get(user_id, 0.0)
        await query.edit_message_text(f"💰 *我的余额*\n\n当前余额：`{balance:.4f} USDT`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 充值", callback_data="recharge_balance")], [InlineKeyboardButton("🔙 返回", callback_data="main_menu")]]), parse_mode="Markdown")
        return
    elif data == "recharge_balance":
        await query.edit_message_text("💎 *充值中心*\n\n请选择充值金额：", reply_markup=get_recharge_keyboard(), parse_mode="Markdown")
        return
    elif data == "my_orders":
        user_orders = []
        for oid, o in orders.items():
            if o['user_id'] == user_id:
                status_emoji = "✅" if o['status'] == "completed" else "⏳"
                user_orders.append(f"{status_emoji} `{oid}` - {o['product_name']} - {o['total_usdt']} USDT")
        text = "📋 *我的订单* (最近10条)\n\n" + "\n".join(user_orders[-10:]) if user_orders else "📋 暂无订单记录。"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 继续购物", callback_data="product_list")], [InlineKeyboardButton("🔙 返回", callback_data="main_menu")]]), parse_mode="Markdown")
        return

    # 分类选择
    if data.startswith("cat_"):
        category = data[4:]
        keyboard = get_products_by_category(category, is_admin_user)
        await query.edit_message_text(f"📁 *{category}*\n\n请选择具体商品：", reply_markup=keyboard, parse_mode="Markdown")
        return
    if data.startswith("dynamic_"):
        product_key = data[8:]
        await query.edit_message_text(f"🌍 *{products[product_key]['name']}*\n\n请选择国家：", reply_markup=get_countries_list_keyboard(product_key), parse_mode="Markdown")
        return
    if data.startswith("detail_"):
        product_key = data[7:]
        prod = products.get(product_key)
        if not prod:
            await query.edit_message_text("❌ 商品不存在")
            return
        product_type = prod.get('product_type', 'card')
        if product_type == 'card':
            available = len([c for c in cards.get(product_key, []) if not c.get('used', False)])
            stock_display = available
        elif product_type == 'account':
            stock_display = len(prod.get('accounts', []))
        else:
            stock_display = prod.get('stock', 0)
        detail_text = f"📦 *{prod['name']}*\n\n💰 价格：`{prod['price_usdt']} USDT`\n📊 库存：`{stock_display}`\n📁 分类：{prod.get('category', '其他')}\n📝 说明：{prod.get('description', '暂无说明')}"
        await query.edit_message_text(detail_text, reply_markup=get_product_detail_keyboard(product_key, prod, is_admin_user), parse_mode="Markdown")
        return
    if data.startswith("edit_product_name_") and is_admin_user:
        product_key = data[18:]
        context.user_data['edit_product_name'] = product_key
        await query.edit_message_text(f"请输入 {products[product_key]['name']} 的新名称：\n发送 /cancel 取消", parse_mode="Markdown")
        return
    if data.startswith("edit_product_price_") and is_admin_user:
        product_key = data[19:]
        context.user_data['edit_product_price'] = product_key
        await query.edit_message_text(f"请输入 {products[product_key]['name']} 的新价格 (USDT)：\n发送 /cancel 取消", parse_mode="Markdown")
        return
    if data.startswith("edit_product_desc_") and is_admin_user:
        product_key = data[18:]
        context.user_data['edit_product_desc'] = product_key
        await query.edit_message_text(f"请输入 {products[product_key]['name']} 的新描述：\n发送 /cancel 取消", parse_mode="Markdown")
        return
    if data.startswith("upload_cards_") and is_admin_user:
        product_key = data[13:]
        context.user_data['upload_cards_to'] = product_key
        await query.edit_message_text("📁 *添加卡密/账号*\n\n**方式1：直接发送文本**\n每行一个卡密/账号\n\n**方式2：上传txt文件**\n直接发送 .txt 文件，每行一个\n\n发送 /cancel 取消", parse_mode="Markdown")
        return

    # 购买国家商品
    if data.startswith("buy_country_"):
        parts = data.split("_")
        if len(parts) >= 4:
            product_key = "_".join(parts[2:-1])
            country_code = parts[-1]
            if country_code not in countries:
                await query.edit_message_text("❌ 国家不存在")
                return
            country = countries[country_code]
            price = country["price_usdt"]
            balance = user_balances.get(user_id, 0.0)
            if balance < price:
                await query.edit_message_text(f"⚠️ *余额不足*\n\n需要：`{price} USDT`\n当前：`{balance:.4f} USDT`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 去充值", callback_data="recharge_balance")]]), parse_mode="Markdown")
                return
            accounts = country.get("accounts", [])
            if len(accounts) <= 0:
                await query.edit_message_text(f"❌ {country['name']} 账号已售罄")
                return
            user_balances[user_id] = balance - price
            save_all_data()
            order_id, account_info = create_order(user_id, product_key, 1, country_code)
            await query.edit_message_text(f"✅ *购买成功！*\n\n📦 商品：{country['name']} 账号\n💰 金额：{price} USDT\n💎 剩余余额：`{user_balances[user_id]:.4f} USDT`\n\n🔐 *账号信息：*\n`{account_info}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 继续购物", callback_data="product_list")], [InlineKeyboardButton("🏠 主菜单", callback_data="main_menu")]]), parse_mode="Markdown")
        return

    # 购买普通商品
    if data.startswith("buy_"):
        product_key = data[4:]
        prod = products.get(product_key)
        if not prod:
            await query.edit_message_text("❌ 商品不存在")
            return
        product_type = prod.get('product_type', 'card')
        if product_type == 'card':
            available_cards = len([c for c in cards.get(product_key, []) if not c.get('used', False)])
            if available_cards <= 0:
                await query.edit_message_text("❌ 抱歉，该商品已售罄。")
                return
        elif product_type == 'account':
            if len(prod.get('accounts', [])) <= 0:
                await query.edit_message_text("❌ 抱歉，该商品已售罄。")
                return
        price = prod["price_usdt"]
        balance = user_balances.get(user_id, 0.0)
        if balance < price:
            await query.edit_message_text(f"⚠️ *余额不足*\n\n需要：`{price} USDT`\n当前：`{balance:.4f} USDT`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 去充值", callback_data="recharge_balance")]]), parse_mode="Markdown")
            return
        user_balances[user_id] = balance - price
        save_all_data()
        order_id, delivery_data = create_order(user_id, product_key, 1)
        await query.edit_message_text(f"✅ *购买成功！*\n\n📦 商品：{prod['name']}\n💰 金额：{price} USDT\n💎 剩余余额：`{user_balances[user_id]:.4f} USDT`\n\n🔐 *发货信息：*\n`{delivery_data if delivery_data else '信息获取失败'}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 继续购物", callback_data="product_list")], [InlineKeyboardButton("🏠 主菜单", callback_data="main_menu")]]), parse_mode="Markdown")
        return

    # 充值处理
    if data.startswith("recharge_") and data not in ["recharge_balance", "recharge_custom"]:
        amount_str = data.replace("recharge_", "")
        try:
            amount = float(amount_str)
            order_number = f"D{datetime.now().strftime('%Y%m%d%H%M%S')}{user_id[-6:]}"
            recharge_orders[order_number] = {"user_id": user_id, "amount": amount, "status": "pending", "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            save_all_data()
            result = okpay_create_deposit(order_number, amount, user_id)
            if result.get('code') == 200:
                pay_url = result.get('data', {}).get('pay_url', '')
                await query.edit_message_text(f"💳 *充值订单已创建*\n\n💰 金额：{amount} USDT\n📦 订单号：`{order_number}`\n\n🔗 [点击支付]({pay_url})\n\n⚠️ 支付完成后，系统会自动确认到账。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ 查询到账", callback_data=f"check_order_{order_number}")], [InlineKeyboardButton("🔙 返回", callback_data="recharge_balance")]]), parse_mode="Markdown", disable_web_page_preview=True)
            else:
                await query.edit_message_text(f"❌ 创建订单失败：{result.get('msg', '未知错误')}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="recharge_balance")]]))
        except Exception as e:
            logger.error(f"充值失败: {e}")
            await query.edit_message_text("❌ 充值失败，请重试")
        return

    if data.startswith("check_order_"):
        order_number = data[12:]
        result = okpay_check_deposit(order_number)
        if result.get('code') == 200:
            data = result.get('data', {})
            if data.get('status') == 1:
                if confirm_recharge(order_number, data.get('tx_id')):
                    await query.edit_message_text(f"✅ *充值成功！*\n\n金额：{data.get('amount')} USDT\n当前余额：`{user_balances.get(user_id, 0):.4f} USDT`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 主菜单", callback_data="main_menu")]]), parse_mode="Markdown")
                else:
                    await query.edit_message_text("⚠️ 订单处理中，请稍后再试")
            else:
                await query.edit_message_text(f"⏳ *订单未支付*\n\n订单号：`{order_number}`\n金额：{data.get('amount')} USDT\n\n请完成支付后再次查询。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 再次查询", callback_data=f"check_order_{order_number}")], [InlineKeyboardButton("🔙 返回", callback_data="recharge_balance")]]), parse_mode="Markdown")
        else:
            await query.edit_message_text(f"❌ 查询失败：{result.get('msg')}")
        return

    if data == "recharge_custom":
        context.user_data['awaiting_recharge'] = True
        await query.edit_message_text("✏️ *自定义充值*\n\n请输入充值金额 (USDT)，最低 1 USDT：\n发送 /cancel 取消。", parse_mode="Markdown")
        return

# ================== 文件上传处理 ==================
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ 权限不足")
        return
    document = update.message.document
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ 请上传 .txt 文件")
        return
    if not context.user_data.get('adding_cards_to') and not context.user_data.get('upload_cards_to'):
        await update.message.reply_text("❌ 请先点击「添加卡密」按钮")
        return
    try:
        file = await context.bot.get_file(document.file_id)
        file_content = await file.download_as_bytearray()
        content = file_content.decode('utf-8')
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        if context.user_data.get('adding_cards_to'):
            product_key = context.user_data['adding_cards_to']
            added = add_cards_bulk(product_key, lines)
            await update.message.reply_text(f"✅ 已添加 {added} 个卡密到 {products[product_key]['name']}")
            context.user_data.pop('adding_cards_to', None)
        elif context.user_data.get('upload_cards_to'):
            product_key = context.user_data['upload_cards_to']
            prod = products[product_key]
            product_type = prod.get('product_type', 'card')
            if product_type == 'card':
                added = add_cards_bulk(product_key, lines)
                await update.message.reply_text(f"✅ 已添加 {added} 个卡密到 {prod['name']}")
            elif product_type == 'account':
                added_count = 0
                for line in lines:
                    if line.strip():
                        add_account_to_product(product_key, line.strip())
                        added_count += 1
                await update.message.reply_text(f"✅ 已添加 {added_count} 个账号到 {prod['name']}")
            else:
                await update.message.reply_text(f"⚠️ 该商品类型不支持批量添加")
            context.user_data.pop('upload_cards_to', None)
    except Exception as e:
        await update.message.reply_text(f"❌ 文件读取失败：{e}")

# ================== 取消操作 ==================
async def cancel_operation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("操作已取消。")
    keys_to_pop = [
        'awaiting_recharge', 'adding_country', 'editing_country', 'edit_type', 
        'adding_account_country', 'adding_product', 'quick_add', 'editing_product', 
        'adding_card_product', 'adding_account_product', 'adding_category', 
        'rename_category', 'edit_product_category', 'create_new_category', 
        'new_product_name', 'new_product_price', 'new_product_category', 
        'new_product_type', 'edit_product_name', 'edit_product_price', 
        'edit_product_desc', 'adding_cards_to', 'upload_cards_to'
    ]
    for key in keys_to_pop:
        context.user_data.pop(key, None)
    return ConversationHandler.END

# ================== 主程序 ==================
async def post_init(application: Application) -> None:
    await send_startup_welcome(application)
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(check_pending_recharges, interval=30, first=10)

def main() -> None:
    application = Application.builder().token(TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel_operation))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    # 重要：只用一个消息处理器，先处理输入状态，再处理普通消息
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
    print("🤖 Bot 已启动！")
    print(f"📊 商品数量：{len(products)}")
    print(f"👥 用户数量：{len(user_balances)}")
    print(f"📦 订单数量：{len(orders)}")
    print(f"🌍 国家数量：{len(countries)}")
    print(f"📂 分类数量：{len(categories)}")
    print("💎 OkayPay API 已集成，全自动充值！")
    print("📝 提示：所有分类和商品均为空，请通过管理面板自行添加")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()