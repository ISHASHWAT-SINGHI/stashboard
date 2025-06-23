import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3
from datetime import datetime
import os
import sys
import logging
from functools import wraps

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='stock_management.log'
)
logger = logging.getLogger(__name__)

def to_sentence_case(text):
    """Convert text to sentence case (first letter capitalized, rest lowercase)"""
    if not text:
        return text
    return text[0].upper() + text[1:].lower()

def format_name(name):
    """Format names in sentence case, handling multiple words"""
    if not name:
        return name
    return ' '.join(to_sentence_case(word) for word in name.split())

# Database Handler Class
class DatabaseHandler:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.connection = sqlite3.connect(get_db_path())
            cls._instance.connection.execute("PRAGMA foreign_keys = ON")
            cls._instance.connection.row_factory = sqlite3.Row
        return cls._instance
    
    def get_cursor(self):
        return self.connection.cursor()
    
    def commit(self):
        self.connection.commit()
    
    def close(self):
        if self.connection:
            self.connection.close()
            DatabaseHandler._instance = None

    # Company operations
    def get_companies(self):
        cursor = self.get_cursor()
        cursor.execute("SELECT id, name FROM companies")
        return {name: id for id, name in cursor.fetchall()}
    
    def add_company(self, name, gst_number, contact):
        cursor = self.get_cursor()
        cursor.execute(
            "INSERT INTO companies (name, gst_number, contact) VALUES (?, ?, ?)",
            (format_name(name), gst_number, contact)
        )
        self.commit()

    def get_purchase_history(self, product_name=None):
        """Get complete purchase history with original and remaining quantities"""
        cursor = self.get_cursor()
        query = '''
            SELECT 
                p.id,
                c.name as company_name,
                p.brand,
                p.product_name,
                p.original_quantity,
                p.quantity as remaining_quantity,
                p.unit_price,
                p.cgst,
                p.sgst,
                p.cess,
                p.purchase_date,
                p.company_invoice,
                (p.original_quantity - p.quantity) as sold_quantity
            FROM products p
            LEFT JOIN companies c ON p.company_id = c.id
        '''
        params = []
        
        if product_name:
            query += " WHERE p.product_name = ?"
            params.append(product_name)
        
        query += " ORDER BY p.purchase_date DESC"
        cursor.execute(query, params)
        return cursor.fetchall()
    
    # Product operations
    def get_products(self):
        cursor = self.get_cursor()
        cursor.execute('''
            SELECT 
                COALESCE(c.name, 'No Company'), 
                p.brand, 
                p.product_name, 
                SUM(p.quantity) as total_quantity,
                p.unit_price, 
                p.cgst, 
                p.sgst, 
                p.cess, 
                MAX(COALESCE(p.purchase_date, '')) as last_purchase_date
            FROM products p
            LEFT JOIN companies c ON p.company_id = c.id
            GROUP BY c.name, p.brand, p.product_name, p.unit_price, p.cgst, p.sgst, p.cess
            ORDER BY p.product_name
        ''')
        return [tuple(row) for row in cursor.fetchall()]
    
    def get_product_history(self, product_name):
        cursor = self.get_cursor()
        cursor.execute('''
            SELECT 
                p.brand, 
                p.product_name, 
                p.quantity, 
                p.unit_price, 
                p.purchase_date,
                p.company_invoice,
                c.name as company_name
            FROM products p
            LEFT JOIN companies c ON p.company_id = c.id
            WHERE LOWER(p.product_name) = LOWER(?)
            ORDER BY p.purchase_date DESC
        ''', (product_name,))
        return cursor.fetchall()
    
    def add_product(self, company_id, brand, product_name, quantity, unit_price, cgst, sgst, cess, purchase_date, company_invoice=None):
        cursor = self.get_cursor()
        brand = format_name(brand)
        product_name = format_name(product_name)

        cursor.execute('''
            INSERT INTO products 
            (company_id, brand, product_name, original_quantity, quantity, unit_price, cgst, sgst, cess, purchase_date, company_invoice, is_current)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ''', (company_id, brand, product_name, quantity, quantity, unit_price, cgst, sgst, cess, purchase_date, company_invoice))
        self.commit()

        def update_product_quantity(self, product_id, new_quantity, purchase_date):
            cursor = self.get_cursor()
            cursor.execute('''
                UPDATE products 
                SET quantity = ?, purchase_date = ?
                WHERE id = ?
            ''', (new_quantity, purchase_date, product_id))
            self.commit()

    # Customer operations
    def get_customers(self):
        cursor = self.get_cursor()
        cursor.execute("SELECT name FROM customers ORDER BY name")
        return [row[0] for row in cursor.fetchall()]
    
    def add_customer(self, name, address, gst_number, contact):
        cursor = self.get_cursor()
        cursor.execute('''
            INSERT INTO customers (name, address, gst_number, contact)
            VALUES (?, ?, ?, ?)
        ''', (format_name(name), address, gst_number, contact))
        self.commit()
    
    def get_customer_address(self, name):
        cursor = self.get_cursor()
        cursor.execute("SELECT address FROM customers WHERE name=?", (name,))
        result = cursor.fetchone()
        return result[0] if result else ""

    # Billing operations
    def create_bill(self, bill_number, customer_name, total_amount, bill_date):
        cursor = self.get_cursor()
        cursor.execute('''
            INSERT INTO billing (bill_number, customer_name, total_amount, bill_date)
            VALUES (?, ?, ?, ?)
        ''', (bill_number, customer_name, total_amount, bill_date))
        self.commit()
    
    def add_bill_item(self, bill_number, product_name, quantity, unit_price):
        cursor = self.get_cursor()
        cursor.execute('''
            INSERT INTO bill_items (bill_number, product_name, quantity, unit_price)
            VALUES (?, ?, ?, ?)
        ''', (bill_number, product_name, quantity, unit_price))
        self.commit()
    
    def update_stock(self, product_name, quantity):
        try:
            cursor = self.get_cursor()
            cursor.execute("BEGIN IMMEDIATE TRANSACTION")

            # Get available stock (only check quantity, not original_quantity)
            cursor.execute('''
                SELECT id, quantity 
                FROM products 
                WHERE product_name = ? AND quantity > 0
                ORDER BY purchase_date ASC
            ''', (product_name,))
            batches = cursor.fetchall()

            total_available = sum(batch['quantity'] for batch in batches)
            if total_available < quantity:
                self.connection.rollback()
                raise ValueError(f"Insufficient stock. Available: {total_available}, Requested: {quantity}")

            # Deduct from oldest batches first
            remaining = quantity
            for batch in batches:
                if remaining <= 0:
                    break

                deduct = min(remaining, batch['quantity'])
                cursor.execute('''
                    UPDATE products 
                    SET quantity = quantity - ? 
                    WHERE id = ?
                ''', (deduct, batch['id']))
                remaining -= deduct

            self.connection.commit()

        except Exception as e:
            self.connection.rollback()
            raise

    # GST operations
    def get_gst_slabs(self):
        cursor = self.get_cursor()
        cursor.execute("SELECT gst_rate FROM gst_slabs")
        return [gst[0] for gst in cursor.fetchall()]
    
    def add_gst_slab(self, rate):
        cursor = self.get_cursor()
        cursor.execute("INSERT INTO gst_slabs (gst_rate) VALUES (?)", (rate,))
        self.commit()

    # Invoice number operations
    def get_invoice_number(self):
        current_year = datetime.now().year
        cursor = self.get_cursor()
        cursor.execute("SELECT last_invoice_number FROM settings WHERE year=?", (current_year,))
        result = cursor.fetchone()

        if result is None:
            cursor.execute("INSERT INTO settings (year, last_invoice_number) VALUES (?, ?)", (current_year, 0))
            self.commit()
            last_invoice_number = 0
        else:
            last_invoice_number = result[0]

        new_invoice_number = last_invoice_number + 1

        # Reset on April 1st
        if datetime.now().month == 4 and datetime.now().day == 1:
            new_invoice_number = 1

        cursor.execute("UPDATE settings SET last_invoice_number=? WHERE year=?", (new_invoice_number, current_year))
        self.commit()
        return new_invoice_number
    
    def check_current_stock(self, product_name):
        """Debugging method to check current stock levels"""
        cursor = self.get_cursor()
        cursor.execute('''
            SELECT id, quantity, purchase_date 
            FROM products 
            WHERE product_name = ? 
            ORDER BY purchase_date ASC
        ''', (product_name,))
        records = cursor.fetchall()

        logger.info(f"Current stock status for {product_name}:")
        total = 0
        for record in records:
            logger.info(f"  ID: {record['id']}, Qty: {record['quantity']}, Date: {record['purchase_date']}")
            total += record['quantity']
        logger.info(f"Total available: {total}")
        return total
    
# Utility functions
def get_app_path():
    """Get the application directory path"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def get_db_path():
    """Get the consistent database path"""
    app_dir = get_app_path()
    return os.path.join(app_dir, 'stock_management.db')

def setup_database():
    """Initialize the database with required tables"""
    db_path = get_db_path()
    logger.info(f"Initializing database at: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create tables if they don't exist
    tables = {
        'companies': '''
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY,
                name TEXT,
                gst_number TEXT,
                contact TEXT
            )
        ''',
        'customers': '''
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY,
                name TEXT,
                address TEXT,
                gst_number TEXT,
                contact TEXT
            )
        ''',
        'products': '''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            company_id INTEGER,
            brand TEXT COLLATE NOCASE,
            product_name TEXT COLLATE NOCASE,
            original_quantity INTEGER,  
            quantity INTEGER,           
            unit_price REAL,
            cgst REAL,
            sgst REAL,
            cess REAL,
            purchase_date TEXT,
            company_invoice TEXT,
            is_current INTEGER DEFAULT 1,
            FOREIGN KEY (company_id) REFERENCES companies (id)
        )
        ''',
        'gst_slabs': '''
            CREATE TABLE IF NOT EXISTS gst_slabs (
                id INTEGER PRIMARY KEY,
                gst_rate REAL
            )
        ''',
        'settings': '''
            CREATE TABLE IF NOT EXISTS settings (
                year INTEGER PRIMARY KEY,
                last_invoice_number INTEGER
                low_stock_threshold INTEGER DEFAULT 5
            )
        ''',
        'purchases': '''
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT,
                product_name TEXT,
                quantity INTEGER,
                unit_price REAL,
                total_price REAL,
                purchase_date DATETIME
            )
        ''',
        'bill_items': '''
            CREATE TABLE IF NOT EXISTS bill_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_number INTEGER,
                product_name TEXT,
                quantity INTEGER,
                unit_price REAL,
                FOREIGN KEY (bill_number) REFERENCES billing(bill_number)
            )
        ''',
        'billing': '''
            CREATE TABLE IF NOT EXISTS billing (
                bill_number INTEGER PRIMARY KEY,
                customer_name TEXT,
                total_amount REAL,
                bill_date TEXT
            )
        ''',
        'users': '''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE,
                password TEXT,
                role TEXT
            )
        '''
    }
    
    for table_name, table_sql in tables.items():
        cursor.execute(table_sql)
        logger.info(f"Created table {table_name} or it already exists.")

    # Check and add low_stock_threshold column if it doesn't exist
    cursor.execute("PRAGMA table_info(settings)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'low_stock_threshold' not in columns:
        cursor.execute("ALTER TABLE settings ADD COLUMN low_stock_threshold INTEGER DEFAULT 5")
        logger.info("Added low_stock_threshold column to settings table")
    
    conn.commit()
    
    # Initialize settings for current year
    current_year = datetime.now().year
    cursor.execute("INSERT OR IGNORE INTO settings (year, last_invoice_number) VALUES (?, ?)", (current_year, 0))
    
    # Create default admin user if not exists
    cursor.execute("SELECT COUNT(*) FROM users WHERE username='admin'")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            ('admin', 'admin123', 'admin')  # In production, use hashed passwords!
        )
        logger.info("Created default admin user")
    
    conn.commit()
    conn.close()

# Decorators for authentication and authorization
def login_required(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if not hasattr(self, 'current_user') or not self.current_user:
            messagebox.showerror("Authentication Required", "Please login to access this feature")
            return
        return func(self, *args, **kwargs)
    return wrapper

def admin_required(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if not hasattr(self, 'current_user') or not self.current_user:
            messagebox.showerror("Authentication Required", "Please login to access this feature")
            return
        if self.current_user.get('role') != 'admin':
            messagebox.showerror("Permission Denied", "Admin privileges required")
            return
        return func(self, *args, **kwargs)
    return wrapper

# Main Application Class
class StockManagementApp:
    def __init__(self, root):
        setup_database()
        self.db = DatabaseHandler()
        self.root = root
        self.root.title("Stock Management System")
        self.current_user = None
        
        # Configure window size and styles
        self.root.geometry("1200x800")
        self.configure_styles()
        
        # Setup authentication UI first
        self.setup_auth_ui()
        
        # Initialize other UI components after successful login
        self.initialize_ui_components()

    def select_product_from_stock_view(self, event):
        """Auto-fill product details when clicking in stock view"""
        selected = self.stock_tree.selection()
        if selected:
            product = self.stock_tree.item(selected[0], 'values')
            self.billing_product_combobox.set(product[0])  # Set product name
            self.billing_price_entry.delete(0, tk.END)
            self.billing_price_entry.insert(0, product[2].replace("₹", ""))  # Price
            self.filter_mini_stock_view()   # Show current stock
    
    def configure_styles(self):
        """Configure application-wide styles"""
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Base styles
        self.style.configure('.', font=('Segoe UI', 10), background='#f0f0f0')
        self.style.configure('TFrame', background='#f0f0f0')
        self.style.configure('TLabel', background='#f0f0f0', font=('Segoe UI', 10))
        self.style.configure('TButton', font=('Segoe UI', 10), padding=6, relief=tk.RAISED)
        
        # Accent button style
        self.style.configure('Accent.TButton',
                           foreground='white',
                           background='#0078d7',
                           font=('Segoe UI', 10, 'bold'))
        self.style.map('Accent.TButton',
                     foreground=[('pressed', 'white'), ('active', 'white')],
                     background=[('pressed', '#0052cc'), ('active', '#0066ff')])
        
        # Treeview styles
        self.style.configure('Treeview',
                           rowheight=25,
                           fieldbackground='white',
                           background='white')
        self.style.configure('Treeview.Heading',
                           font=('Segoe UI', 10, 'bold'),
                           background='#e6e6e6',
                           relief=tk.RAISED)
        self.style.map('Treeview.Heading',
                     background=[('active', '#d9d9d9')])
        
        # Notebook style
        self.style.configure('TNotebook', background='#f0f0f0')
        self.style.configure('TNotebook.Tab', padding=[10, 5], font=('Segoe UI', 9))
    
    def setup_auth_ui(self):
        """Setup authentication UI (login screen)"""
        self.auth_frame = ttk.Frame(self.root)
        self.auth_frame.pack(fill=tk.BOTH, expand=True, padx=200, pady=100)
        
        # Login form
        ttk.Label(self.auth_frame, text="Username:", font=('Segoe UI', 12)).pack(pady=5)
        self.username_entry = ttk.Entry(self.auth_frame, font=('Segoe UI', 12))
        self.username_entry.pack(pady=5, fill=tk.X)
        
        ttk.Label(self.auth_frame, text="Password:", font=('Segoe UI', 12)).pack(pady=5)
        self.password_entry = ttk.Entry(self.auth_frame, show="*", font=('Segoe UI', 12))
        self.password_entry.pack(pady=5, fill=tk.X)
        
        ttk.Button(self.auth_frame, text="Login", command=self.login, style='Accent.TButton').pack(pady=20)
    
    def login(self):
        """Handle user login"""
        username = self.username_entry.get()
        password = self.password_entry.get()
        
        if not username or not password:
            messagebox.showerror("Error", "Please enter both username and password")
            return
        
        cursor = self.db.get_cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()
        
        if user and user['password'] == password:  # In production, use proper password hashing!
            self.current_user = dict(user)
            self.auth_frame.destroy()
            self.setup_main_ui()
            logger.info(f"User {username} logged in successfully")
        else:
            messagebox.showerror("Login Failed", "Invalid username or password")
            logger.warning(f"Failed login attempt for username: {username}")
    
    def initialize_ui_components(self):
        """Initialize UI components that will be shown after login"""
        self.added_items = []
        self.temp_products = []
        self.total_cgst = 0.0
        self.total_sgst = 0.0
        
        # Windows references
        self.company_window = None
        self.product_window = None
        self.customer_window = None
        self.report_window = None
    
    def setup_main_ui(self):
        """Setup the main application UI after successful login"""
        # Menu bar
        self.setup_menu()
        
        # Main Frame with Notebook (Tabbed Interface)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create tabs
        self.inventory_tab = ttk.Frame(self.notebook)
        self.billing_tab = ttk.Frame(self.notebook)
        self.reports_tab = ttk.Frame(self.notebook)
        
        self.notebook.add(self.inventory_tab, text="Inventory")
        self.notebook.add(self.billing_tab, text="Billing")
        self.notebook.add(self.reports_tab, text="Reports")
        
        # Status Bar
        self.status_bar = ttk.Label(self.root, text=f"Logged in as: {self.current_user['username']}", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Setup individual tabs
        self.setup_inventory_tab()
        self.setup_billing_tab()
        self.setup_reports_tab()
        
        # Load initial data
        self.load_products()
        self.update_status("Application started")
    
    def setup_menu(self):
        """Setup the application menu bar"""
        menubar = tk.Menu(self.root)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Add GST Slab", command=self.add_gst_slab)
        file_menu.add_command(label="View Purchases", command=self.open_purchases_window)
        file_menu.add_command(label="View Bills", command=self.open_bills_window)
        file_menu.add_command(label="Reset Cache", command=self.reset_application_state)
        file_menu.add_command(label="Set Low Stock Threshold", command=self.set_low_stock_threshold)
        file_menu.add_separator()

        if self.current_user.get('role') == 'admin':
            file_menu.add_command(label="User Management", command=self.manage_users)

        file_menu.add_separator()
        file_menu.add_command(label="Logout", command=self.logout)
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="☰", menu=file_menu)

        # Billing menu (new)
        billing_menu = tk.Menu(menubar, tearoff=0)
        billing_menu.add_command(label="Add Customer", command=self.add_customer)
        # menubar.add_cascade(label="Billing", menu=billing_menu)

        # Configure the menu
        self.root.config(menu=menubar)
    
    def logout(self):
        """Handle user logout"""
        # Clean up all windows
        for attr in ['company_window', 'product_window', 'customer_window', 'report_window', 
                    'purchases_window', 'bills_window']:
            if hasattr(self, attr) and getattr(self, attr) is not None:
                try:
                    getattr(self, attr).destroy()
                except:
                    pass
                setattr(self, attr, None)

        self.current_user = None
        for widget in self.root.winfo_children():
            widget.destroy()
        self.setup_auth_ui()
        logger.info("User logged out")

    @admin_required
    def manage_users(self):
        """Admin user management interface"""
        user_window = tk.Toplevel(self.root)
        user_window.title("User Management")
        user_window.geometry("600x400")
        
        # Treeview for users
        tree_frame = ttk.Frame(user_window)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        yscroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.users_tree = ttk.Treeview(
            tree_frame,
            columns=("ID", "Username", "Role"),
            show='headings',
            yscrollcommand=yscroll.set
        )
        yscroll.config(command=self.users_tree.yview)
        self.users_tree.pack(fill=tk.BOTH, expand=True)
        
        # Configure columns
        self.users_tree.heading("ID", text="ID")
        self.users_tree.heading("Username", text="Username")
        self.users_tree.heading("Role", text="Role")
        
        # Load users
        self.load_users()
        
        # Add/Edit/Delete buttons
        button_frame = ttk.Frame(user_window)
        button_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(button_frame, text="Add User", command=self.add_user_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Edit User", command=self.edit_user_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Delete User", command=self.delete_user).pack(side=tk.LEFT, padx=5)
    
    def load_users(self):
        """Load users into the treeview"""
        for item in self.users_tree.get_children():
            self.users_tree.delete(item)
        
        cursor = self.db.get_cursor()
        cursor.execute("SELECT id, username, role FROM users")
        for user in cursor.fetchall():
            self.users_tree.insert("", "end", values=(user['id'], user['username'], user['role']))
    
    def add_user_dialog(self):
        """Dialog for adding a new user"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Add New User")
        
        ttk.Label(dialog, text="Username:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        username_entry = ttk.Entry(dialog)
        username_entry.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(dialog, text="Password:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        password_entry = ttk.Entry(dialog, show="*")
        password_entry.grid(row=1, column=1, padx=5, pady=5)
        
        ttk.Label(dialog, text="Role:").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        role_combobox = ttk.Combobox(dialog, values=["admin", "user"])
        role_combobox.grid(row=2, column=1, padx=5, pady=5)
        role_combobox.current(1)  # Default to 'user'
        
        def save_user():
            username = username_entry.get()
            password = password_entry.get()
            role = role_combobox.get()
            
            if not username or not password:
                messagebox.showerror("Error", "Username and password are required")
                return
            
            try:
                cursor = self.db.get_cursor()
                cursor.execute(
                    "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                    (username, password, role)  # In production, hash the password!
                )
                self.db.commit()
                self.load_users()
                dialog.destroy()
                messagebox.showinfo("Success", "User added successfully")
            except sqlite3.IntegrityError:
                messagebox.showerror("Error", "Username already exists")
        
        ttk.Button(dialog, text="Save", command=save_user).grid(row=3, column=1, padx=5, pady=10, sticky="e")
    
    def edit_user_dialog(self):
        """Dialog for editing an existing user"""
        selected = self.users_tree.selection()
        if not selected:
            messagebox.showerror("Error", "Please select a user to edit")
            return
        
        user_id = self.users_tree.item(selected[0], "values")[0]
        
        cursor = self.db.get_cursor()
        cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
        user = cursor.fetchone()
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit User")
        
        ttk.Label(dialog, text="Username:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        username_entry = ttk.Entry(dialog)
        username_entry.insert(0, user['username'])
        username_entry.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(dialog, text="New Password:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        password_entry = ttk.Entry(dialog, show="*")
        password_entry.grid(row=1, column=1, padx=5, pady=5)
        
        ttk.Label(dialog, text="Role:").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        role_combobox = ttk.Combobox(dialog, values=["admin", "user"])
        role_combobox.set(user['role'])
        role_combobox.grid(row=2, column=1, padx=5, pady=5)
        
        def update_user():
            username = username_entry.get()
            password = password_entry.get()
            role = role_combobox.get()
            
            if not username:
                messagebox.showerror("Error", "Username is required")
                return
            
            try:
                cursor = self.db.get_cursor()
                if password:  # Only update password if provided
                    cursor.execute(
                        "UPDATE users SET username=?, password=?, role=? WHERE id=?",
                        (username, password, role, user_id)  # In production, hash the password!
                    )
                else:
                    cursor.execute(
                        "UPDATE users SET username=?, role=? WHERE id=?",
                        (username, role, user_id)
                    )
                self.db.commit()
                self.load_users()
                dialog.destroy()
                messagebox.showinfo("Success", "User updated successfully")
            except sqlite3.IntegrityError:
                messagebox.showerror("Error", "Username already exists")
        
        ttk.Button(dialog, text="Update", command=update_user).grid(row=3, column=1, padx=5, pady=10, sticky="e")
    
    def delete_user(self):
        """Delete selected user"""
        selected = self.users_tree.selection()
        if not selected:
            messagebox.showerror("Error", "Please select a user to delete")
            return
        
        user_id = self.users_tree.item(selected[0], "values")[0]
        username = self.users_tree.item(selected[0], "values")[1]
        
        if username == self.current_user['username']:
            messagebox.showerror("Error", "You cannot delete your own account while logged in")
            return
        
        if messagebox.askyesno("Confirm", f"Are you sure you want to delete user {username}?"):
            cursor = self.db.get_cursor()
            cursor.execute("DELETE FROM users WHERE id=?", (user_id,))
            self.db.commit()
            self.load_users()
            messagebox.showinfo("Success", "User deleted successfully")
    
    def setup_inventory_tab(self):
        """Setup the inventory management tab"""
        # Top frame for buttons
        button_frame = ttk.Frame(self.inventory_tab)
        button_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Action buttons
        ttk.Button(button_frame, text="Add Company", command=self.add_company, 
                  style='Accent.TButton').pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Add Stock", command=self.add_product,
                  style='Accent.TButton').pack(side=tk.LEFT, padx=5)
        
        # Search frame
        search_frame = ttk.Frame(self.inventory_tab)
        search_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT, padx=5)
        self.search_entry = ttk.Entry(search_frame)
        self.search_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        # self.search_entry.bind("<KeyRelease>", self.schedule_inventory_search)
        self.search_entry.bind("<KeyRelease>", self.real_time_inventory_search)
        
        # Product List with scrollbars
        container = ttk.Frame(self.inventory_tab)
        container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Scrollbars
        yscroll = ttk.Scrollbar(container, orient=tk.VERTICAL)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        xscroll = ttk.Scrollbar(container, orient=tk.HORIZONTAL)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Treeview
        self.product_list = ttk.Treeview(
        container, 
        columns=("Company", "Brand", "Product Name", "Quantity", "Unit Price", "CGST", "SGST", "CESS", "Purchase Date"), 
        show='headings',
        yscrollcommand=yscroll.set,
        xscrollcommand=xscroll.set
        )
        
        # Configure scrollbars
        yscroll.config(command=self.product_list.yview)
        xscroll.config(command=self.product_list.xview)
        
        # Pack treeview
        self.product_list.pack(fill=tk.BOTH, expand=True)
        
        # Configure columns
        columns = ["Company", "Brand", "Product Name", "Quantity", "Unit Price", "CGST", "SGST", "CESS", "Purchase Date"]
        for col in columns:
            self.product_list.heading(col, text=col)
            self.product_list.column(col, width=100, anchor=tk.CENTER)
        
        # Double click event
        self.product_list.bind("<Double-1>", self.on_product_double_click)

        footer_frame = ttk.Frame(self.inventory_tab)
        footer_frame.pack(fill=tk.X, pady=5, padx=10)

        ttk.Label(footer_frame, text="Total Stock Value:", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)
        self.total_stock_value_label = ttk.Label(footer_frame, text="₹0.00", font=('Segoe UI', 10, 'bold'))
        self.total_stock_value_label.pack(side=tk.LEFT, padx=5)

        # Load products and calculate total value
        self.load_products()

    def schedule_inventory_search(self, event):
        """Schedule search with small delay to avoid excessive queries"""
        if hasattr(self, '_search_after_id'):
            self.root.after_cancel(self._search_after_id)

        # Schedule search after 300ms of inactivity
        self._search_after_id = self.root.after(300, self.search_products)
    
    def search_products(self):
        """Search products based on search term"""
        search_term = self.search_entry.get().strip().lower()
        
        if not search_term:
            self.load_products()
            return
        
        cursor = self.db.get_cursor()
        cursor.execute('''
            SELECT 
                COALESCE(c.name, 'No Company'), 
                p.brand, 
                p.product_name, 
                p.quantity, 
                p.unit_price, 
                p.cgst, 
                p.sgst, 
                p.cess, 
                COALESCE(p.purchase_date, '')
            FROM products p
            LEFT JOIN companies c ON p.company_id = c.id
            WHERE p.product_name LIKE ? OR p.brand LIKE ? OR c.name LIKE ?
        ''', (f'%{search_term}%', f'%{search_term}%', f'%{search_term}%'))
        
        products = [tuple(row) for row in cursor.fetchall()]
        
        # Clear current items
        for item in self.product_list.get_children():
            self.product_list.delete(item)
        
        # Add matching products
        for product in products:
            self.product_list.insert("", "end", values=product)
    
    def load_products(self):
        """Load all products into the inventory list with low-stock highlighting"""
        try:
            # Clear current items
            for item in self.product_list.get_children():
                self.product_list.delete(item)

            # Get threshold from settings
            cursor = self.db.get_cursor()
            cursor.execute("SELECT low_stock_threshold FROM settings WHERE year=?", (datetime.now().year,))
            result = cursor.fetchone()
            threshold = result['low_stock_threshold'] if result and 'low_stock_threshold' in result.keys() else 5

            # Get products from database
            products = self.db.get_products()

            total_value = 0.0  # Initialize total stock value

            # Add to treeview with color coding
            for product in products:
                quantity = product[3]  # Assuming quantity is the 4th column
                price = product[4]    # Assuming price is the 5th column
                total_value += quantity * price  # Update total stock value

                if quantity <= threshold:
                    self.product_list.insert("", "end", values=product, tags=('low_stock',))
                else:
                    self.product_list.insert("", "end", values=product)

            # Update the total stock value label
            self.total_stock_value_label.config(text=f"₹{total_value:,.2f}")

            # Configure tag for low stock items (red background)
            self.product_list.tag_configure('low_stock', background='#ffdddd', foreground='black')

        except Exception as e:
            logger.error(f"Error loading products: {e}")
            messagebox.showerror("Error", f"Failed to load products: {str(e)}")

    def set_low_stock_threshold(self):
        """Allow admin to change the low-stock alert threshold"""
        threshold = simpledialog.askinteger(
            "Low Stock Threshold",
            "Enter minimum stock quantity to trigger alerts:",
            parent=self.root,
            minvalue=1,
            initialvalue=5
        )
        if threshold:
            cursor = self.db.get_cursor()
            cursor.execute("UPDATE settings SET low_stock_threshold=? WHERE year=?", (threshold, datetime.now().year))
            self.db.commit()
            self.load_products()  # Refresh to apply new threshold
    
    def on_product_double_click(self, event):
        """Handle double click on product in inventory list"""
        selected_items = self.product_list.selection()
        if not selected_items:  # No item selected
            return

        try:
            item = selected_items[0]
            product_data = self.product_list.item(item, 'values')

            details = (
                f"Company: {product_data[0]}\n"
                f"Brand: {product_data[1]}\n"
                f"Product: {product_data[2]}\n"
                f"Quantity: {product_data[3]}\n"
                f"Price: {product_data[4]}\n"
                f"CGST: {product_data[5]}%\n"
                f"SGST: {product_data[6]}%\n"
                f"CESS: {product_data[7]}%\n"
                f"Purchase Date: {product_data[8]}"
            )

            messagebox.showinfo("Product Details", details)
        except Exception as e:
            logger.error(f"Error showing product details: {e}")
            messagebox.showerror("Error", "Failed to show product details")

    def update_product_suggestions(self, event):
        """Update product suggestions based on typed text"""
        typed = self.billing_product_combobox.get()
        if not typed:
            self.load_billing_products()
            return

        cursor = self.db.get_cursor()
        cursor.execute("""
            SELECT DISTINCT product_name FROM products 
            WHERE product_name LIKE ? 
            ORDER BY product_name
        """, (f'%{typed}%',))

        products = [row[0] for row in cursor.fetchall()]
        self.billing_product_combobox['values'] = products

    def update_combobox_values(self):
        """Update combobox values from database"""
        cursor = self.db.get_cursor()
        cursor.execute("SELECT DISTINCT product_name FROM products ORDER BY product_name")
        self.all_products = [row[0] for row in cursor.fetchall()]
        self.billing_product_combobox['values'] = self.all_products

    def real_time_product_filter(self, event):
        """Filter products in real-time as user types"""
        # Only process alphanumeric keys and backspace
        if event.keysym in ('Escape', 'Return', 'Tab', 'Up', 'Down', 'Left', 'Right'):
            return

        typed = self.billing_product_combobox.get().lower()

        # Filter products based on typed text
        if typed:
            filtered = [p for p in self.all_products if typed in p.lower()]
        else:
            filtered = self.all_products

        # Update combobox values
        self.billing_product_combobox['values'] = filtered

        # Also filter the mini stock view
        self.filter_mini_stock_view(event)

    def show_dropdown_options(self, event=None):
        """Show dropdown options when down arrow is pressed"""
        if not self.billing_product_combobox['values']:
            self.update_combobox_values()

        self.billing_product_combobox.event_generate('<Button-1>')
        self.billing_product_combobox.focus_set()

    def setup_billing_tab(self):
        """Setup the billing tab with enhanced UI"""
        # Main frame
        main_frame = ttk.Frame(self.billing_tab)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Top button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=5)

        # Add Customer button
        ttk.Button(button_frame, text="Add Customer", command=self.add_customer,
                  style='Accent.TButton').pack(side=tk.LEFT, padx=5)

        # COMBINED CUSTOMER AND ADDRESS ROW
        customer_frame = ttk.Frame(main_frame)
        customer_frame.pack(fill=tk.X, pady=5)

        ttk.Label(customer_frame, text="Customer:").pack(side=tk.LEFT, padx=5)
        self.billing_customer_combobox = ttk.Combobox(customer_frame, width=20)
        self.billing_customer_combobox.pack(side=tk.LEFT, padx=5)
        self.load_billing_customers()

        ttk.Label(customer_frame, text="Address:").pack(side=tk.LEFT, padx=5)
        self.customer_address_label = ttk.Label(customer_frame, text="", 
                                              relief=tk.SUNKEN, wraplength=400)
        self.customer_address_label.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # COMBINED PRODUCT, QTY, PRICE AND ADD BUTTON ROW
        product_frame = ttk.Frame(main_frame)
        product_frame.pack(fill=tk.X, pady=5)

        ttk.Label(product_frame, text="Product:").pack(side=tk.LEFT, padx=5)
        self.billing_product_combobox = ttk.Combobox(product_frame)
        self.billing_product_combobox.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.update_combobox_values()
        self.billing_product_combobox.bind('<KeyRelease>', self.real_time_product_filter)

        # Load initial values
        self.update_combobox_values()

        ttk.Label(product_frame, text="Qty:").pack(side=tk.LEFT, padx=5)
        self.billing_qty_entry = ttk.Entry(product_frame, width=6)
        self.billing_qty_entry.pack(side=tk.LEFT, padx=5)

        ttk.Label(product_frame, text="Price:").pack(side=tk.LEFT, padx=5)
        self.billing_price_entry = ttk.Entry(product_frame, width=8)
        self.billing_price_entry.pack(side=tk.LEFT, padx=5)
        # UPDATE BUTTON
        ttk.Button(product_frame, text="Update", command=self.update_billing_item, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Button(product_frame, text="Add Item", command=self.add_billing_item, width=10).pack(side=tk.LEFT, padx=5)

        # Setup autocomplete
        self.billing_product_combobox.bind('<KeyRelease>', lambda e: self.update_product_suggestions(e))
        self.billing_product_combobox.bind("<KeyRelease>", self.filter_mini_stock_view)

        # Items table with scrollbars
        tree_frame = ttk.Frame(main_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        yscroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        xscroll = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)

        self.billing_items_tree = ttk.Treeview(
            tree_frame,
            columns=("Product", "Qty", "Price", "CGST", "SGST", "Total"),
            show='headings',
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set
        )

        # Configure scrollbars
        yscroll.config(command=self.billing_items_tree.yview)
        xscroll.config(command=self.billing_items_tree.xview)

        # Configure columns
        self.billing_items_tree.heading("Product", text="Product")
        self.billing_items_tree.heading("Qty", text="Qty")
        self.billing_items_tree.heading("Price", text="Price")
        self.billing_items_tree.heading("CGST", text="CGST")
        self.billing_items_tree.heading("SGST", text="SGST")
        self.billing_items_tree.heading("Total", text="Total")

        self.billing_items_tree.column("Product", width=200)
        self.billing_items_tree.column("Qty", width=50, anchor=tk.CENTER)
        self.billing_items_tree.column("Price", width=80, anchor=tk.E)
        self.billing_items_tree.column("CGST", width=60, anchor=tk.E)
        self.billing_items_tree.column("SGST", width=60, anchor=tk.E)
        self.billing_items_tree.column("Total", width=80, anchor=tk.E)

        self.billing_items_tree.pack(fill=tk.BOTH, expand=True)

        # Total frame
        total_frame = ttk.Frame(main_frame)
        total_frame.pack(fill=tk.X, pady=5)

        ttk.Label(total_frame, text="Subtotal:").pack(side=tk.LEFT, padx=5)
        self.subtotal_label = ttk.Label(total_frame, text="0.00", font=('Segoe UI', 10, 'bold'))
        self.subtotal_label.pack(side=tk.LEFT, padx=5)

        ttk.Label(total_frame, text="CGST:").pack(side=tk.LEFT, padx=5)
        self.cgst_label = ttk.Label(total_frame, text="0.00", font=('Segoe UI', 10, 'bold'))
        self.cgst_label.pack(side=tk.LEFT, padx=5)

        ttk.Label(total_frame, text="SGST:").pack(side=tk.LEFT, padx=5)
        self.sgst_label = ttk.Label(total_frame, text="0.00", font=('Segoe UI', 10, 'bold'))
        self.sgst_label.pack(side=tk.LEFT, padx=5)

        ttk.Label(total_frame, text="Total:").pack(side=tk.LEFT, padx=5)
        self.total_label = ttk.Label(total_frame, text="0.00", font=('Segoe UI', 12, 'bold'))
        self.total_label.pack(side=tk.LEFT, padx=5)

        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)

        ttk.Button(button_frame, text="Remove", command=self.remove_billing_items).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Generate Bill", command=self.generate_bill, 
              style='Accent.TButton').pack(side=tk.RIGHT, padx=5)
        # Bind double-click for editing
        self.billing_items_tree.bind("<Double-1>", self.on_billing_item_double_click)

        # Bind customer selection change
        self.billing_customer_combobox.bind("<<ComboboxSelected>>", self.on_customer_selected)

        # Initialize temp products list
        self.temp_products = []

        # Mini stock view with increased height
        stock_frame = ttk.Frame(self.billing_tab)
        stock_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.stock_tree = ttk.Treeview(
            stock_frame,
            columns=("Product", "Stock", "Price"),
            show='headings',
            height=8,  # Increased height for more items
            selectmode='browse'
        )

        # Configure columns
        self.stock_tree.heading("Product", text="Product")
        self.stock_tree.heading("Stock", text="Available")
        self.stock_tree.heading("Price", text="Unit Price")

        self.stock_tree.column("Product", width=150)
        self.stock_tree.column("Stock", width=80, anchor=tk.CENTER)
        self.stock_tree.column("Price", width=100, anchor=tk.E)

        # Add scrollbar
        scrollbar = ttk.Scrollbar(stock_frame, orient=tk.VERTICAL, command=self.stock_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.stock_tree.configure(yscrollcommand=scrollbar.set)
        self.stock_tree.pack(fill=tk.BOTH, expand=True)

        # Now bind the events after the treeview is created
        self.stock_tree.bind("<ButtonRelease-1>", self.select_product_from_stock_view)

        # Load initial data
        self.load_mini_stock_view()

    def _setup_mini_stock_view(self):
        """Initialize the mini stock treeview"""
        stock_frame = ttk.Frame(self.billing_tab)
        stock_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.stock_tree = ttk.Treeview(
            stock_frame,
            columns=("Product", "Stock", "Price"),
            show='headings',
            height=5,
            selectmode='browse'
        )

        # Configure columns
        self.stock_tree.heading("Product", text="Product")
        self.stock_tree.heading("Stock", text="Available")
        self.stock_tree.heading("Price", text="Unit Price")

        self.stock_tree.column("Product", width=150)
        self.stock_tree.column("Stock", width=80, anchor=tk.CENTER)
        self.stock_tree.column("Price", width=100, anchor=tk.E)

        # Add scrollbar
        scrollbar = ttk.Scrollbar(stock_frame, orient=tk.VERTICAL, command=self.stock_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.stock_tree.configure(yscrollcommand=scrollbar.set)
        self.stock_tree.pack(fill=tk.BOTH, expand=True)

        # Load initial data
        self.load_mini_stock_view()
    
    def load_mini_stock_view(self, filter_text=""):
        """Load/refresh the mini stock view with optional filter"""
        self.stock_tree.delete(*self.stock_tree.get_children())

        cursor = self.db.get_cursor()
        query = '''
            SELECT 
                product_name,
                SUM(quantity) as total_stock,
                unit_price
            FROM products
            WHERE product_name LIKE ?
            GROUP BY product_name, unit_price
            ORDER BY product_name
        '''
        cursor.execute(query, (f"%{filter_text}%",))

        for product in cursor.fetchall():
            self.stock_tree.insert("", "end", values=(
                product['product_name'],
                product['total_stock'],
                f"₹{product['unit_price']:.2f}"
            ))

    def filter_mini_stock_view(self, event):
        """Filter stock view as user types"""
        search_term = self.billing_product_combobox.get()
        self.load_mini_stock_view(search_term)
    
    def on_billing_item_double_click(self, event):
        """Handle double-click on billing item for editing"""
        selected = self.billing_items_tree.selection()
        if not selected:
            return

        # Get selected item values
        item = selected[0]
        values = self.billing_items_tree.item(item, 'values')

        # Pre-fill the input fields
        self.billing_product_combobox.set(values[0])
        self.billing_qty_entry.delete(0, tk.END)
        self.billing_qty_entry.insert(0, values[1])
        self.billing_price_entry.delete(0, tk.END)
        self.billing_price_entry.insert(0, values[2].replace("₹", ""))

        # Store reference to item being edited
        self.editing_item = item
    
    def load_billing_customers(self):
        """Load customers into billing combobox"""
        customers = self.db.get_customers()
        self.billing_customer_combobox['values'] = customers
    
    def load_billing_products(self):
        """Load products into billing combobox"""
        cursor = self.db.get_cursor()
        cursor.execute("SELECT DISTINCT product_name FROM products ORDER BY product_name")
        products = [row[0] for row in cursor.fetchall()]
        self.billing_product_combobox['values'] = products
    
    def on_customer_selected(self, event):
        """Update customer address when customer is selected"""
        customer_name = self.billing_customer_combobox.get()
        address = self.db.get_customer_address(customer_name)
        self.customer_address_label.config(text=address)
    
    def add_billing_item(self):
        """Add item to billing list with proper variable scoping"""
        product_name = self.billing_product_combobox.get()
        quantity = self.billing_qty_entry.get()
        price = self.billing_price_entry.get()

        if not product_name or not quantity or not price:
            messagebox.showerror("Error", "Please fill all fields")
            return

        try:
            quantity = int(quantity)
            price = float(price)
        except ValueError:
            messagebox.showerror("Error", "Quantity must be integer and price must be numeric")
            return

        # Get product details from database with distinct variable name
        cursor = self.db.get_cursor()
        cursor.execute('''
            SELECT p.product_name, p.cgst, p.sgst, SUM(p.quantity) as total_quantity 
            FROM products p 
            WHERE p.product_name = ?
            GROUP BY p.product_name, p.cgst, p.sgst
        ''', (product_name,))
        product_data = cursor.fetchone()

        if not product_data:
            messagebox.showerror("Error", "Product not found in database")
            return

        if quantity > product_data['total_quantity']:
            messagebox.showerror("Error", 
                f"Not enough stock. Only {product_data['total_quantity']} available (total across all batches)")
            return

        # Calculate taxes and total
        cgst_amount = (price * quantity) * (product_data['cgst'] / 100)
        sgst_amount = (price * quantity) * (product_data['sgst'] / 100)
        item_total = (price * quantity) + cgst_amount + sgst_amount

        # Add to treeview
        self.billing_items_tree.insert("", "end", values=(
            product_name,
            quantity,
            f"{price:.2f}",
            f"{cgst_amount:.2f}",
            f"{sgst_amount:.2f}",
            f"{item_total:.2f}"
        ))

        # Add to temporary list for later processing
        self.temp_products.append({
            'product_name': product_name,
            'quantity': quantity,
            'unit_price': price,
            'cgst': product_data['cgst'],
            'sgst': product_data['sgst']
        })

        # Update totals
        self.update_billing_totals()

        # Clear fields
        self.billing_qty_entry.delete(0, tk.END)
        self.billing_price_entry.delete(0, tk.END)

    def update_billing_totals(self):
        """Update billing totals with widget existence checks"""
        if not hasattr(self, 'subtotal_label') or not self.subtotal_label.winfo_exists():
            return  # Exit if widgets don't exist

        subtotal = 0.0
        total_cgst = 0.0
        total_sgst = 0.0

        for item in self.temp_products:
            item_value = item['quantity'] * item['unit_price']
            subtotal += item_value
            total_cgst += item_value * (item['cgst'] / 100)
            total_sgst += item_value * (item['sgst'] / 100)

        total = subtotal + total_cgst + total_sgst

        try:
            self.subtotal_label.config(text=f"{subtotal:.2f}")
            self.cgst_label.config(text=f"{total_cgst:.2f}")
            self.sgst_label.config(text=f"{total_sgst:.2f}")
            self.total_label.config(text=f"{total:.2f}")
        except tk.TclError as e:
            logger.warning(f"UI elements not available: {str(e)}")
    
    def remove_billing_items(self):
        """Remove selected items or all items if none selected"""
        selected = self.billing_items_tree.selection()

        if selected:
            # Remove selected items
            for item in selected:
                # Find index in temp_products
                values = self.billing_items_tree.item(item, 'values')
                product_name = values[0]

                # Remove from temp_products
                self.temp_products = [p for p in self.temp_products if p['product_name'] != product_name]

                # Remove from tree
                self.billing_items_tree.delete(item)
        else:
            # Clear all items if nothing selected
            self.billing_items_tree.delete(*self.billing_items_tree.get_children())
            self.temp_products.clear()

        self.update_billing_totals()

    def update_billing_item(self):
        """Update selected billing item with new values"""
        if not hasattr(self, 'editing_item') or not self.editing_item:
            messagebox.showinfo("Edit Item", "Please select an item to edit (double-click)")
            return

        product_name = self.billing_product_combobox.get()
        quantity = self.billing_qty_entry.get()
        price = self.billing_price_entry.get()

        if not product_name or not quantity or not price:
            messagebox.showerror("Error", "Please fill all fields")
            return

        try:
            quantity = int(quantity)
            price = float(price)
        except ValueError:
            messagebox.showerror("Error", "Quantity must be integer and price must be numeric")
            return

        # Get product details from database
        cursor = self.db.get_cursor()
        cursor.execute('''
            SELECT p.product_name, p.cgst, p.sgst, SUM(p.quantity) as total_quantity 
            FROM products p 
            WHERE p.product_name = ?
            GROUP BY p.product_name, p.cgst, p.sgst
        ''', (product_name,))
        product_data = cursor.fetchone()

        if not product_data:
            messagebox.showerror("Error", "Product not found in database")
            return

        if quantity > product_data['total_quantity']:
            messagebox.showerror("Error", 
                f"Not enough stock. Only {product_data['total_quantity']} available")
            return

        # Calculate taxes and total
        cgst_amount = (price * quantity) * (product_data['cgst'] / 100)
        sgst_amount = (price * quantity) * (product_data['sgst'] / 100)
        item_total = (price * quantity) + cgst_amount + sgst_amount

        # Update treeview
        self.billing_items_tree.item(self.editing_item, values=(
            product_name,
            quantity,
            f"{price:.2f}",
            f"{cgst_amount:.2f}",
            f"{sgst_amount:.2f}",
            f"{item_total:.2f}"
        ))

        # Update temporary products list
        for product in self.temp_products:
            if product['product_name'] == product_name:
                product['quantity'] = quantity
                product['unit_price'] = price
                break

        # Update totals
        self.update_billing_totals()

        # Clear editing state
        self.editing_item = None

        # Clear fields
        self.billing_qty_entry.delete(0, tk.END)
        self.billing_price_entry.delete(0, tk.END)
    
    def generate_bill(self):
        """Generate bill and save to database with detailed logging"""
        try:
            # DEBUG: Check stock before processing
            for item in self.temp_products:
                self.db.check_current_stock(item['product_name'])
            
            logger.info("=== Starting bill generation process ===")

            if not self.temp_products:
                logger.error("No items to bill - temp_products is empty")
                messagebox.showerror("Error", "No items to bill")
                return

            customer_name = self.billing_customer_combobox.get()
            if not customer_name:
                logger.error("No customer selected")
                messagebox.showerror("Error", "Please select a customer")
                return

            logger.info(f"Generating bill for customer: {customer_name}")
            logger.info("Items in bill:")
            for idx, item in enumerate(self.temp_products, 1):
                logger.info(f"  {idx}. {item['product_name']} - Qty: {item['quantity']}, Price: {item['unit_price']}")

            # Get invoice number
            invoice_number = self.db.get_invoice_number()
            logger.info(f"Generated invoice number: {invoice_number}")

            # Calculate total from items
            total_amount = 0.0
            for item in self.temp_products:
                item_value = item['quantity'] * item['unit_price']
                item_total = item_value * (1 + (item['cgst'] + item['sgst']) / 100)
                total_amount += item_total
                logger.info(f"Calculated item total for {item['product_name']}: {item_total:.2f}")

            logger.info(f"Total bill amount: {total_amount:.2f}")

            # Get current date
            bill_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"Bill date: {bill_date}")

            try:
                # Save bill to database
                logger.info("Creating bill record in database...")
                self.db.create_bill(invoice_number, customer_name, total_amount, bill_date)
                logger.info("Bill record created successfully")

                # Save bill items and update stock
                for item in self.temp_products:
                    product_name = item['product_name']
                    quantity = item['quantity']

                    logger.info(f"Processing item: {product_name} (Qty: {quantity})")

                    # First check current stock
                    cursor = self.db.get_cursor()
                    cursor.execute('''
                        SELECT id, quantity, purchase_date 
                        FROM products 
                        WHERE product_name = ? AND quantity > 0
                        ORDER BY purchase_date ASC
                    ''', (product_name,))
                    stock_records = cursor.fetchall()
                    total_stock = sum(record['quantity'] for record in stock_records)

                    logger.info(f"Current stock records for {product_name}:")
                    for record in stock_records:
                        logger.info(f"  ID: {record['id']}, Qty: {record['quantity']}, Date: {record['purchase_date']}")
                    logger.info(f"Total available stock for {product_name}: {total_stock}")

                    if total_stock < quantity:
                        logger.error(f"Insufficient stock for {product_name}. Available: {total_stock}, Needed: {quantity}")
                        raise ValueError(f"Insufficient stock for {product_name}")

                    # Add bill item
                    logger.info(f"Adding bill item for {product_name}...")
                    self.db.add_bill_item(invoice_number, product_name, quantity, item['unit_price'])
                    logger.info("Bill item added successfully")

                    # Update stock
                    logger.info(f"Updating stock for {product_name}...")
                    self.db.update_stock(product_name, quantity)
                    logger.info("Stock updated successfully")

                # Show success message
                message = f"Bill generated successfully!\nInvoice Number: {invoice_number}"
                logger.info(message)
                messagebox.showinfo("Success", message)

                try:
                    self.remove_billing_items()
                    self.load_products()
                except tk.TclError as e:
                    logger.warning(f"UI cleanup skipped: {str(e)}")

            except Exception as e:
                logger.error(f"Error during bill processing: {str(e)}", exc_info=True)
                messagebox.showerror("Error", f"Failed to generate bill: {str(e)}")
                raise

        except Exception as e:
            logger.error(f"Error in bill generation process: {str(e)}", exc_info=True)
            messagebox.showerror("Error", f"An unexpected error occurred: {str(e)}")

    def real_time_inventory_search(self, event):
        """Real-time inventory search with simple filtering"""
        # Skip non-text keys
        if event.keysym in ('Escape', 'Return', 'Tab', 'Up', 'Down', 'Left', 'Right'):
            return

        search_term = self.search_entry.get().strip().lower()

        # Clear current items
        for item in self.product_list.get_children():
            self.product_list.delete(item)

        # Filter products using the existing get_products method
        all_products = self.db.get_products()

        if search_term:
            products = [p for p in all_products if any(
                search_term in str(field).lower() for field in p
            )]
        else:
            products = all_products

        # Add matching products
        for product in products:
            self.product_list.insert("", "end", values=product)

    def setup_reports_tab(self):
        """Setup the reports tab with proper column formatting"""
        # Main frame
        main_frame = ttk.Frame(self.reports_tab)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Report type selection
        report_frame = ttk.Frame(main_frame)
        report_frame.pack(fill=tk.X, pady=5)

        ttk.Label(report_frame, text="Report Type:").pack(side=tk.LEFT, padx=5)
        self.report_type = ttk.Combobox(report_frame, values=[
            "Stock Report", 
            "Sales Report", 
            "Customer Report",
            "Product Sales Report"
        ], state="readonly")
        self.report_type.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.report_type.current(0)

        # Date range frame (optional)
        date_frame = ttk.Frame(main_frame)
        date_frame.pack(fill=tk.X, pady=5)

        ttk.Label(date_frame, text="From:").pack(side=tk.LEFT, padx=5)
        self.from_date_entry = ttk.Entry(date_frame, width=12)
        self.from_date_entry.pack(side=tk.LEFT, padx=5)

        ttk.Label(date_frame, text="To:").pack(side=tk.LEFT, padx=5)
        self.to_date_entry = ttk.Entry(date_frame, width=12)
        self.to_date_entry.pack(side=tk.LEFT, padx=5)

        # Generate button
        ttk.Button(main_frame, text="Generate Report", command=self.generate_report,
                  style='Accent.TButton').pack(pady=10)

        # Report display area
        report_display_frame = ttk.Frame(main_frame)
        report_display_frame.pack(fill=tk.BOTH, expand=True)

        # Scrollbars
        yscroll = ttk.Scrollbar(report_display_frame, orient=tk.VERTICAL)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        xscroll = ttk.Scrollbar(report_display_frame, orient=tk.HORIZONTAL)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)

        # Treeview with proper headings
        self.report_tree = ttk.Treeview(
            report_display_frame,
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set,
            selectmode='browse'
        )

        # Configure scrollbars
        yscroll.config(command=self.report_tree.yview)
        xscroll.config(command=self.report_tree.xview)

        # Style configuration
        self.style.configure("Treeview.Heading", font=('Segoe UI', 10, 'bold'))
        self.report_tree.pack(fill=tk.BOTH, expand=True)
    
    def generate_report(self):
        """Generate the selected report with proper formatting"""
        report_type = self.report_type.get()
        from_date = self.from_date_entry.get()
        to_date = self.to_date_entry.get()

        # Clear previous report
        self.report_tree.delete(*self.report_tree.get_children())
        self.report_tree["columns"] = []

        try:
            cursor = self.db.get_cursor()

            if report_type == "Stock Report":
                # Configure columns
                columns = [
                    ("Company", 150),
                    ("Brand", 120), 
                    ("Product", 200),
                    ("Quantity", 80),
                    ("Unit Price", 100),
                    ("CGST%", 80),
                    ("SGST%", 80),
                    ("Last Purchase", 120)
                ]
                self._setup_report_columns(columns)

                # Fetch and display data
                products = self.db.get_products()
                for product in products:
                    self.report_tree.insert("", "end", values=(
                        product[0],  # Company
                        product[1],  # Brand
                        product[2],  # Product
                        product[3],  # Quantity
                        f"₹{product[4]:.2f}",  # Price
                        f"{product[5]}%",  # CGST
                        f"{product[6]}%",  # SGST
                        self._format_date(product[8])  # Purchase Date
                    ))

            elif report_type == "Sales Report":
                columns = [
                    ("Invoice No", 100),
                    ("Customer", 150),
                    ("Date", 120),
                    ("Amount", 100)
                ]
                self._setup_report_columns(columns)

                query = "SELECT bill_number, customer_name, bill_date, total_amount FROM billing"
                params = []

                if from_date and to_date:
                    query += " WHERE bill_date BETWEEN ? AND ?"
                    params.extend([from_date, to_date])

                cursor.execute(query, params)
                for sale in cursor.fetchall():
                    self.report_tree.insert("", "end", values=(
                        sale['bill_number'],
                        sale['customer_name'],
                        self._format_date(sale['bill_date']),
                        f"₹{sale['total_amount']:.2f}"
                    ))

            elif report_type == "Customer Report":
                columns = [
                    ("Name", 150),
                    ("Address", 200),
                    ("GST No", 120),
                    ("Contact", 120)
                ]
                self._setup_report_columns(columns)

                cursor.execute("SELECT name, address, gst_number, contact FROM customers")
                for customer in cursor.fetchall():
                    self.report_tree.insert("", "end", values=(
                        customer['name'],
                        customer['address'],
                        customer['gst_number'],
                        customer['contact']
                    ))

            elif report_type == "Product Sales Report":
                columns = [
                    ("Product", 200),
                    ("Qty Sold", 100),
                    ("Revenue", 120)
                ]
                self._setup_report_columns(columns)

                cursor.execute('''
                    SELECT product_name, SUM(quantity) as qty, 
                           SUM(quantity*unit_price) as revenue
                    FROM bill_items 
                    GROUP BY product_name
                    ORDER BY qty DESC
                ''')
                for item in cursor.fetchall():
                    self.report_tree.insert("", "end", values=(
                        item['product_name'],
                        item['qty'],
                        f"₹{item['revenue']:.2f}"
                    ))

        except Exception as e:
            logger.error(f"Report error: {str(e)}", exc_info=True)
            messagebox.showerror("Error", f"Failed to generate report:\n{str(e)}")

    def _setup_report_columns(self, columns):
        """Configure treeview columns consistently"""
        self.report_tree["columns"] = [col[0] for col in columns]

        # Configure main columns
        for col_name, width in columns:
            self.report_tree.heading(col_name, text=col_name, anchor=tk.CENTER)
            self.report_tree.column(col_name, width=width, anchor=tk.CENTER, stretch=False)

        # Configure invisible first column
        self.report_tree.heading("#0", text="", anchor=tk.CENTER)
        self.report_tree.column("#0", width=0, stretch=False)

    def _format_date(self, date_str):
        """Format database date for display"""
        try:
            return datetime.strptime(date_str[:10], "%Y-%m-%d").strftime("%d-%b-%Y")
        except:
            return date_str or "N/A"
    
    def add_company(self):
        """Open dialog to add a new company"""
        if self.company_window is not None and self.company_window.winfo_exists():
            self.company_window.lift()
            return
        
        self.company_window = tk.Toplevel(self.root)
        self.company_window.title("Add Company")
        self.company_window.geometry("400x300")
        
        ttk.Label(self.company_window, text="Company Name:").pack(pady=5)
        name_entry = ttk.Entry(self.company_window)
        name_entry.pack(pady=5, fill=tk.X, padx=10)
        
        ttk.Label(self.company_window, text="GST Number:").pack(pady=5)
        gst_entry = ttk.Entry(self.company_window)
        gst_entry.pack(pady=5, fill=tk.X, padx=10)
        
        ttk.Label(self.company_window, text="Contact:").pack(pady=5)
        contact_entry = ttk.Entry(self.company_window)
        contact_entry.pack(pady=5, fill=tk.X, padx=10)
        
        def save_company():
            name = name_entry.get()
            gst = gst_entry.get()
            contact = contact_entry.get()
            
            if not name:
                messagebox.showerror("Error", "Company name is required")
                return
            
            try:
                self.db.add_company(name, gst, contact)
                messagebox.showinfo("Success", "Company added successfully")
                self.company_window.destroy()
                self.company_window = None
            except Exception as e:
                logger.error(f"Error adding company: {e}")
                messagebox.showerror("Error", f"Failed to add company: {str(e)}")
        
        ttk.Button(self.company_window, text="Save", command=save_company,
                  style='Accent.TButton').pack(pady=10)
        
        self.company_window.protocol("WM_DELETE_WINDOW", lambda: setattr(self, 'company_window', None))
    
    def add_customer(self):
        """Open dialog to add a new customer"""
        if self.customer_window is not None and self.customer_window.winfo_exists():
            self.customer_window.lift()
            return
        
        self.customer_window = tk.Toplevel(self.root)
        self.customer_window.title("Add Customer")
        self.customer_window.geometry("400x300")
        
        ttk.Label(self.customer_window, text="Customer Name:").pack(pady=5)
        name_entry = ttk.Entry(self.customer_window)
        name_entry.pack(pady=5, fill=tk.X, padx=10)
        
        ttk.Label(self.customer_window, text="Address:").pack(pady=5)
        address_entry = ttk.Entry(self.customer_window)
        address_entry.pack(pady=5, fill=tk.X, padx=10)
        
        ttk.Label(self.customer_window, text="GST Number:").pack(pady=5)
        gst_entry = ttk.Entry(self.customer_window)
        gst_entry.pack(pady=5, fill=tk.X, padx=10)
        
        ttk.Label(self.customer_window, text="Contact:").pack(pady=5)
        contact_entry = ttk.Entry(self.customer_window)
        contact_entry.pack(pady=5, fill=tk.X, padx=10)
        
        def save_customer():
            name = name_entry.get()
            address = address_entry.get()
            gst = gst_entry.get()
            contact = contact_entry.get()
            
            if not name:
                messagebox.showerror("Error", "Customer name is required")
                return
            
            try:
                self.db.add_customer(name, address, gst, contact)
                messagebox.showinfo("Success", "Customer added successfully")
                self.load_billing_customers()  # Refresh billing customer list
                self.customer_window.destroy()
                self.customer_window = None
            except Exception as e:
                logger.error(f"Error adding customer: {e}")
                messagebox.showerror("Error", f"Failed to add customer: {str(e)}")
        
        ttk.Button(self.customer_window, text="Save", command=save_customer,
                  style='Accent.TButton').pack(pady=10)
        
        self.customer_window.protocol("WM_DELETE_WINDOW", lambda: setattr(self, 'customer_window', None))
    
    def add_product(self):
        """Open dialog to add new products (multiple at once) with interface similar to billing"""
        if self.product_window is not None and self.product_window.winfo_exists():
            self.product_window.lift()
            return

        self.product_window = tk.Toplevel(self.root)
        self.product_window.title("Add Products")
        self.product_window.geometry("1000x700")

        # Main frame
        main_frame = ttk.Frame(self.product_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Company selection
        company_frame = ttk.Frame(main_frame)
        company_frame.pack(fill=tk.X, pady=5)

        ttk.Label(company_frame, text="Company:").pack(side=tk.LEFT, padx=5)
        self.product_company_combobox = ttk.Combobox(company_frame)
        self.product_company_combobox.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Load companies
        companies = self.db.get_companies()
        self.product_company_combobox['values'] = list(companies.keys())

        # Company invoice number
        invoice_frame = ttk.Frame(main_frame)
        invoice_frame.pack(fill=tk.X, pady=5)

        ttk.Label(invoice_frame, text="Company Invoice No:").pack(side=tk.LEFT, padx=5)
        self.company_invoice_entry = ttk.Entry(invoice_frame)
        self.company_invoice_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Product selection frame
        product_frame = ttk.Frame(main_frame)
        product_frame.pack(fill=tk.X, pady=5)

        ttk.Label(product_frame, text="Brand:").pack(side=tk.LEFT, padx=5)
        self.product_brand_entry = ttk.Entry(product_frame)
        self.product_brand_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        ttk.Label(product_frame, text="Product Name:").pack(side=tk.LEFT, padx=5)
        self.product_name_entry = ttk.Entry(product_frame)
        self.product_name_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Quantity and price frame
        qty_price_frame = ttk.Frame(main_frame)
        qty_price_frame.pack(fill=tk.X, pady=5)

        ttk.Label(qty_price_frame, text="Qty:").pack(side=tk.LEFT, padx=5)
        self.product_qty_entry = ttk.Entry(qty_price_frame, width=10)
        self.product_qty_entry.pack(side=tk.LEFT, padx=5)

        ttk.Label(qty_price_frame, text="Price:").pack(side=tk.LEFT, padx=5)
        self.product_price_entry = ttk.Entry(qty_price_frame, width=10)
        self.product_price_entry.pack(side=tk.LEFT, padx=5)

        # GST frame
        gst_frame = ttk.Frame(main_frame)
        gst_frame.pack(fill=tk.X, pady=5)

        ttk.Label(gst_frame, text="GST Slab (%):").pack(side=tk.LEFT, padx=5)
        self.gst_slab_combobox = ttk.Combobox(gst_frame, values=self.db.get_gst_slabs())
        self.gst_slab_combobox.pack(side=tk.LEFT, padx=5)
        if self.db.get_gst_slabs():
            self.gst_slab_combobox.current(0)

        ttk.Label(gst_frame, text="CGST %:").pack(side=tk.LEFT, padx=5)
        self.cgst_label = ttk.Label(gst_frame, text="0.0", relief=tk.SUNKEN, width=8)
        self.cgst_label.pack(side=tk.LEFT, padx=5)

        ttk.Label(gst_frame, text="SGST %:").pack(side=tk.LEFT, padx=5)
        self.sgst_label = ttk.Label(gst_frame, text="0.0", relief=tk.SUNKEN, width=8)
        self.sgst_label.pack(side=tk.LEFT, padx=5)

        ttk.Label(gst_frame, text="CESS %:").pack(side=tk.LEFT, padx=5)
        self.cess_entry = ttk.Entry(gst_frame, width=8)
        self.cess_entry.insert(0, "0.0")
        self.cess_entry.pack(side=tk.LEFT, padx=5)

        # Button to add product to list
        ttk.Button(main_frame, text="Add Product", command=self.add_product_to_list,
                  style='Accent.TButton').pack(pady=5)

        # Items table with scrollbars
        tree_frame = ttk.Frame(main_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        yscroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        xscroll = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)

        self.product_items_tree = ttk.Treeview(
            tree_frame,
            columns=("Company", "Brand", "Product", "Qty", "Price", "CGST", "SGST", "CESS", "Total"),
            show='headings',
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set
        )

        # Configure scrollbars
        yscroll.config(command=self.product_items_tree.yview)
        xscroll.config(command=self.product_items_tree.xview)

        # Configure columns
        self.product_items_tree.heading("Company", text="Company")
        self.product_items_tree.heading("Brand", text="Brand")
        self.product_items_tree.heading("Product", text="Product")
        self.product_items_tree.heading("Qty", text="Qty")
        self.product_items_tree.heading("Price", text="Price")
        self.product_items_tree.heading("CGST", text="CGST %")
        self.product_items_tree.heading("SGST", text="SGST %")
        self.product_items_tree.heading("CESS", text="CESS %")
        self.product_items_tree.heading("Total", text="Total")

        self.product_items_tree.column("Company", width=120, anchor=tk.W)
        self.product_items_tree.column("Brand", width=100, anchor=tk.W)
        self.product_items_tree.column("Product", width=150, anchor=tk.W)
        self.product_items_tree.column("Qty", width=50, anchor=tk.CENTER)
        self.product_items_tree.column("Price", width=80, anchor=tk.E)
        self.product_items_tree.column("CGST", width=60, anchor=tk.E)
        self.product_items_tree.column("SGST", width=60, anchor=tk.E)
        self.product_items_tree.column("CESS", width=60, anchor=tk.E)
        self.product_items_tree.column("Total", width=80, anchor=tk.E)

        self.product_items_tree.pack(fill=tk.BOTH, expand=True)

        # Totals frame (similar to billing)
        total_frame = ttk.Frame(main_frame)
        total_frame.pack(fill=tk.X, pady=5)

        ttk.Label(total_frame, text="Subtotal:").pack(side=tk.LEFT, padx=5)
        self.product_subtotal_label = ttk.Label(total_frame, text="0.00", font=('Segoe UI', 10, 'bold'))
        self.product_subtotal_label.pack(side=tk.LEFT, padx=5)

        ttk.Label(total_frame, text="CGST:").pack(side=tk.LEFT, padx=5)
        self.product_cgst_label = ttk.Label(total_frame, text="0.00", font=('Segoe UI', 10, 'bold'))
        self.product_cgst_label.pack(side=tk.LEFT, padx=5)

        ttk.Label(total_frame, text="SGST:").pack(side=tk.LEFT, padx=5)
        self.product_sgst_label = ttk.Label(total_frame, text="0.00", font=('Segoe UI', 10, 'bold'))
        self.product_sgst_label.pack(side=tk.LEFT, padx=5)

        ttk.Label(total_frame, text="CESS:").pack(side=tk.LEFT, padx=5)
        self.product_cess_label = ttk.Label(total_frame, text="0.00", font=('Segoe UI', 10, 'bold'))
        self.product_cess_label.pack(side=tk.LEFT, padx=5)

        ttk.Label(total_frame, text="Total:").pack(side=tk.LEFT, padx=5)
        self.product_total_label = ttk.Label(total_frame, text="0.00", font=('Segoe UI', 12, 'bold'))
        self.product_total_label.pack(side=tk.LEFT, padx=5)

        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)

        ttk.Button(button_frame, text="Clear", command=self.clear_product_items).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Save All Products", command=self.save_all_products,
                  style='Accent.TButton').pack(side=tk.RIGHT, padx=5)

        # Bind GST slab change
        self.gst_slab_combobox.bind("<<ComboboxSelected>>", self.update_product_gst_rates)
        self.gst_slab_combobox.bind("<KeyRelease>", self.update_product_gst_rates)

        # Initialize GST rates
        self.update_product_gst_rates()

        # List to store products before saving
        self.product_items = []
    
    def update_product_totals(self):
        """Update product totals based on items in the list"""
        subtotal = 0.0
        total_cgst = 0.0
        total_sgst = 0.0
        total_cess = 0.0

        for item in self.product_items:
            item_value = item['quantity'] * item['unit_price']
            subtotal += item_value
            total_cgst += item_value * (item['cgst'] / 100)
            total_sgst += item_value * (item['sgst'] / 100)
            total_cess += item_value * (item['cess'] / 100)

        total = subtotal + total_cgst + total_sgst + total_cess

        # Update labels
        self.product_subtotal_label.config(text=f"{subtotal:.2f}")
        self.product_cgst_label.config(text=f"{total_cgst:.2f}")
        self.product_sgst_label.config(text=f"{total_sgst:.2f}")
        self.product_cess_label.config(text=f"{total_cess:.2f}")
        self.product_total_label.config(text=f"{total:.2f}")

    def update_product_gst_rates(self, event=None):
        """Update CGST and SGST labels when GST slab changes"""
        try:
            gst_slab = float(self.gst_slab_combobox.get())
            cgst = gst_slab / 2
            sgst = gst_slab / 2
            self.cgst_label.config(text=f"{cgst:.2f}")
            self.sgst_label.config(text=f"{sgst:.2f}")
        except ValueError:
            pass

    def add_product_to_list(self):
        """Add product to the items list"""
        company = self.product_company_combobox.get()
        brand = self.product_brand_entry.get()
        product_name = self.product_name_entry.get()
        quantity = self.product_qty_entry.get()
        price = self.product_price_entry.get()
        cess = self.cess_entry.get()
        company_invoice = self.company_invoice_entry.get()

        if not company or not product_name or not quantity or not price:
            messagebox.showerror("Error", "Company, Product Name, Quantity and Price are required")
            return

        try:
            quantity = int(quantity)
            price = float(price)
            cess = float(cess) if cess else 0.0

            # Get GST rates
            gst_slab = float(self.gst_slab_combobox.get())
            cgst = gst_slab / 2
            sgst = gst_slab / 2

            # Calculate item total
            item_total = (price * quantity) * (1 + (cgst + sgst + cess) / 100)

            # Add to treeview
            self.product_items_tree.insert("", "end", values=(
                company,
                brand,
                product_name,
                quantity,
                f"{price:.2f}",
                f"{cgst:.2f}",
                f"{sgst:.2f}",
                f"{cess:.2f}",
                f"{item_total:.2f}"
            ))

            # Add to temporary list for later processing
            self.product_items.append({
                'company': company,
                'brand': brand,
                'product_name': product_name,
                'quantity': quantity,
                'unit_price': price,
                'cgst': cgst,
                'sgst': sgst,
                'cess': cess,
                'company_invoice': company_invoice
            })

            # Update totals
            self.update_product_totals()

            # Clear fields (except company and invoice)
            # self.product_brand_entry.delete(0, tk.END)
            self.product_name_entry.delete(0, tk.END)
            self.product_qty_entry.delete(0, tk.END)
            self.product_price_entry.delete(0, tk.END)
            self.cess_entry.delete(0, tk.END)
            self.cess_entry.insert(0, "0.0")

        except ValueError:
            messagebox.showerror("Error", "Please enter valid numeric values")

    def clear_product_items(self):
        """Clear all items from product list"""
        self.product_items_tree.delete(*self.product_items_tree.get_children())
        self.product_items.clear()

    def save_all_products(self):
        """Save all products in the list to database"""
        if not self.product_items:
            messagebox.showerror("Error", "No products to save")
            return

        companies = self.db.get_companies()
        purchase_date = datetime.now().strftime("%Y-%m-%d")

        try:
            for product in self.product_items:
                company_id = companies.get(product['company'])
                if not company_id:
                    messagebox.showerror("Error", f"Company '{product['company']}' not found")
                    return

                self.db.add_product(
                    company_id,
                    product['brand'],
                    product['product_name'],
                    product['quantity'],
                    product['unit_price'],
                    product['cgst'],
                    product['sgst'],
                    product['cess'],
                    purchase_date,
                    product['company_invoice']
                )

            messagebox.showinfo("Success", f"{len(self.product_items)} product(s) added successfully")
            self.load_products()  # Refresh product list
            self.load_billing_products()  # Refresh billing product list
            self.product_window.destroy()
            self.product_window = None

        except Exception as e:
            logger.error(f"Error adding products: {e}")
            messagebox.showerror("Error", f"Failed to add products: {str(e)}")

    def add_product_entry(self, parent_frame, companies, gst_slabs):
        """Add a set of product entry fields"""
        entry_frame = ttk.Frame(parent_frame, borderwidth=1, relief="solid", padding=10)
        entry_frame.pack(fill=tk.X, pady=5, padx=5)

        # Product details
        ttk.Label(entry_frame, text="Brand:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        brand_entry = ttk.Entry(entry_frame)
        brand_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        ttk.Label(entry_frame, text="Product Name:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        product_entry = ttk.Entry(entry_frame)
        product_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        ttk.Label(entry_frame, text="Quantity:").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        qty_entry = ttk.Entry(entry_frame)
        qty_entry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")

        ttk.Label(entry_frame, text="Unit Price:").grid(row=3, column=0, padx=5, pady=5, sticky="e")
        price_entry = ttk.Entry(entry_frame)
        price_entry.grid(row=3, column=1, padx=5, pady=5, sticky="ew")

        # GST slab selection
        ttk.Label(entry_frame, text="GST Slab (%):").grid(row=4, column=0, padx=5, pady=5, sticky="e")
        gst_slab_combobox = ttk.Combobox(entry_frame, values=gst_slabs)
        gst_slab_combobox.grid(row=4, column=1, padx=5, pady=5, sticky="ew")
        if gst_slabs:
            gst_slab_combobox.current(0)

        # CGST (auto-calculated as half of GST slab)
        ttk.Label(entry_frame, text="CGST %:").grid(row=5, column=0, padx=5, pady=5, sticky="e")
        cgst_label = ttk.Label(entry_frame, text="0.0", relief=tk.SUNKEN)
        cgst_label.grid(row=5, column=1, padx=5, pady=5, sticky="ew")

        # SGST (auto-calculated as half of GST slab)
        ttk.Label(entry_frame, text="SGST %:").grid(row=6, column=0, padx=5, pady=5, sticky="e")
        sgst_label = ttk.Label(entry_frame, text="0.0", relief=tk.SUNKEN)
        sgst_label.grid(row=6, column=1, padx=5, pady=5, sticky="ew")

        # CESS (default to 0)
        ttk.Label(entry_frame, text="CESS %:").grid(row=7, column=0, padx=5, pady=5, sticky="e")
        cess_entry = ttk.Entry(entry_frame)
        cess_entry.insert(0, "0.0")  # Default value
        cess_entry.grid(row=7, column=1, padx=5, pady=5, sticky="ew")

        # Update CGST and SGST when GST slab changes
        def update_gst_rates(event=None):
            try:
                gst_slab = float(gst_slab_combobox.get())
                cgst = gst_slab / 2
                sgst = gst_slab / 2
                cgst_label.config(text=f"{cgst:.2f}")
                sgst_label.config(text=f"{sgst:.2f}")
            except ValueError:
                pass

        gst_slab_combobox.bind("<<ComboboxSelected>>", update_gst_rates)
        gst_slab_combobox.bind("<KeyRelease>", update_gst_rates)

        # Initialize GST rates
        update_gst_rates()

        # Store references to all entries
        if not hasattr(entry_frame, 'product_entries'):
            entry_frame.product_entries = []

        entry_frame.product_entries.append({
            'brand_entry': brand_entry,
            'product_entry': product_entry,
            'qty_entry': qty_entry,
            'price_entry': price_entry,
            'gst_slab_combobox': gst_slab_combobox,
            'cgst_label': cgst_label,
            'sgst_label': sgst_label,
            'cess_entry': cess_entry
        })

    
    def add_gst_slab(self):
        """Add a new GST slab rate"""
        rate = simpledialog.askfloat("Add GST Slab", "Enter GST rate (%):", parent=self.root)
        if rate is not None:
            try:
                self.db.add_gst_slab(rate)
                messagebox.showinfo("Success", "GST slab added successfully")
            except Exception as e:
                logger.error(f"Error adding GST slab: {e}")
                messagebox.showerror("Error", f"Failed to add GST slab: {str(e)}")
    
    # Enhance the purchases window to show invoices:
    def open_purchases_window(self):
        """Open window to view purchase history with enhanced filtering"""
        if hasattr(self, 'purchases_window') and self.purchases_window.winfo_exists():
            self.purchases_window.lift()
            return
    
        self.purchases_window = tk.Toplevel(self.root)
        self.purchases_window.title("Purchase History")
        self.purchases_window.geometry("1200x600")
    
        # Filter frame with type selection
        filter_frame = ttk.Frame(self.purchases_window)
        filter_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(filter_frame, text="Filter Type:").pack(side=tk.LEFT, padx=5)
        self.filter_type_combobox = ttk.Combobox(filter_frame, 
                                               values=["All", "Product", "Company", "Invoice"],
                                               state="readonly", width=10)
        self.filter_type_combobox.pack(side=tk.LEFT, padx=5)
        self.filter_type_combobox.current(0)  # Default to "All"
        
        ttk.Label(filter_frame, text="Filter:").pack(side=tk.LEFT, padx=5)
        self.purchase_filter_entry = ttk.Entry(filter_frame)
        self.purchase_filter_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        ttk.Button(filter_frame, text="Apply Filter", command=self.refresh_purchases_view).pack(side=tk.LEFT, padx=5)
    
        # Treeview with scrollbars
        tree_frame = ttk.Frame(self.purchases_window)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
        yscroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
    
        xscroll = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)
    
        self.purchases_tree = ttk.Treeview(
            tree_frame,
            columns=("ID", "Company", "Brand", "Product", "Original", "Remaining", "Sold", "Price", "Purchase Date", "Invoice"),
            show='headings',
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set
        )
    
        # Configure scrollbars
        yscroll.config(command=self.purchases_tree.yview)
        xscroll.config(command=self.purchases_tree.xview)
    
        # Configure columns
        columns = [
            ("ID", 50),
            ("Company", 150),
            ("Brand", 100),
            ("Product", 150),
            ("Original", 80),
            ("Remaining", 80),
            ("Sold", 80),
            ("Price", 80),
            ("Purchase Date", 120),
            ("Invoice", 120)
        ]
    
        for col, width in columns:
            self.purchases_tree.heading(col, text=col)
            self.purchases_tree.column(col, width=width, anchor=tk.CENTER)
    
        self.purchases_tree.pack(fill=tk.BOTH, expand=True)
    
        # Load initial data
        self.refresh_purchases_view()
    
    def refresh_purchases_view(self):
        """Refresh the purchases treeview with applied filters"""
        filter_type = self.filter_type_combobox.get()
        filter_value = self.purchase_filter_entry.get().strip()
        
        # Build SQL query based on filter type
        cursor = self.db.get_cursor()
        query = '''
            SELECT 
                p.id,
                c.name as company_name,
                p.brand,
                p.product_name,
                p.original_quantity,
                p.quantity as remaining_quantity,
                p.unit_price,
                p.cgst,
                p.sgst,
                p.cess,
                p.purchase_date,
                p.company_invoice,
                (p.original_quantity - p.quantity) as sold_quantity
            FROM products p
            LEFT JOIN companies c ON p.company_id = c.id
        '''
        
        params = []
        
        if filter_value:
            if filter_type == "Product":
                query += " WHERE p.product_name LIKE ?"
                params.append(f"%{filter_value}%")
            elif filter_type == "Company":
                query += " WHERE c.name LIKE ?"
                params.append(f"%{filter_value}%")
            elif filter_type == "Invoice":
                query += " WHERE p.company_invoice LIKE ?"
                params.append(f"%{filter_value}%")
        
        query += " ORDER BY p.purchase_date DESC"
        cursor.execute(query, params)
        purchases = cursor.fetchall()
    
        # Clear current items
        for item in self.purchases_tree.get_children():
            self.purchases_tree.delete(item)
    
        # Add filtered purchases
        for purchase in purchases:
            self.purchases_tree.insert("", "end", values=(
                purchase['id'],
                purchase['company_name'],
                purchase['brand'],
                purchase['product_name'],
                purchase['original_quantity'],
                purchase['remaining_quantity'],
                purchase['sold_quantity'],
                f"{purchase['unit_price']:.2f}",
                purchase['purchase_date'],
                purchase['company_invoice'] or ""
            ))
    
    def on_invoice_selected(self, event):
        """Load items for selected invoice"""
        selected = self.invoices_tree.selection()
        if not selected:
            return

        invoice_no = self.invoices_tree.item(selected[0], "values")[0]

        cursor = self.db.get_cursor()
        cursor.execute('''
            SELECT 
                p.company_invoice as invoice_no,
                p.product_name,
                p.brand,
                p.quantity,
                p.unit_price,
                (p.quantity * p.unit_price) as total
            FROM products p
            WHERE p.company_invoice = ?
            ORDER BY p.product_name
        ''', (invoice_no,))

        items = cursor.fetchall()

        # Clear current items
        for item in self.purchase_items_tree.get_children():
            self.purchase_items_tree.delete(item)

        # Add new items
        for item in items:
            self.purchase_items_tree.insert("", "end", values=(
                item['invoice_no'],
                item['product_name'],
                item['brand'],
                item['quantity'],
                f"{item['unit_price']:.2f}",
                f"{item['total']:.2f}"
            ))

    def load_invoices(self):
        """Load invoices into the treeview"""
        cursor = self.db.get_cursor()
        cursor.execute('''
            SELECT 
                p.company_invoice as invoice_no,
                c.name as company,
                p.purchase_date as date,
                p.product_name,
                p.brand,
                p.quantity,
                p.unit_price,
                (p.quantity * p.unit_price) as total_value
            FROM products p
            LEFT JOIN companies c ON p.company_id = c.id
            WHERE p.company_invoice IS NOT NULL AND p.company_invoice != ''
            ORDER BY p.purchase_date DESC, p.company_invoice
        ''')
        purchases = cursor.fetchall()

        # Clear current items
        for item in self.invoices_tree.get_children():
            self.invoices_tree.delete(item)

        # Organize by invoice
        invoice_dict = {}
        for purchase in purchases:
            invoice_no = purchase['invoice_no']
            if invoice_no not in invoice_dict:
                invoice_dict[invoice_no] = {
                    'company': purchase['company'],
                    'date': purchase['date'],
                    'items': [],
                    'total_value': 0
                }
            invoice_dict[invoice_no]['items'].append(purchase)
            invoice_dict[invoice_no]['total_value'] += purchase['total_value']

        # Add to treeview
        for invoice_no, data in invoice_dict.items():
            self.invoices_tree.insert("", "end", values=(
                invoice_no,
                data['company'],
                data['date'],
                len(data['items']),  # Total items
                f"{data['total_value']:.2f}"  # Total value
            ))
    
    def load_purchases(self):
        """Load purchases into the treeview"""
        cursor = self.db.get_cursor()
        cursor.execute("SELECT * FROM purchases ORDER BY purchase_date DESC")
        purchases = cursor.fetchall()
        
        for item in self.purchases_tree.get_children():
            self.purchases_tree.delete(item)
        
        for purchase in purchases:
            self.purchases_tree.insert("", "end", values=(
                purchase['id'],
                purchase['transaction_id'],
                purchase['product_name'],
                purchase['quantity'],
                f"{purchase['unit_price']:.2f}",
                f"{purchase['total_price']:.2f}",
                purchase['purchase_date']
            ))
    
    def open_bills_window(self):
        """Open window to view bills"""
        if hasattr(self, 'bills_window') and self.bills_window.winfo_exists():
            self.bills_window.lift()
            return
        
        self.bills_window = tk.Toplevel(self.root)
        self.bills_window.title("Bill Records")
        self.bills_window.geometry("1000x600")
        
        # Main frame with notebook
        notebook = ttk.Notebook(self.bills_window)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        # Bills tab
        bills_tab = ttk.Frame(notebook)
        notebook.add(bills_tab, text="Bills")
        
        # Bill items tab
        items_tab = ttk.Frame(notebook)
        notebook.add(items_tab, text="Items")
        
        # Setup bills treeview
        bills_container = ttk.Frame(bills_tab)
        bills_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        yscroll = ttk.Scrollbar(bills_container, orient=tk.VERTICAL)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        xscroll = ttk.Scrollbar(bills_container, orient=tk.HORIZONTAL)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.bills_tree = ttk.Treeview(
            bills_container,
            columns=("Bill No", "Customer", "Amount", "Date"),
            show='headings',
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set
        )
        
        yscroll.config(command=self.bills_tree.yview)
        xscroll.config(command=self.bills_tree.xview)
        
        self.bills_tree.heading("Bill No", text="Bill No")
        self.bills_tree.heading("Customer", text="Customer")
        self.bills_tree.heading("Amount", text="Amount")
        self.bills_tree.heading("Date", text="Date")
        
        self.bills_tree.column("Bill No", width=100, anchor=tk.CENTER)
        self.bills_tree.column("Customer", width=200, anchor=tk.W)
        self.bills_tree.column("Amount", width=100, anchor=tk.E)
        self.bills_tree.column("Date", width=150, anchor=tk.CENTER)
        
        self.bills_tree.pack(fill=tk.BOTH, expand=True)
        
        # Setup bill items treeview
        items_container = ttk.Frame(items_tab)
        items_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        yscroll = ttk.Scrollbar(items_container, orient=tk.VERTICAL)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        xscroll = ttk.Scrollbar(items_container, orient=tk.HORIZONTAL)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.bill_items_tree = ttk.Treeview(
            items_container,
            columns=("Bill No", "Product", "Qty", "Price", "Total"),
            show='headings',
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set
        )
        
        yscroll.config(command=self.bill_items_tree.yview)
        xscroll.config(command=self.bill_items_tree.xview)
        
        self.bill_items_tree.heading("Bill No", text="Bill No")
        self.bill_items_tree.heading("Product", text="Product")
        self.bill_items_tree.heading("Qty", text="Qty")
        self.bill_items_tree.heading("Price", text="Price")
        self.bill_items_tree.heading("Total", text="Total")
        
        self.bill_items_tree.column("Bill No", width=100, anchor=tk.CENTER)
        self.bill_items_tree.column("Product", width=200, anchor=tk.W)
        self.bill_items_tree.column("Qty", width=50, anchor=tk.CENTER)
        self.bill_items_tree.column("Price", width=100, anchor=tk.E)
        self.bill_items_tree.column("Total", width=100, anchor=tk.E)
        
        self.bill_items_tree.pack(fill=tk.BOTH, expand=True)
        
        # Load data
        self.load_bills()
        
        # Bind bill selection to load items
        self.bills_tree.bind("<<TreeviewSelect>>", self.on_bill_selected)
    
    def load_bills(self):
        """Load bills into the treeview"""
        cursor = self.db.get_cursor()
        cursor.execute("SELECT * FROM billing ORDER BY bill_date DESC")
        bills = cursor.fetchall()
        
        for item in self.bills_tree.get_children():
            self.bills_tree.delete(item)
        
        for bill in bills:
            self.bills_tree.insert("", "end", values=(
                bill['bill_number'],
                bill['customer_name'],
                f"{bill['total_amount']:.2f}",
                bill['bill_date']
            ))
    
    def on_bill_selected(self, event):
        """Load items for selected bill"""
        selected = self.bills_tree.selection()
        if not selected:
            return
        
        bill_number = self.bills_tree.item(selected[0], "values")[0]
        
        cursor = self.db.get_cursor()
        cursor.execute('''
            SELECT bill_number, product_name, quantity, unit_price, 
                   (quantity * unit_price) as total
            FROM bill_items
            WHERE bill_number = ?
        ''', (bill_number,))
        
        items = cursor.fetchall()
        
        # Clear current items
        for item in self.bill_items_tree.get_children():
            self.bill_items_tree.delete(item)
        
        # Add new items
        for item in items:
            self.bill_items_tree.insert("", "end", values=(
                item['bill_number'],
                item['product_name'],
                item['quantity'],
                f"{item['unit_price']:.2f}",
                f"{item['total']:.2f}"
            ))
    
    def reset_application_state(self):
        """Reset application state by clearing temporary data"""
        self.added_items.clear()
        self.temp_products.clear()
        self.total_cgst = 0.0
        self.total_sgst = 0.0
        
        if hasattr(self, 'billing_items_tree'):
            self.billing_items_tree.delete(*self.billing_items_tree.get_children())
            self.subtotal_label.config(text="0.00")
            self.cgst_label.config(text="0.00")
            self.sgst_label.config(text="0.00")
            self.total_label.config(text="0.00")
        
        messagebox.showinfo("Success", "Application state has been reset")
    
    def update_status(self, message):
        """Update status bar message"""
        self.status_bar.config(text=f"{self.current_user['username']} | {message}")
        self.root.after(5000, lambda: self.status_bar.config(text=f"Logged in as: {self.current_user['username']}"))

# Main function
def main():
    root = tk.Tk()
    app = StockManagementApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()