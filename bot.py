import asyncio
import logging
import os
from datetime import datetime
import aiosqlite
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ==========================================
# ⚙️ CONFIGURATION & SECURITY
# ==========================================
# Load environment variables from .env file
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("⚠️ Error: BOT_TOKEN or ADMIN_ID is missing in the .env file!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==========================================
# 🗄️ DATABASE SETUP
# ==========================================
DB_NAME = "shop.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                photo_id TEXT,
                price REAL,
                description TEXT,
                status TEXT DEFAULT 'Available',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                product_id INTEGER,
                full_name TEXT,
                address TEXT,
                phone TEXT,
                payment_method TEXT,
                payment_details TEXT,
                status TEXT DEFAULT 'Pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.commit()

# ==========================================
# 🚦 FSM STATES
# ==========================================
class AddProduct(StatesGroup):
    photo = State()
    name = State()
    price = State()
    description = State()

class Checkout(StatesGroup):
    product_id = State()
    name = State()
    address = State()
    phone = State()
    payment_method = State()
    trx_id = State()

# ==========================================
# 🛑 CANCEL COMMAND (Global)
# ==========================================
@dp.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return
    await state.clear()
    await message.answer("🚫 <b>প্রক্রিয়াটি বাতিল করা হয়েছে।</b>", parse_mode="HTML", reply_markup=get_main_menu())

# ==========================================
# 🔑 KEYBOARDS
# ==========================================
def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🛍️ Shop Now")]],
        resize_keyboard=True
    )

def get_admin_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Add Product", callback_data="admin_add_product")
    builder.button(text="📦 Manage Products", callback_data="admin_manage")
    builder.button(text="📋 View Orders", callback_data="admin_orders")
    builder.adjust(1)
    return builder.as_markup()

def get_payment_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="💵 Cash on Delivery", callback_data="pay_cod")
    builder.button(text="💳 Online Payment", callback_data="pay_online")
    builder.adjust(1)
    return builder.as_markup()

# ==========================================
# 🛡️ ADMIN HANDLERS
# ==========================================
@dp.message(Command("admin"))
async def admin_dashboard(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("⛔ <b>Unauthorized access.</b>", parse_mode="HTML")
    await message.answer("👑 <b>Admin Dashboard</b>\nSelect an option below:", reply_markup=get_admin_menu(), parse_mode="HTML")

@dp.callback_query(F.data == "admin_add_product")
async def start_add_product(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await state.set_state(AddProduct.photo)
    await call.message.answer("📸 <b>Product Photo:</b> Please send the product image.\n<i>(Send /cancel to abort)</i>", parse_mode="HTML")
    await call.answer()

@dp.message(StateFilter(AddProduct.photo), F.photo)
async def process_product_photo(message: Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await state.set_state(AddProduct.name)
    await message.answer("📝 <b>Product Name:</b> Enter the product name:", parse_mode="HTML")

@dp.message(StateFilter(AddProduct.name))
async def process_product_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AddProduct.price)
    await message.answer("💰 <b>Product Price:</b> Enter price (numbers only):", parse_mode="HTML")

@dp.message(StateFilter(AddProduct.price))
async def process_product_price(message: Message, state: FSMContext):
    try:
        price = float(message.text)
        await state.update_data(price=price)
        await state.set_state(AddProduct.description)
        await message.answer("📄 <b>Product Description:</b> Enter product details:", parse_mode="HTML")
    except ValueError:
        await message.answer("⚠️ Please enter a valid numerical value for the price.")

@dp.message(StateFilter(AddProduct.description))
async def process_product_desc(message: Message, state: FSMContext):
    data = await state.get_data()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO products (name, photo_id, price, description) VALUES (?, ?, ?, ?)",
            (data['name'], data['photo_id'], data['price'], message.text)
        )
        await db.commit()
    await state.clear()
    await message.answer("✅ <b>Product added successfully!</b>", parse_mode="HTML", reply_markup=get_admin_menu())

@dp.callback_query(F.data == "admin_manage")
async def manage_products(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, name, price, status FROM products") as cursor:
            products = await cursor.fetchall()
            
    if not products:
        await call.message.answer("📭 No products found in the database.")
        return await call.answer()

    for p in products:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Toggle Stock", callback_data=f"toggle_{p[0]}")
        builder.button(text="❌ Delete", callback_data=f"delete_{p[0]}")
        builder.adjust(2)
        
        status_emoji = "✅" if p[3] == "Available" else "🔴"
        text = f"📦 <b>ID:</b> {p[0]}\n📌 <b>Name:</b> {p[1]}\n💵 <b>Price:</b> ৳{p[2]}\n📊 <b>Status:</b> {status_emoji} {p[3]}"
        await call.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("toggle_"))
async def toggle_stock(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    p_id = int(call.data.split("_")[1])
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT status FROM products WHERE id = ?", (p_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                new_status = "Out of Stock" if row[0] == "Available" else "Available"
                await db.execute("UPDATE products SET status = ? WHERE id = ?", (new_status, p_id))
                await db.commit()
                await call.message.edit_text(f"{call.message.html_text}\n\n<i>🔄 Updated to: {new_status}</i>", parse_mode="HTML")
    await call.answer("Stock status updated!", show_alert=True)

@dp.callback_query(F.data.startswith("delete_"))
async def delete_product(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    p_id = int(call.data.split("_")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM products WHERE id = ?", (p_id,))
        await db.commit()
    await call.message.delete()
    await call.answer("Product deleted successfully!", show_alert=True)

@dp.callback_query(F.data == "admin_orders")
async def view_orders(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, full_name, phone, payment_method, status, created_at FROM orders ORDER BY id DESC LIMIT 5") as cursor:
            orders = await cursor.fetchall()
            
    if not orders:
        await call.message.answer("📭 No recent orders found.")
        return await call.answer()

    for o in orders:
        text = (f"🛒 <b>Order #{o[0]}</b>\n"
                f"👤 <b>Name:</b> {o[1]}\n"
                f"📱 <b>Phone:</b> {o[2]}\n"
                f"💳 <b>Payment:</b> {o[3]}\n"
                f"📊 <b>Status:</b> {o[4]}\n"
                f"🕒 <b>Time:</b> {o[5]}")
        
        # Action buttons for Admin
        builder = InlineKeyboardBuilder()
        if o[4] == 'Pending':
            builder.button(text="✅ Mark Confirmed", callback_data=f"status_Confirm_{o[0]}")
            builder.button(text="❌ Mark Canceled", callback_data=f"status_Cancel_{o[0]}")
            builder.adjust(2)
        
        await call.message.answer(text, reply_markup=builder.as_markup() if o[4] == 'Pending' else None, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("status_"))
async def update_order_status(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    _, action, order_id = call.data.split("_")
    
    new_status = "Confirmed" if action == "Confirm" else "Canceled"
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, int(order_id)))
        await db.commit()
    
    await call.message.edit_text(f"{call.message.html_text}\n\n<i>✅ Status updated to: {new_status}</i>", parse_mode="HTML")
    await call.answer(f"Order {order_id} marked as {new_status}")

# ==========================================
# 🛍️ USER HANDLERS (Shop & Checkout)
# ==========================================
@dp.message(CommandStart())
async def start_cmd(message: Message):
    welcome_msg = (
        "👋 <b>Welcome to our Premium Store!</b>\n\n"
        "Explore our latest collections. Click the button below to browse the catalog.\n\n"
        "<i>Need help? Just type /cancel to restart any process.</i>"
    )
    await message.answer(welcome_msg, reply_markup=get_main_menu(), parse_mode="HTML")

@dp.message(F.text == "🛍️ Shop Now")
async def show_catalog(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, name, photo_id, price, description FROM products WHERE status = 'Available'") as cursor:
            products = await cursor.fetchall()
            
    if not products:
        return await message.answer("😔 <b>Sorry, there are no products available right now.</b>", parse_mode="HTML")

    for p in products:
        builder = InlineKeyboardBuilder()
        builder.button(text="🛒 Buy Now", callback_data=f"buy_{p[0]}")
        caption = f"💎 <b>{p[1]}</b>\n\n📄 {p[4]}\n\n💰 <b>Price:</b> ৳{p[3]}"
        await message.answer_photo(
            photo=p[2],
            caption=caption,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )

# ==========================================
# 🛒 DYNAMIC CHECKOUT PROCESS
# ==========================================
@dp.callback_query(F.data.startswith("buy_"))
async def start_checkout(call: CallbackQuery, state: FSMContext):
    p_id = int(call.data.split("_")[1])
    await state.update_data(product_id=p_id)
    await state.set_state(Checkout.name)
    await call.message.answer("📝 <b>Checkout Step 1/4:</b>\n\nPlease enter your <b>Full Name</b>:\n<i>(Send /cancel to abort)</i>", parse_mode="HTML")
    await call.answer()

@dp.message(StateFilter(Checkout.name))
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(Checkout.address)
    await message.answer("🏠 <b>Checkout Step 2/4:</b>\n\nPlease enter your <b>Full Shipping Address</b>:", parse_mode="HTML")

@dp.message(StateFilter(Checkout.address))
async def get_address(message: Message, state: FSMContext):
    await state.update_data(address=message.text)
    await state.set_state(Checkout.phone)
    await message.answer("📱 <b>Checkout Step 3/4:</b>\n\nPlease enter your <b>Phone Number</b>:", parse_mode="HTML")

@dp.message(StateFilter(Checkout.phone))
async def get_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await state.set_state(Checkout.payment_method)
    await message.answer("💳 <b>Checkout Step 4/4:</b>\n\nHow would you like to pay?", reply_markup=get_payment_menu(), parse_mode="HTML")

@dp.callback_query(StateFilter(Checkout.payment_method), F.data.in_(["pay_cod", "pay_online"]))
async def process_payment_method(call: CallbackQuery, state: FSMContext):
    if call.data == "pay_cod":
        await state.update_data(payment_method="Cash on Delivery", trx_id="N/A")
        await finalize_order(call.message, state, call.from_user.id)
    else:
        await state.update_data(payment_method="Online Payment")
        await state.set_state(Checkout.trx_id)
        payment_text = (
            "🏦 <b>Online Payment Instructions</b>\n\n"
            "Please send the total amount to any of these numbers:\n"
            "• <b>bKash:</b> <code>01856771266</code>\n"
            "• <b>Nagad:</b> <code>01856771266</code>\n"
            "• <b>Rocket:</b> <code>01856771266</code>\n\n"
            "<i>(Tap the number to copy)</i>\n\n"
            "Once paid, please reply with your <b>Transaction ID</b> or the <b>Last 4 Digits</b> of your sending number."
        )
        await call.message.answer(payment_text, parse_mode="HTML")
    await call.answer()

@dp.message(StateFilter(Checkout.trx_id))
async def process_trx(message: Message, state: FSMContext):
    await state.update_data(trx_id=message.text)
    await finalize_order(message, state, message.from_user.id)

async def finalize_order(message: Message, state: FSMContext, user_id: int):
    data = await state.get_data()
    
    # Save to Database
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "INSERT INTO orders (user_id, product_id, full_name, address, phone, payment_method, payment_details) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, data['product_id'], data['name'], data['address'], data['phone'], data['payment_method'], data['trx_id'])
        )
        order_id = cursor.lastrowid
        await db.commit()

    # Clear state and notify user
    await state.clear()
    success_msg = (
        "🎉 <b>Order Placed Successfully!</b>\n\n"
        f"<b>Order ID:</b> #{order_id}\n"
        "<b>Status:</b> ⏳ Pending Confirmation\n\n"
        "Thank you for shopping with us! We will contact you soon."
    )
    await message.answer(success_msg, parse_mode="HTML", reply_markup=get_main_menu())

    # Formatted Notification for Admin
    admin_notification = (
        "🚨 <b>NEW ORDER ALERT!</b> 🚨\n\n"
        f"🔖 <b>Order ID:</b> #{order_id}\n"
        f"📦 <b>Product ID:</b> {data['product_id']}\n"
        f"👤 <b>Customer:</b> {data['name']}\n"
        f"📞 <b>Phone:</b> {data['phone']}\n"
        f"🏠 <b>Address:</b> {data['address']}\n"
        f"💳 <b>Payment:</b> {data['payment_method']}\n"
        f"🧾 <b>Trx Info:</b> {data['trx_id']}"
    )
    
    # Send Notification to Admin with action buttons
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Confirm", callback_data=f"status_Confirm_{order_id}")
    builder.button(text="❌ Cancel", callback_data=f"status_Cancel_{order_id}")
    builder.adjust(2)
    
    try:
        await bot.send_message(ADMIN_ID, admin_notification, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception as e:
        logging.error(f"Failed to send admin notification: {e}")

# ==========================================
# 🚀 MAIN POLLING
# ==========================================
async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    print("🚀 Secure Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
